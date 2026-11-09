"""
Klipal — YouTube, TikTok, Instagram, Facebook ve X video indirici.
Yapım: selcukyus
Flask + yt-dlp + ffmpeg.

Çalıştırma:  python app.py   ->  http://localhost:8000
Windows'ta:  baslat.bat dosyasına çift tıklayın.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict, deque

import yt_dlp
from flask import Flask, Response, abort, jsonify, render_template, request, send_file, send_from_directory
from yt_dlp.extractor import gen_extractor_classes
from yt_dlp.postprocessor.common import PostProcessor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"),
            template_folder=os.path.join(BASE_DIR, "templates"))
app.json.ensure_ascii = False


# ───────────────────────── Ayarlar (ortam değişkenleri) ─────────────────────────
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


HOST = os.getenv("HOST", "0.0.0.0")
PORT = _env_int("PORT", 8000)
MAX_FILE_MB = _env_int("MAX_FILE_MB", 2048)          # tek dosya üst sınırı
MAX_CONCURRENT = _env_int("MAX_CONCURRENT", 3)       # aynı anda indirilen video
MAX_QUEUE = _env_int("MAX_QUEUE", 30)                # sırada bekleyebilecek en fazla iş
RATE_LIMIT_PER_MIN = _env_int("RATE_LIMIT_PER_MIN", 20)
FILE_TTL_MIN = _env_int("FILE_TTL_MIN", 15)          # hazır dosyanın sunucuda kalma süresi
COOKIES_FILE = os.getenv("COOKIES_FILE")             # Instagram / YouTube için cookies.txt (isteğe bağlı)
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER")  # örn. firefox
TRUST_PROXY = os.getenv("TRUST_PROXY") == "1"
# GitHub Pages gibi başka bir adreste yayınlanan arayüzün bu motoru kullanabilmesi için izinli adresler (virgülle)
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.getenv(
    "ALLOWED_ORIGINS", "https://sinekvalesii.github.io").split(",") if o.strip()}        # Render / Nginx arkasında 1 yapın
WORK_DIR = os.getenv("WORK_DIR") or os.path.join(tempfile.gettempdir(), "klipal")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

if TRUST_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def find_ffmpeg() -> str | None:
    """Önce FFMPEG_PATH, sonra sistemdeki ffmpeg, en son pip ile gelen imageio-ffmpeg."""
    path = os.getenv("FFMPEG_PATH")
    if path and os.path.isfile(path):
        return path
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_deno() -> str | None:
    """YouTube için gereken JavaScript motoru (pip 'yt-dlp[deno]' ile gelir)."""
    try:
        from yt_dlp.utils._jsruntime import _find_exe
        path = _find_exe("deno")
        return path if os.path.isfile(path) else shutil.which(path)
    except Exception:
        return shutil.which("deno")


FFMPEG = find_ffmpeg()
DENO = find_deno()


# ───────────────────────── Platformlar ─────────────────────────
PLATFORMS = {
    "youtube":   {"name": "YouTube",   "hosts": ("youtube.com", "youtu.be", "youtube-nocookie.com"), "ie": "youtube.*"},
    "tiktok":    {"name": "TikTok",    "hosts": ("tiktok.com",),                                    "ie": ".*tiktok.*"},
    "instagram": {"name": "Instagram", "hosts": ("instagram.com", "instagr.am"),                    "ie": "instagram.*"},
    "facebook":  {"name": "Facebook",  "hosts": ("facebook.com", "fb.watch", "fb.com"),             "ie": "facebook.*"},
    "x":         {"name": "X",         "hosts": ("x.com", "twitter.com", "t.co"),                   "ie": "twitter.*"},
}
# yt-dlp yalnızca bu platformların çözücülerini kullanır; "generic" çözücü kapalıdır.
# Böylece yönlendirme hileleriyle sunucunun başka adreslere istek atması (SSRF) engellenir.
ALLOWED_IES = [p["ie"] for p in PLATFORMS.values()]
_IE_CLASSES = [ie for ie in gen_extractor_classes()
               if any(re.fullmatch(p, ie.IE_NAME.lower()) for p in ALLOWED_IES)]

URL_RE = re.compile(r"https?://[^\s<>\"'“”]+", re.I)
BARE_RE = re.compile(r"(?:^|\s)((?:[\w-]+\.)*(?:youtube\.com|youtu\.be|tiktok\.com|instagram\.com|"
                     r"facebook\.com|fb\.watch|x\.com|twitter\.com)/\S*)", re.I)


def normalize_url(raw: str) -> str:
    """Paylaşım metninin içinden ilk linki çıkarır, şemasız linke https ekler."""
    text = (raw or "").strip()
    m = URL_RE.search(text)
    if m:
        url = m.group(0)
    else:
        m = BARE_RE.search(text)
        url = "https://" + m.group(1) if m else text
    return url.rstrip(").,;!?»”’'\"]")


def detect_platform(url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    for key, p in PLATFORMS.items():
        if any(host == d or host.endswith("." + d) for d in p["hosts"]):
            return key
    return None


def is_supported(url: str) -> bool:
    return any(ie.suitable(url) for ie in _IE_CLASSES)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)
_META_URL_RE = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)', re.I)


def resolve_url(url: str) -> str | None:
    """fb.watch, facebook.com/share/..., instagr.am gibi kısa linkleri güvenli şekilde açar.
    Her yönlendirme adımı yalnızca desteklenen platform alan adlarına izin verir."""
    for _ in range(6):
        if is_supported(url):
            return url
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "tr,en;q=0.8"})
        try:
            with _opener.open(req, timeout=10) as resp:
                ctype = resp.headers.get("Content-Type", "")
                body = resp.read(600_000).decode("utf-8", "ignore") if "html" in ctype else ""
            m = _META_URL_RE.search(body)
            if not m:
                return None
            nxt = urllib.parse.urljoin(url, m.group(1).replace("&amp;", "&"))
            if nxt == url:
                return None
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if 300 <= e.code < 400 else None
            if not loc:
                return None
            nxt = urllib.parse.urljoin(url, loc)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConnectionError(str(e)) from e
        parsed = urllib.parse.urlparse(nxt)
        nxt_q = urllib.parse.parse_qs(parsed.query)
        if "login" in parsed.path and nxt_q.get("next"):      # Facebook giriş duvarı
            nxt = nxt_q["next"][0]
        if not detect_platform(nxt):
            return None
        url = nxt
    return url if is_supported(url) else None


# ───────────────────────── Yardımcılar ─────────────────────────
_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def client_ip() -> str:
    return request.remote_addr or "?"


def rate_limited(ip: str) -> bool:
    now = time.time()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT_PER_MIN:
            return True
        q.append(now)
        return False


def err(message: str, code: int):
    return jsonify(error=message), code


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def clean_title(title: str | None) -> str:
    """Dosya adından #etiket, @bahsetme, link ve emojileri temizler."""
    t = title or "video"
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[#@]\S+", "", t)
    t = re.sub(r"[^\w\s\-.,()'&!]", "", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip(" .-_,")
    return t[:80].strip(" .-_,") or "video"


def fmt_res(f: dict) -> int | None:
    """Çözünürlük etiketi: dikey videolarda da kısa kenar (1080x1920 -> 1080p)."""
    vals = [v for v in (f.get("height"), f.get("width")) if isinstance(v, (int, float)) and v > 0]
    return int(min(vals)) if vals else None


def fsize(f: dict | None) -> int | None:
    if not f:
        return None
    s = f.get("filesize") or f.get("filesize_approx")
    return int(s) if s else None


def is_watermarked(f: dict) -> bool:
    return "watermark" in (f.get("format_note") or "").lower()


def is_h264(f: dict) -> bool:
    return (f.get("vcodec") or "").lower().startswith(("avc", "h264"))


def res_tag(r: int) -> str:
    if r >= 4000: return "8K"
    if r >= 2000: return "4K"
    if r >= 1400: return "2K"
    if r >= 1000: return "Full HD"
    if r >= 700: return "HD"
    if r >= 470: return "SD"
    return "Düşük"


def first_entry(info: dict | None) -> dict:
    if info and info.get("_type") == "playlist":
        return next((e for e in info.get("entries") or [] if e), info)
    return info or {}


# ───────────────────────── Kapak görseli (proxy) ─────────────────────────
THUMBS: dict[str, tuple[str, float]] = {}


def thumb_url(entry: dict) -> str | None:
    url = entry.get("thumbnail")
    if not url:
        thumbs = [t for t in entry.get("thumbnails") or [] if t.get("url")]
        url = thumbs[-1]["url"] if thumbs else None
    if not url or not url.startswith(("http://", "https://")):
        return None
    token = secrets.token_urlsafe(9)
    THUMBS[token] = (url, time.time())
    return f"/api/thumb/{token}"


# ───────────────────────── Kalite seçenekleri ─────────────────────────
def summarize(entry: dict, platform: str) -> dict | None:
    fmts = [f for f in entry.get("formats") or []
            if not f.get("has_drm") and not (platform == "tiktok" and is_watermarked(f))]
    if not fmts and entry.get("url"):
        fmts = [entry]
    if not fmts:
        return None

    videos = [f for f in fmts if f.get("vcodec") != "none" and fmt_res(f)]
    audios = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audios, key=lambda f: ((f.get("acodec") or "").startswith("mp4a"),
                                            f.get("abr") or f.get("tbr") or 0), default=None)

    rows = []
    for r in sorted({fmt_res(f) for f in videos}, reverse=True)[:7]:
        cands = [f for f in videos if fmt_res(f) == r]
        best = max(cands, key=lambda f: (f.get("fps") or 0, is_h264(f), fsize(f) or 0))
        size = fsize(best)
        if size and best.get("acodec") == "none" and best_audio:
            a = fsize(best_audio)
            size = size + a if a else None
        rows.append({"q": str(r), "label": f"{r}p", "tag": res_tag(r), "size": size, "ext": "mp4"})
    if not rows:
        rows.append({"q": "best", "label": "En iyi kalite", "tag": "", "ext": "mp4",
                     "size": max((fsize(f) or 0 for f in fmts), default=0) or None})

    has_audio = bool(audios) or any(f.get("acodec") != "none" for f in fmts)
    duration = entry.get("duration")
    audio = ({"q": "audio", "label": "MP3", "tag": "320 kbps", "ext": "mp3",
              "size": int(duration * 40_000) if duration else None} if has_audio else None)

    top = max(videos, key=lambda f: fmt_res(f) or 0, default=None) or entry
    return {
        "title": entry.get("title") or "",
        "uploader": entry.get("uploader") or entry.get("channel") or entry.get("uploader_id") or "",
        "duration": duration,
        "thumb": thumb_url(entry),
        "w": top.get("width") or entry.get("width"),
        "h": top.get("height") or entry.get("height"),
        "qualities": rows,
        "audio": audio,
    }


# ───────────────────────── yt-dlp ayarları ─────────────────────────
def base_opts(platform: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": platform == "youtube",
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "allowed_extractors": ALLOWED_IES,
        "max_filesize": MAX_FILE_MB * 1024 * 1024,
        "overwrites": True,
    }
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    elif COOKIES_FROM_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_FROM_BROWSER,)
    return opts


