# Klipal

YouTube, TikTok, Instagram, Facebook ve X (Twitter) videolarını filigransız, etiketsiz ve istenen kalitede (MP4 / MP3) indiren web uygulaması.

**Yapım: selcukyus**

---

## İndir ve çalıştır (Windows)

1. Sağdaki **Releases** bölümünden en son `Klipal-vX.Y.Z.zip` dosyasını indir.
2. Zip'i bir klasöre çıkar ve **`baslat.bat`** dosyasına çift tıkla.
   - Python yoksa kendisi kurar; kurulumdan sonra `baslat.bat`'ı bir kez daha aç.
   - İlk açılışta gereken her şeyi (ffmpeg ve YouTube motoru dahil) kurar; birkaç dakika sürer.
3. Site **http://localhost:8000** adresinde kendiliğinden açılır. Siyah pencere açık kaldığı sürece çalışır.

Aynı Wi-Fi'deki telefondan girmek için siyah pencerede yazan adresi kullan (örn. `http://192.168.1.23:8000`). Windows Güvenlik Duvarı sorarsa **Özel ağlar** için izin ver.

macOS / Linux: `./baslat.sh` · Docker: `docker build -t klipal . && docker run -p 8000:8000 klipal`

## Site olarak yayın (GitHub Pages)

Arayüz GitHub Pages'te yayınlanır: **https://sinekvalesii.github.io/Klipal/**

GitHub Pages yalnızca sabit dosya sunar; videoyu indiren motor (`app.py`) bir bilgisayarda ya da sunucuda çalışmak zorundadır. Site, motorla şöyle bağlanır:

1. **Pages'i aç (bir kez):** Depo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Motoru internete aç:** Motorun çalıştığı bilgisayarda [Tailscale](https://tailscale.com) kur, giriş yap ve şu komutu çalıştır:
   ```
   tailscale funnel --bg 8000
   ```
   Çıktıdaki `https://….ts.net` adresi motorun adresidir.
3. **Adresi siteye tanıt:** Depo → **Settings → Secrets and variables → Actions → Variables → New repository variable**
   - Ad: `KLIPAL_API`
   - Değer: `https://….ts.net` (sonunda `/` olmadan)
4. **Actions → Site (GitHub Pages) → Run workflow** ile siteyi yeniden yayınla.

Motor varsayılan olarak yalnızca `https://sinekvalesii.github.io` adresinden gelen isteklere izin verir. Kendi alan adını bağlarsan `ALLOWED_ORIGINS` ortam değişkenine ekle.

Motor kapalıyken site açılır ama indirme çalışmaz; ziyaretçiye bunu söyleyen bir uyarı çıkar.

## Otomatik iş akışları (GitHub Actions)

| İş akışı | Ne zaman | Ne yapar |
|---|---|---|
| **Test** | Her push | Uygulamayı kurar ve testleri çalıştırır |
| **Site (GitHub Pages)** | `main`'e her push | Arayüzü Pages'e yayınlar |
| **İndirilebilir sürüm** | `VERSION` dosyası değişince | `Klipal-vX.Y.Z.zip` oluşturup Releases'e ekler |

Yeni sürüm çıkarmak için `VERSION` dosyasındaki numarayı artır (örn. `1.0.1`) ve `main`'e gönder.

## Özellikler
- 5 platform: YouTube (Shorts dahil), TikTok, Instagram (Reels, çoklu gönderi), Facebook (video, Reels, `fb.watch`), X
- Platformun sunduğu her çözünürlük ve tahmini dosya boyutu; MP3 320 kbps
- Filigransız: TikTok'ta filigranlı akışlar elenir
- Etiketsiz: başlık, açıklama, etiket ve bölüm bilgisi silinir (yeniden kodlama yok); dosya adında #, @, emoji kalmaz
- Gerçek ilerleme çubuğu, sıra sistemi, linki yapıştırınca otomatik başlama
- Telefonda paylaş menüsünden indirme (uygulama olarak yüklenebilir)
- Açık / koyu tema, mobil uyumlu
- Güvenlik: yalnızca 5 platformun çözücüleri açık, IP başına istek sınırı, dosyalar 15 dakika sonra silinir

## Ayarlar (ortam değişkenleri)
| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PORT` | 8000 | Sunucu portu |
| `HOST` | 0.0.0.0 | Yalnız bu bilgisayardan erişim için `127.0.0.1` |
| `ALLOWED_ORIGINS` | `https://sinekvalesii.github.io` | Motoru kullanabilecek site adresleri (virgülle) |
| `MAX_FILE_MB` | 2048 | Tek dosya üst sınırı |
| `MAX_CONCURRENT` | 3 | Aynı anda indirilen video |
| `RATE_LIMIT_PER_MIN` | 20 | IP başına dakikalık istek |
| `FILE_TTL_MIN` | 15 | Hazır dosyanın sunucuda kalma süresi |
| `COOKIES_FILE` | — | Giriş isteyen içerikler için `cookies.txt` yolu |
| `TRUST_PROXY` | 0 (Docker'da 1) | Vekil sunucu arkasında gerçek kullanıcı IP'si için `1` |

## Sorun giderme
| Belirti | Çözüm |
|---|---|
| "İndirme motoruna ulaşılamadı" | Motor kapalı: `baslat.bat` ve `tailscale funnel` açık olmalı. |
| "Bu yayına henüz indirme motoru bağlanmadı" | `KLIPAL_API` değişkenini ayarla, Pages iş akışını yeniden çalıştır. |
| Bir platform birden çalışmıyor | `baslat.bat` her açılışta yt-dlp'yi günceller; programı kapatıp aç. |
| Instagram "giriş gerekiyor" | `COOKIES_FILE` ayarla. |

Durum kontrolü: `http://localhost:8000/health`

## Yasal
Yalnızca herkese açık ve indirme hakkına sahip olduğunuz içerikleri indirin. Başkasına ait içeriği izinsiz yeniden yayınlamak telif hakkı ihlalidir. YouTube, TikTok, Instagram, Facebook ve X, sahiplerinin ticari markalarıdır; Klipal bu şirketlerle bağlantılı değildir.

Yazı tipi: Bricolage Grotesque (SIL Open Font License, `static/fonts/OFL.txt`).
