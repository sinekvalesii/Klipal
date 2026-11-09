/* Klipal — arayüz mantığı */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  // İndirme motorunun adresi: boşsa aynı sunucu (static/config.js ile ayarlanır)
  const API = String(window.KLIPAL_API || '').replace(/\/+$/, '');
  const api = (path) => API + path;
  const el = {
    form: $('form'), url: $('url'), clear: $('clearBtn'), paste: $('pasteBtn'), go: $('goBtn'),
    plats: $('plats'), msg: $('msg'), msgText: $('msgText'),
    result: $('result'), rThumb: $('rThumb'), rDur: $('rDur'), rTitle: $('rTitle'), rPlat: $('rPlat'), rBy: $('rBy'),
    itemsBox: $('itemsBox'), itemsLabel: $('itemsLabel'), items: $('items'),
    qlist: $('qlist'), alist: $('alist'), audioBox: $('audioBox'), rErr: $('rErr'), newBtn: $('newBtn'),
    frame: $('frame'), fImg: $('fImg'), fPlat: $('fPlat'), fDur: $('fDur'),
    toast: $('toast'), themeBtn: $('themeBtn'), scUrl: $('scUrl'), scCopy: $('scCopy'),
  };

  const PLATFORMS = {
    youtube: ['youtube.com', 'youtu.be', 'youtube-nocookie.com'],
    tiktok: ['tiktok.com'],
    instagram: ['instagram.com', 'instagr.am'],
    facebook: ['facebook.com', 'fb.watch', 'fb.com'],
    x: ['x.com', 'twitter.com', 't.co'],
  };
  const NAMES = { youtube: 'YouTube', tiktok: 'TikTok', instagram: 'Instagram', facebook: 'Facebook', x: 'X' };
  const URL_RE = /https?:\/\/[^\s<>"'“”]+/i;
  const BARE_RE = /(?:^|\s)((?:[\w-]+\.)*(?:youtube\.com|youtu\.be|tiktok\.com|instagram\.com|facebook\.com|fb\.watch|x\.com|twitter\.com)\/\S*)/i;
  const BUSY = ['starting', 'queued', 'downloading', 'processing'];
  const nf = (d) => new Intl.NumberFormat('tr-TR', { maximumFractionDigits: d });

  let current = null;      // /api/info yanıtı (+ seçili video)
  let infoCtrl = null;
  let pendingUrl = '';
  let frameRatio = 9 / 16;
  const jobs = new Map();  // satır anahtarı -> indirme durumu

  /* ── yardımcılar ── */
  function extractUrl(text) {
    const t = String(text || '').trim();
    let m = t.match(URL_RE);
    let u = m ? m[0] : '';
    if (!u) { m = t.match(BARE_RE); if (m) u = 'https://' + m[1]; }
    return u.replace(/[)\].,;!?»”’'"]+$/, '');
  }
  function detect(u) {
    try {
      const host = new URL(u).hostname.toLowerCase();
      for (const [key, hosts] of Object.entries(PLATFORMS)) {
        if (hosts.some((h) => host === h || host.endsWith('.' + h))) return key;
      }
    } catch (_) { /* geçersiz adres */ }
    return null;
  }
  function fmtSize(b) {
    if (!b) return '';
    if (b < 1e6) return '≈ ' + nf(0).format(Math.max(1, b / 1e3)) + ' KB';
    if (b < 1e9) return '≈ ' + nf(b < 1e8 ? 1 : 0).format(b / 1e6) + ' MB';
    return '≈ ' + nf(2).format(b / 1e9) + ' GB';
  }
  function fmtDur(s) {
    if (s == null || s === '') return '';
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
  }
  function fmtEta(s) {
    if (!s || s < 1) return '';
    return s < 60 ? Math.ceil(s) + ' sn kaldı' : Math.ceil(s / 60) + ' dk kaldı';
  }
  const fmtSpeed = (bps) => (bps ? nf(1).format(bps / 1e6) + ' MB/sn' : '');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const rowFor = (key) => document.querySelector('.q[data-key="' + CSS.escape(key) + '"]');

  let toastTimer;
  function toast(text) {
    el.toast.textContent = text;
    el.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.hidden = true; }, 4000);
  }
  function showMsg(text) { el.msgText.textContent = text; el.msg.hidden = false; }
  function hideMsg() { el.msg.hidden = true; }

  function syncInput() {
    const v = el.url.value.trim();
    el.clear.hidden = !v;
    const p = detect(extractUrl(v));
    for (const li of el.plats.querySelectorAll('li[data-p]')) li.classList.toggle('is-on', li.dataset.p === p);
  }
  function setBusy(on) {
    el.go.disabled = on;
    el.go.classList.toggle('is-busy', on);
    el.go.querySelector('.btn-go__text').textContent = on ? 'Getiriliyor' : 'Videoyu getir';
  }

  /* ── önizleme çerçevesi ── */
  function sizeFrame(ratio) {
    const col = el.frame.parentElement.clientWidth || 400;
    const maxW = Math.min(col, 400);
    const maxH = Math.max(340, Math.min(560, window.innerHeight - 150));
    let w, h;
    if (ratio >= 1) { w = maxW; h = w / ratio; }
    else { h = maxH; w = h * ratio; if (w > maxW) { w = maxW; h = w / ratio; } }
    el.frame.style.width = Math.round(w) + 'px';
    el.frame.style.height = Math.round(h) + 'px';
  }
  function frameEmpty() {
    frameRatio = 9 / 16;
    sizeFrame(frameRatio);
    el.frame.dataset.state = 'empty';
    el.fImg.removeAttribute('src');
  }
  function frameShow(item) {
    const ratio = item.w && item.h ? item.w / item.h : (current.platform === 'youtube' ? 16 / 9 : 9 / 16);
    frameRatio = Math.min(Math.max(ratio, 0.5), 2.4);
    sizeFrame(frameRatio);
    el.fPlat.textContent = current.platform_name;
    el.fDur.textContent = fmtDur(item.duration);
    if (!item.thumb) { el.frame.dataset.state = 'noimg'; return; }
    el.frame.dataset.state = 'loading';
    el.fImg.onload = () => { el.frame.dataset.state = 'ready'; };
    el.fImg.onerror = () => { el.frame.dataset.state = 'noimg'; };
    el.fImg.src = item.thumb;
  }

  /* ── video bilgisi ── */
  function skelLine(width) {
    const s = document.createElement('span');
    s.className = 'skel-line';
    s.style.width = width;
    return s;
  }
  function skelRow() {
    const d = document.createElement('div');
    d.className = 'q skel';
    d.setAttribute('aria-hidden', 'true');
    return d;
  }
  function showSkeleton(platform) {
    el.result.hidden = false;
    el.rTitle.replaceChildren(skelLine('92%'), skelLine('58%'));
    el.rPlat.textContent = NAMES[platform];
    el.rBy.textContent = '';
    el.rThumb.removeAttribute('src');
    el.rDur.textContent = '';
    el.itemsBox.hidden = true;
    el.rErr.hidden = true;
    el.qlist.replaceChildren(skelRow(), skelRow(), skelRow());
    el.audioBox.hidden = true;
    el.newBtn.hidden = true;
    el.frame.dataset.state = 'loading';
    if (window.innerWidth < 980) {                      // telefonda sonucu görünür yap
      requestAnimationFrame(() => el.result.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    }
  }
  function hideResult() {
    el.result.hidden = true;
    frameEmpty();
  }

  async function analyze(raw) {
    const u = extractUrl(raw);
    if (!u) { hideResult(); showMsg('Önce bir video linki yapıştır.'); el.url.focus(); return; }
    if (el.url.value !== u) el.url.value = u;
    syncInput();
    const platform = detect(u);
    if (!platform) {
      hideResult();
      showMsg('Bu link desteklenmiyor. YouTube, TikTok, Instagram, Facebook veya X’ten bir video linki yapıştır.');
      return;
    }
    if (!API && /\.github\.io$/.test(location.hostname)) {
      hideResult();
      showMsg('Bu yayına henüz indirme motoru bağlanmadı. Site sahibi, motor adresini GitHub ayarlarındaki KLIPAL_API değişkenine yazmalı.');
      return;
    }
    if (infoCtrl && pendingUrl === u) return;                       // aynı link zaten yükleniyor
    if (!infoCtrl && current && current.input === u && !el.result.hidden) return;  // zaten açık
    hideMsg();
    if (infoCtrl) infoCtrl.abort();
    const ctrl = (infoCtrl = new AbortController());
    pendingUrl = u;
    setBusy(true);
    showSkeleton(platform);
    try {
      const res = await fetch(api('/api/info'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: u }),
        signal: ctrl.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'Video bilgisi alınamadı. Tekrar dene.');
      for (const it of data.items || []) if (it.thumb) it.thumb = api(it.thumb);
      current = Object.assign(data, { input: u, active: 0 });
      render();
    } catch (e) {
      if (e.name === 'AbortError') return;
      current = null;
      hideResult();
      showMsg(e instanceof TypeError
        ? 'İndirme motoruna ulaşılamadı. İnternet bağlantını kontrol et; motor kendi bilgisayarında çalışıyorsa baslat.bat penceresi açık olmalı.'
        : e.message);
    } finally {
      if (infoCtrl === ctrl) { infoCtrl = null; pendingUrl = ''; setBusy(false); }
    }
  }

  function render() {
    const c = current;
    const it = c.items[c.active];
    el.result.hidden = false;
    el.newBtn.hidden = false;
    el.rErr.hidden = true;
    el.rTitle.textContent = it.title || c.title || c.platform_name + ' videosu';
    el.rPlat.textContent = c.platform_name;
    el.rBy.textContent = it.uploader || c.uploader || '';
    el.rDur.textContent = fmtDur(it.duration);
    if (it.thumb) el.rThumb.src = it.thumb; else el.rThumb.removeAttribute('src');

    if (c.items.length > 1) {
      el.itemsBox.hidden = false;
      el.itemsLabel.textContent = 'Bu gönderide ' + c.items.length + ' video var';
      el.items.replaceChildren(...c.items.map((x, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.setAttribute('aria-pressed', String(i === c.active));
        b.setAttribute('aria-label', (i + 1) + '. video');
        if (x.thumb) {
          const img = document.createElement('img');
          img.src = x.thumb; img.alt = ''; img.loading = 'lazy';
          b.append(img);
        }
        const n = document.createElement('span');
        n.textContent = String(i + 1);
        b.append(n);
        b.addEventListener('click', () => { if (c.active !== i) { c.active = i; render(); } });
        return b;
      }));
    } else {
      el.itemsBox.hidden = true;
    }

    el.qlist.replaceChildren(...it.qualities.map((q, i) => makeRow(q, it, i === 0 && it.qualities.length > 1)));
    if (it.audio) { el.alist.replaceChildren(makeRow(it.audio, it, false)); el.audioBox.hidden = false; }
    else { el.alist.replaceChildren(); el.audioBox.hidden = true; }
    frameShow(it);
  }

  /* ── kalite satırları ── */
  const icon = (id) => '<svg class="' + id + '" width="22" height="22" aria-hidden="true"><use href="#' + id + '"/></svg>';

  function makeRow(q, it, best) {
    const key = current.url + '|' + it.index + '|' + q.q;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'q';
    b.dataset.key = key;
    b.innerHTML =
      '<span class="q__fill"></span>' +
      '<span class="q__main"><span class="q__label"></span><span class="q__tag"></span></span>' +
      '<span class="q__meta"><span class="q__size"></span><span class="q__pct"></span><span class="q__sub"></span></span>' +
      '<span class="q__go">' + icon('i-down') + icon('i-check') + '<span class="q__spin"></span></span>';
    b.querySelector('.q__label').textContent = q.label;
    b.querySelector('.q__tag').textContent = q.tag || '';
    if (best) {
      const s = document.createElement('span');
      s.className = 'q__best';
      s.textContent = 'En iyi';
      b.querySelector('.q__main').append(s);
    }
    b.dataset.size = fmtSize(q.size);
    b.dataset.aria = [q.label, q.tag, q.size ? fmtSize(q.size).replace('≈', 'yaklaşık') : ''].filter(Boolean).join(', ');
    b.addEventListener('click', () => onRow(key, q, it));
    paintRow(b, jobs.get(key));
    return b;
  }

  function paintRow(b, st) {
    if (!b) return;
    const s = st ? st.status : 'idle';
    const fill = b.querySelector('.q__fill');
    const size = b.querySelector('.q__size');
    const pct = b.querySelector('.q__pct');
    const sub = b.querySelector('.q__sub');
    b.classList.toggle('is-busy', BUSY.includes(s));
    b.classList.toggle('is-processing', s === 'processing');
    b.classList.toggle('is-done', s === 'ready');
    size.textContent = s === 'ready' ? 'İndirildi' : b.dataset.size;
    if (s === 'starting' || s === 'queued') {
      fill.style.width = '0%';
      pct.textContent = s === 'queued' ? 'Sırada' : 'Başlıyor';
      sub.textContent = '';
    } else if (s === 'downloading') {
      const p = Math.floor(st.progress || 0);
      fill.style.width = p + '%';
      pct.textContent = '%' + p;
      sub.textContent = fmtEta(st.eta) || fmtSpeed(st.speed);
    } else if (s === 'processing') {
      pct.textContent = 'Hazırlanıyor';
      sub.textContent = '';
    } else if (s === 'ready') {
      fill.style.width = '100%';
    } else {
      fill.style.width = '0%';
    }
    const label = b.dataset.aria;
    b.setAttribute('aria-label', s === 'ready' ? label + ', indirildi, tekrar indir'
      : BUSY.includes(s) ? label + ', ' + (pct.textContent || 'hazırlanıyor') : label + ', indir');
  }

  function setJob(key, st) {
    jobs.set(key, st);
    paintRow(rowFor(key), st);
  }
  function failJob(key, message) {
    jobs.delete(key);
    paintRow(rowFor(key), null);
    el.rErr.textContent = message;
    el.rErr.hidden = false;
  }

  async function onRow(key, q, it) {
    const st = jobs.get(key);
    if (st && BUSY.includes(st.status)) return;
    if (st && st.status === 'ready') {
      try {                                   // dosya hâlâ sunucuda mı?
        const r = await fetch(api('/api/job/' + encodeURIComponent(st.job)), { cache: 'no-store' });
        const d = await r.json().catch(() => ({}));
        if (r.ok && d.status === 'ready') { save(st.job, st.name); return; }
      } catch (_) { /* yeniden hazırlanır */ }
      jobs.delete(key);
    }
    el.rErr.hidden = true;
    const url = current.url;
    setJob(key, { status: 'starting' });
    try {
      const res = await fetch(api('/api/download'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, quality: q.q, item: it.index }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || 'İndirme başlatılamadı. Tekrar dene.');
      setJob(key, { status: 'queued', job: data.job });
      poll(key, data.job);
    } catch (e) {
      failJob(key, e instanceof TypeError ? 'Sunucuya ulaşılamadı. Bağlantını kontrol edip tekrar dene.' : e.message);
    }
  }

  async function poll(key, job) {
    let misses = 0;
    for (;;) {
      await sleep(700);
      let d;
      try {
        const r = await fetch(api('/api/job/' + encodeURIComponent(job)), { cache: 'no-store' });
        d = await r.json().catch(() => ({}));
        if (!r.ok) { failJob(key, d.error || 'İndirme durumu alınamadı. Tekrar dene.'); return; }
        misses = 0;
      } catch (_) {
        if (++misses < 10) continue;
        failJob(key, 'Sunucu bağlantısı koptu. Tekrar dene.');
        return;
      }
      if (d.status === 'error') { failJob(key, d.error || 'Video indirilemedi.'); return; }
      if (d.status === 'ready') {
        setJob(key, { status: 'ready', job, name: d.name });
        save(job, d.name);
        return;
      }
      setJob(key, { status: d.status, job, progress: d.progress, eta: d.eta, speed: d.speed });
    }
  }

  function save(job, name) {
    const a = document.createElement('a');
    a.href = api('/api/file/' + encodeURIComponent(job));
    a.download = name || '';
    document.body.append(a);
    a.click();
    a.remove();
    toast('Dosya iniyor: ' + (name || 'video'));
  }

  /* ── olaylar ── */
  el.url.addEventListener('input', syncInput);
  el.url.addEventListener('paste', () => setTimeout(() => {
    const u = extractUrl(el.url.value);
    if (u && detect(u)) analyze(u);
  }, 0));
  el.clear.addEventListener('click', () => { el.url.value = ''; syncInput(); hideMsg(); el.url.focus(); });
  el.form.addEventListener('submit', (e) => { e.preventDefault(); analyze(el.url.value); });
  el.paste.addEventListener('click', async () => {
    if (!navigator.clipboard || !navigator.clipboard.readText) {
      el.url.focus();
      toast('Kutuya uzun basıp “Yapıştır”ı seç.');
      return;
    }
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) { toast('Pano boş. Önce videonun linkini kopyala.'); return; }
      el.url.value = extractUrl(text) || text.trim();
      syncInput();
      analyze(el.url.value);
    } catch (_) {
      el.url.focus();
      toast('Panoya erişim izni verilmedi. Linki kutuya kendin yapıştır.');
    }
  });
  el.newBtn.addEventListener('click', () => {
    current = null;
    el.url.value = '';
    syncInput();
    hideMsg();
    hideResult();
    window.scrollTo({ top: 0, behavior: 'smooth' });
    el.url.focus({ preventScroll: true });
  });

  let resizeRaf = 0;
  window.addEventListener('resize', () => {
    cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(() => sizeFrame(frameRatio));
  });

  /* ── tema ── */
  const root = document.documentElement;
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const theme = () => root.dataset.theme || (mq.matches ? 'dark' : 'light');
  function syncTheme() {
    const dark = theme() === 'dark';
    el.themeBtn.setAttribute('aria-label', dark ? 'Açık temaya geç' : 'Koyu temaya geç');
    if (root.dataset.theme) {
      for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.setAttribute('content', dark ? '#0A1220' : '#F3F5F6');
    }
  }
  el.themeBtn.addEventListener('click', () => {
    const next = theme() === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (_) { /* depolama kapalı */ }
    syncTheme();
  });
  if (mq.addEventListener) mq.addEventListener('change', syncTheme);
  syncTheme();

  /* ── iPhone kısayolu adresi ── */
  el.scUrl.textContent = new URL('./', location.href).href + '?url=';
  el.scCopy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(el.scUrl.textContent); toast('Adres kopyalandı.'); }
    catch (_) { toast('Kopyalanamadı. Adresi seçip elle kopyala.'); }
  });

  /* ── paylaş menüsünden ya da ?url= ile gelen link ── */
  function incomingUrl() {
    const s = location.search;
    if (!s) return '';
    const raw = s.match(/^\?url=([\s\S]*)$/);          // iOS kısayolu linki kodlamadan ekleyebilir
    if (raw && !/[?&](?:title|text)=/.test(s.slice(1))) {
      let v = raw[1];
      try { v = decodeURIComponent(v); } catch (_) { /* olduğu gibi kullan */ }
      return extractUrl(v);
    }
    const p = new URLSearchParams(s);
    for (const k of ['url', 'text', 'title']) {
      const u = extractUrl(p.get(k));
      if (u) return u;
    }
    return '';
  }

  frameEmpty();
  syncInput();
  const incoming = incomingUrl();
  if (incoming) {
    history.replaceState(null, '', location.pathname);
    el.url.value = incoming;
    analyze(incoming);
  }

  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    window.addEventListener('load', () => { navigator.serviceWorker.register('sw.js').catch(() => {}); });
  }
})();