def format_opts(quality: str, platform: str) -> dict:
    """TikTok'ta filigranlı akışlar elenir; kaliteye göre en uygun MP4 seçilir."""
    nowm = "[format_note!*=?watermark]" if platform == "tiktok" else ""
    if quality == "audio":
        return {
            "format": f"bestaudio{nowm}/best{nowm}/bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
        }
    res = "res" if quality == "best" else f"res:{quality}"
    return {
        "format": f"bv*{nowm}+ba/b{nowm}/bv*+ba/b",
        "format_sort": [res, "fps", "vcodec:h264", "acodec:aac", "ext:mp4:m4a"],
        "merge_output_format": "mp4",
    }


def valid_quality(q: str) -> bool:
    return q in ("best", "audio") or (q.isdigit() and 100 <= int(q) <= 4320)


def strip_metadata(path: str) -> None:
    """Başlık, açıklama, etiket, bölüm gibi gömülü bilgileri siler. Yeniden kodlama yok, kalite aynı."""
    if not FFMPEG:
        return
    root, ext = os.path.splitext(path)
    out = f"{root}.clean{ext}"
    ext = ext.lower()
    cmd = [FFMPEG, "-y", "-v", "error", "-i", path]
    cmd += ["-map", "0:a"] if ext == ".mp3" else ["-map", "0:v?", "-map", "0:a?"]
    cmd += ["-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact"]
    if ext in (".mp4", ".m4a", ".mov"):
        cmd += ["-movflags", "+faststart"]
    if ext == ".mp3":
        cmd += ["-id3v2_version", "0", "-write_id3v1", "0"]
    cmd.append(out)
    try:
        subprocess.run(cmd, check=True, timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.replace(out, path)
    except Exception as e:
        log("[uyarı] meta veri temizlenemedi:", e)
        if os.path.exists(out):
            os.remove(out)


class TooLarge(Exception):
    pass


def friendly_error(e: Exception) -> str:
    m = str(e).lower()
    if isinstance(e, TooLarge) or "max-filesize" in m or "larger than" in m:
        return f"Dosya {MAX_FILE_MB} MB sınırını aşıyor. Daha düşük bir kalite seçin."
    if "sign in to confirm" in m or "not a bot" in m:
        return "YouTube bu sunucudan bot doğrulaması istedi. Birkaç dakika sonra tekrar deneyin."
    if "drm" in m:
        return "Bu video DRM korumalı, indirilemez."
    if "live event" in m or "is live" in m or "premieres in" in m:
        return "Canlı yayınlar indirilemez. Yayın bittikten sonra tekrar deneyin."
    if "private" in m or "login" in m or "log in" in m or "cookies" in m or "authentication" in m:
        return "Bu gönderi gizli ya da görmek için giriş gerekiyor. Yalnızca herkese açık gönderiler indirilebilir."
    if "429" in m or "too many requests" in m or "rate-limit" in m:
        return "Platform çok fazla istek nedeniyle geçici olarak engelledi. Birkaç dakika sonra tekrar deneyin."
    if "unsupported url" in m or "no suitable infoextractor" in m:
        return "Bu link türü desteklenmiyor. Gönderinin kendi linkini kopyalayın (Paylaş > Linki kopyala)."
    if "no video" in m or "no media" in m or "requested format is not available" in m:
        return "Bu gönderide indirilebilir video bulunamadı."
    if "not available" in m or "unavailable" in m or "removed" in m or "deleted" in m or "404" in m:
        return "Video kaldırılmış, gizlenmiş ya da bulunduğunuz ülkede erişime kapalı."
    if "ffmpeg" in m or "ffprobe" in m:
        return "Video birleştirilemedi (ffmpeg). Programı yeniden başlatıp tekrar deneyin."
    if "timed out" in m or "connection" in m or "network" in m or "getaddrinfo" in m or "ssl" in m:
        return "Platforma bağlanılamadı. İnternet bağlantısını kontrol edip tekrar deneyin."
    return "Video alınamadı. Linki kontrol edip tekrar deneyin; sorun sürerse birkaç dakika bekleyin."


# ───────────────────────── İndirme işleri ─────────────────────────
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
ACTIVE = ("queued", "downloading", "processing")


class PartsPP(PostProcessor):
    """İndirme başlamadan hemen önce çalışır: kaç parça (görüntü + ses) indirileceğini
    ve boyutlarını kaydeder; böylece ilerleme yüzdesi tek bir çubukta doğru gösterilir."""

    def __init__(self, job: dict):
        super().__init__()
        self.job = job

    def run(self, info):
        parts = info.get("requested_formats") or [info]
        sizes = [fsize(f) or 0 for f in parts]
        if all(sizes) and sum(sizes) > MAX_FILE_MB * 1024 * 1024:
            raise TooLarge("max-filesize")
        if all(sizes):
            weights = [s / sum(sizes) for s in sizes]
        elif len(parts) == 2:
            weights = [0.85, 0.15]
        else:
            weights = [1 / len(parts)] * len(parts)
        self.job["_ids"] = [f.get("format_id") for f in parts]
        self.job["_w"] = weights
        self.job["_done"] = {}
        return [], info


def on_progress(job: dict, d: dict) -> None:
    status = d.get("status")
    if status not in ("downloading", "finished"):
        return
    fid = (d.get("info_dict") or {}).get("format_id")
    ids, weights = job.get("_ids") or [], job.get("_w") or [1.0]
    idx = min(ids.index(fid) if fid in ids else 0, len(weights) - 1)
    done = d.get("downloaded_bytes") or 0
    if status == "finished":
        frac = 1.0
    else:
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        if total:
            frac = done / total
        elif d.get("fragment_count"):
            frac = (d.get("fragment_index") or 0) / d["fragment_count"]
        else:
            frac = 0.0
    parts_done = job.setdefault("_done", {})
    parts_done[idx] = done
    if sum(parts_done.values()) > MAX_FILE_MB * 1024 * 1024:
        raise TooLarge("max-filesize")
    p = sum(weights[:idx]) + weights[idx] * max(0.0, min(frac, 1.0))
    job["progress"] = max(job["progress"], min(p, 0.99))
    job["speed"] = d.get("speed")
    job["eta"] = d.get("eta")


def on_postprocess(job: dict, d: dict) -> None:
    if d.get("status") == "started" and d.get("postprocessor") != "Parts" and job["status"] == "downloading":
        job["status"] = "processing"


def run_job(job: dict, url: str, quality: str, item: int, platform: str) -> None:
    try:
        with _slots:
            job["status"] = "downloading"
            opts = base_opts(platform) | format_opts(quality, platform)
            opts.update(
                outtmpl=os.path.join(job["tmp"], "media.%(ext)s"),
                playlist_items=str(item),
                progress_hooks=[lambda d: on_progress(job, d)],
                postprocessor_hooks=[lambda d: on_postprocess(job, d)],
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.add_post_processor(PartsPP(job), when="before_dl")
                entry = first_entry(ydl.extract_info(url, download=True))

            job["status"] = "processing"
            files = [os.path.join(job["tmp"], f) for f in os.listdir(job["tmp"])
                     if f.startswith("media.") and not f.endswith((".part", ".ytdl", ".json", ".jpg",
                                                                   ".jpeg", ".png", ".webp", ".temp"))]
            if not files:
                raise RuntimeError("İndirme tamamlanamadı (dosya boyutu sınırı ya da bağlantı kesintisi).")
            path = max(files, key=os.path.getsize)
            strip_metadata(path)

            ext = os.path.splitext(path)[1].lstrip(".").lower() or "mp4"
            label = "MP3" if quality == "audio" else ("en iyi" if quality == "best" else f"{quality}p")
            job.update(
                path=path,
                name=f"{clean_title(entry.get('title'))} ({label}).{ext}",
                mime={"mp3": "audio/mpeg", "mp4": "video/mp4", "m4a": "audio/mp4",
                      "webm": "video/webm"}.get(ext, "application/octet-stream"),
                size=os.path.getsize(path),
                progress=1.0,
                status="ready",
            )
            log(f"[hazır] {PLATFORMS[platform]['name']} {label} {job['size'] / 1e6:.1f} MB  {job['name']}")
    except Exception as e:
        log(f"[hata] {platform} {quality}: {e}")
        job.update(status="error", error=friendly_error(e))
        shutil.rmtree(job["tmp"], ignore_errors=True)
    finally:
        job["finished"] = time.time()


def janitor() -> None:
    """Süresi dolan dosyaları ve kayıtları temizler."""
    while True:
        time.sleep(30)
        now = time.time()
        ttl = FILE_TTL_MIN * 60
        with JOBS_LOCK:
            jobs = list(JOBS.items())
        for jid, j in jobs:
            if j["status"] in ACTIVE:
                continue
            last = max(j.get("finished") or 0, j.get("touched") or 0)
            if now - last > ttl:
                shutil.rmtree(j["tmp"], ignore_errors=True)
                if not os.path.exists(j["tmp"]):       # Windows'ta dosya kullanımdaysa sonra tekrar dener
                    with JOBS_LOCK:
                        JOBS.pop(jid, None)
        for tok, (_, ts) in list(THUMBS.items()):
            if now - ts > 3600:
                THUMBS.pop(tok, None)
        with _hits_lock:
            for ip in [ip for ip, q in _hits.items() if not q or now - q[-1] > 120]:
                _hits.pop(ip, None)


# ───────────────────────── Rotalar ─────────────────────────
@app.after_request
def cors_headers(resp):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin and request.path.startswith("/api/") and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["Access-Control-Max-Age"] = "600"
    return resp


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self' 'sha256-CN6avskgvtCn5Sn2MmXOFupP7D1bpAwCNQcdNAhBY4I='; "
        "font-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
    return resp


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    resp = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.static_folder, "icons"), "icon-192.png", mimetype="image/png")


@app.get("/health")
def health():
    return {"ok": True, "yt_dlp": yt_dlp.version.__version__, "ffmpeg": bool(FFMPEG), "deno": bool(DENO)}


@app.post("/api/info")
def api_info():
    if rate_limited(client_ip()):
        return err("Çok fazla istek gönderildi. Bir dakika bekleyip tekrar deneyin.", 429)
    url = normalize_url((request.get_json(silent=True) or {}).get("url", ""))
    platform = detect_platform(url)
    if not platform:
        return err("Bu link desteklenmiyor. YouTube, TikTok, Instagram, Facebook veya X'ten bir video linki yapıştırın.", 400)
    try:
        resolved = resolve_url(url)
    except ConnectionError:
        return err("Platforma bağlanılamadı. İnternet bağlantısını kontrol edip tekrar deneyin.", 502)
    if not resolved:
        return err("Bu link bir videoya gitmiyor. Gönderinin kendi linkini kopyalayın (Paylaş > Linki kopyala).", 400)

    opts = base_opts(platform)
    opts["playlist_items"] = "1" if platform == "youtube" else "1:10"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(resolved, download=False)
    except Exception as e:
        log(f"[hata] bilgi {platform}: {e}")
        return err(friendly_error(e), 422)

    entries = ([e for e in info.get("entries") or [] if e] if info.get("_type") == "playlist" else [info])
    if entries and all(e.get("is_live") for e in entries):
        return err("Canlı yayınlar indirilemez. Yayın bittikten sonra tekrar deneyin.", 422)
    items = []
    for pos, entry in enumerate(entries, 1):
        if entry.get("is_live"):
            continue
        summary = summarize(entry, platform)
        if summary:
            summary["index"] = entry.get("playlist_index") or pos
            items.append(summary)
    if not items:
        return err("Bu gönderide indirilebilir video bulunamadı.", 422)

    log(f"[bilgi] {PLATFORMS[platform]['name']}: {items[0]['title'][:60]!r} ({len(items)} video)")
    return jsonify(platform=platform, platform_name=PLATFORMS[platform]["name"], url=resolved,
                   title=info.get("title") or items[0]["title"],
                   uploader=info.get("uploader") or items[0]["uploader"], items=items)


@app.post("/api/download")
def api_download():
    if rate_limited(client_ip()):
        return err("Çok fazla istek gönderildi. Bir dakika bekleyip tekrar deneyin.", 429)
    data = request.get_json(silent=True) or {}
    url = normalize_url(data.get("url", ""))
    platform = detect_platform(url)
    if not platform or not is_supported(url):
        return err("Link geçersiz. Videoyu yeniden getirin.", 400)
    quality = str(data.get("quality", "best"))
    if not valid_quality(quality):
        return err("Geçersiz kalite seçimi.", 400)
    try:
        item = max(1, min(int(data.get("item", 1)), 50))
    except (TypeError, ValueError):
        item = 1

    with JOBS_LOCK:
        if sum(1 for j in JOBS.values() if j["status"] in ACTIVE) >= MAX_QUEUE:
            return err("Sunucu şu an çok yoğun. Birkaç dakika sonra tekrar deneyin.", 503)
        job_id = secrets.token_urlsafe(16)
        job = {"id": job_id, "status": "queued", "progress": 0.0, "speed": None, "eta": None,
               "error": None, "path": None, "name": None, "size": None, "mime": None,
               "created": time.time(), "finished": None, "touched": None,
               "tmp": tempfile.mkdtemp(prefix="job_", dir=WORK_DIR)}
        JOBS[job_id] = job
    threading.Thread(target=run_job, args=(job, url, quality, item, platform), daemon=True).start()
    return jsonify(job=job_id)


@app.get("/api/job/<job_id>")
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return err("Bu indirmenin süresi doldu. Videoyu yeniden getirin.", 404)
    return jsonify(status=job["status"], progress=round(job["progress"] * 100, 1),
                   speed=job["speed"], eta=job["eta"], error=job["error"],
                   name=job["name"], size=job["size"])


@app.get("/api/file/<job_id>")
def api_file(job_id):
    job = JOBS.get(job_id)
    if not job or job["status"] != "ready" or not job["path"] or not os.path.exists(job["path"]):
        abort(404)
    job["touched"] = time.time()
    resp = send_file(job["path"], as_attachment=True, download_name=job["name"],
                     mimetype=job["mime"], conditional=True, max_age=0)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/thumb/<token>")
def api_thumb(token):
    item = THUMBS.get(token)
    if not item:
        abort(404)
    req = urllib.request.Request(item[0], headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ctype = r.headers.get_content_type()
            data = r.read(5 * 1024 * 1024 + 1)
    except Exception:
        abort(404)
    if not ctype.startswith("image/") or len(data) > 5 * 1024 * 1024:
        abort(404)
    return Response(data, mimetype=ctype, headers={"Cache-Control": "private, max-age=3600"})


# ───────────────────────── Başlatma ─────────────────────────
os.makedirs(WORK_DIR, exist_ok=True)
threading.Thread(target=janitor, daemon=True).start()


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main() -> None:
    local = f"http://localhost:{PORT}"
    if not port_free(HOST, PORT):
        print(f"\n[!] {PORT} portu kullanımda. Klipal zaten açık olabilir: {local}\n"
              f"    Başka bir port için: PORT=8080 ortam değişkenini ayarlayın.\n")
        if os.getenv("OPEN_BROWSER") == "1":
            webbrowser.open(local)
        sys.exit(1)

    for name in os.listdir(WORK_DIR):          # önceki çalıştırmadan kalan geçici dosyalar
        shutil.rmtree(os.path.join(WORK_DIR, name), ignore_errors=True)
    ip = lan_ip()
    print("\n  Klipal çalışıyor  (yapım: selcukyus)")
    print(f"  Bu bilgisayarda:         {local}")
    if ip and HOST == "0.0.0.0":
        print(f"  Telefonda (aynı Wi-Fi):  http://{ip}:{PORT}")
    print(f"  ffmpeg:                  {'hazır' if FFMPEG else 'YOK - MP3 ve yüksek kalite birleştirme çalışmaz'}")
    print(f"  YouTube JS motoru:       {'hazır' if DENO else 'YOK - bazı YouTube videoları açılmayabilir'}")
    print(f"  yt-dlp sürümü:           {yt_dlp.version.__version__}")
    print("  Kapatmak için bu pencereyi kapatın (veya CTRL+C).\n", flush=True)

    if os.getenv("OPEN_BROWSER") == "1":
        threading.Timer(1.2, lambda: webbrowser.open(local)).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=16, channel_timeout=300, ident="Klipal")
    except ImportError:
        app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
