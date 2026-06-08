# 📦 Packing Detector

Hikvision IP kameralardan RTSP stream alıp paketleme etiketindeki **Code128
barkodu** okur ve ilgili **Shopify siparişine** "şu kamerada, şu zamanda
paketlendi" bilgisini otomatik yazar (order note + metafield). Tespit anının
fotoğrafı kanıt olarak saklanır.

Müşteri "eksik/yanlış ürün geldi" dediğinde: Shopify'da siparişi aç → yorumdaki
kamera ve zamana bak → NVR'da direkt o ana git. **Saatler yerine saniyeler.**

Her şey **tek konteynerde, lokal** çalışır — bulut yok, ek donanım yok, internet
kesilse tespit devam eder (Shopify yazımı kuyruğa alınır).

---

## İçindekiler
- [Mimari](#mimari)
- [Hızlı başlangıç (Docker)](#hızlı-başlangıç-docker)
- [Konfigürasyon](#konfigürasyon)
- [Shopify kurulumu (GraphQL)](#shopify-kurulumu-graphql)
- [Admin Web Panel](#admin-web-panel)
- [Lisanslama](#lisanslama)
- [Geliştirme & test](#geliştirme--test)
- [Sorun giderme](#sorun-giderme)
- [Proje yapısı](#proje-yapısı)

---

## Mimari

```
Hikvision Kameralar ──RTSP──► NVR (ana kayıt, dokunulmaz)
        │
        └──RTSP substream──► ┌──────────────── Docker: packing-detector ───────────────┐
                             │ CameraWorker (kamera/thread) → barkod → dedup → snapshot │
                             │        → SQLite (pending) → ShopifyWorker → Shopify API   │
                             │ MaintenanceWorker (retention + lisans)                    │
                             │ Admin Web Panel (FastAPI) :8080  /health                  │
                             └───────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
                                      Shopify GraphQL Admin API
                                      (order note + metafield)
```

Detaylı mimari ve kararlar: [CLAUDE.md](CLAUDE.md) ·
**deploy & operasyon: [DEPLOYMENT.md](DEPLOYMENT.md)** ·
tam proje dokümanı: [shopify-paketleme-tespit-sistemi.md](shopify-paketleme-tespit-sistemi.md)

---

## Hızlı başlangıç (Docker)

> Hedef: Windows 11 + Docker Desktop (depodaki Dell PC). Linux'ta da çalışır.

```bash
# 1) Ayarları hazırla
cp .env.example .env          # Windows: copy .env.example .env
#   .env içine Shopify token + kamera şifresini yaz
#   config/config.yaml içinde kamera IP'lerini gerçek değerlerle değiştir

# 2) Çalıştır
docker compose up --build -d
docker compose logs -f

# 3) Admin Panel
#   http://localhost:8080
```

Durdurma: `docker compose down`. PC açıldığında otomatik başlaması için Docker
Desktop "Start with Windows" + compose'daki `restart: unless-stopped` yeterli.

**Tam sisteme geçmeden önce parça parça test et:** önce VLC ile RTSP URL'i aç,
sonra `scripts/test_camera.py`, sonra `scripts/test_shopify.py` (bkz.
[Geliştirme & test](#geliştirme--test)).

---

## Konfigürasyon

İki dosya:

| Dosya | İçerik | Git'e gider mi |
|-------|--------|----------------|
| `.env` | Sırlar: Shopify token, kamera şifresi, web/lisans | ❌ (gitignore) |
| `config/config.yaml` | Kameralar, tespit, depolama, bakım, izleme | ✅ |

Önemli `config.yaml` ayarları:

```yaml
detection:
  target_fps: 3                 # saniyede işlenecek frame (CPU yüksekse düşür)
  dedup_window_seconds: 30      # aynı sipariş+kamera tekrar yoksayma
  order_no_regex: '^#?\d{3,8}$' # etikette TR-2026-1234 gibi format varsa değiştir
  add_hash_prefix: true         # '1234' → '#1234' (Shopify araması)
storage:
  snapshot_retention_days: 90   # 0 = silme; scheduler otomatik temizler
```

`.env` anahtarları için [.env.example](.env.example)'a bak.

---

## Shopify kurulumu (GraphQL)

Bu sürüm Shopify **GraphQL Admin API** kullanır (REST Orders API deprecate
ediliyor).

1. Shopify admin → **Settings → Apps and sales channels → Develop apps**
2. **Create an app** → isim ver (örn. "Packing Detector")
3. **Configure Admin API scopes**: `read_orders`, `write_orders`

İki kimlik doğrulama yöntemi var — **birini** seç:

### (A) Önerilen — client_credentials (otomatik token)

Token, uygulama tarafından `client_id` + `client_secret` ile alınır ve süresi
dolunca **otomatik yenilenir** (elle token kopyalamak gerekmez, expire sorunu yok).

4. App'in **API credentials** sayfasından **Client ID** ve **Client secret** al.
5. `.env`:
   ```
   SHOPIFY_SHOP_URL=magazaniz.myshopify.com
   SHOPIFY_CLIENT_ID=xxxxxxxx
   SHOPIFY_CLIENT_SECRET=shpss_xxxxxxxx
   SHOPIFY_API_VERSION=2025-01
   ```

### (B) Alternatif — statik access token

4. **Install app** → **Admin API access token**'ı kopyala (yalnızca bir kez gösterilir!)
5. `.env`:
   ```
   SHOPIFY_SHOP_URL=magazaniz.myshopify.com
   SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxx
   SHOPIFY_API_VERSION=2025-01
   ```
   ⚠️ Bu token süresi dolabilir; dolunca elle yenilemen gerekir. Mümkünse (A)'yı kullan.

> İkisi de tanımlıysa `client_id`+`client_secret` (A) önceliklidir.

Bağlantıyı doğrula: `python scripts/test_shopify.py` (token testi) ·
`python scripts/test_shopify.py "#1001"` (gerçek siparişe test yorumu).

---

## Admin Web Panel

`http://localhost:8080` (port `.env` `WEB_PORT` ile değişir).

- **Dashboard**: bugünkü/toplam tespit, bekleyen Shopify, kamera sağlık durumu,
  lisans, son tespitler
- **Olaylar**: sipariş no / kamera / durum / tarih ile arama + sayfalama
- **Olay detayı**: snapshot önizleme + "Shopify'a tekrar yaz" (not_found/failed için)
- **`/health`**: kimlik doğrulamasız JSON (Docker healthcheck / dış izleme)

Kimlik doğrulama: `.env`'de `ADMIN_PASSWORD` tanımlıysa HTTP Basic devreye girer.
Boşsa panel açık (yalnızca güvenli LAN için). Panel **tamamen offline** çalışır
(CDN yok).

---

## Lisanslama

Ürün, **offline Ed25519 imzalı lisans anahtarı** ile korunur (internetsiz depoda
da çalışır). Satıcı private key ile imzalar; uygulama gömülü public key ile
doğrular.

**Satıcı (bir kez):**
```bash
python scripts/generate_license.py keygen          # anahtar çifti üret
#   → private key: config/private_key.pem (GİZLİ, yedekle, paylaşma)
#   → public key:  app/licensing/keys.py'ye otomatik yazılır
```

**Her müşteri için lisans üret:**
```bash
python scripts/generate_license.py issue --customer "ACME Lojistik" --cameras 8 --days 365
```

**Müşteri kurulumu:** üretilen anahtarı `.env`'e `LICENSE_KEY=...` ya da
`config/license.key` dosyasına koy. Zorunlu kılmak için `.env`'de
`LICENSE_ENFORCE=true` (geçersiz/eksik lisansta sistem başlamaz).
`false` iken (varsayılan geliştirme) sadece uyarı verir.

---

## Geliştirme & test

```bash
# Sistem (pyzbar/opencv için): libzbar0, libgl1, libglib2.0-0, ffmpeg
pip install -r requirements-dev.txt

ruff check . && ruff format --check .
pytest                       # cv2/pyzbar yoksa barkod testleri atlanır
```

**Sıralı doğrulama (saha kurulumu):**
1. **VLC** ile RTSP URL aç — görüntü geliyor mu?
2. `python scripts/test_camera.py "rtsp://admin:SIFRE@192.168.1.101:554/Streaming/Channels/102"`
   — barkodu kameraya göster, konsola düşmeli.
3. `python scripts/test_shopify.py "#1001"` — Shopify Timeline'a test yorumu.
4. `docker compose up --build -d` — tam sistem.

---

## Sorun giderme

| Belirti | Bak |
|---------|-----|
| "Stream açılamadı" | VLC ile URL'i dene · `ping <ip>` · RTSP yetkili kullanıcı · şifrede özel karakter varsa URL-encode · substream yerine `/101` |
| Barkod okunmuyor | etiket küçük/eğik/bulanık mı · ışık · `target_fps` artır · ana stream'e geç |
| Shopify'a yazılmıyor | `docker compose logs` · Panel → Olaylar → durum `not_found` (regex/sipariş yok) ya da `failed` (API hatası) |
| Çok false-positive | `dedup_window_seconds` artır · `order_no_regex` daralt · ürün barkodları karışıyor olabilir |
| Yüksek CPU | `target_fps` düşür · substream (`/102`) kullan · kapalı kameraları `enabled: false` |
| Kamera sessizce düştü | Dashboard'da kamera durumu `stale`/`down` · `/health` JSON |

---

## Proje yapısı

```
app/
├── app.py                 # orchestrator (Application)
├── main.py / healthcheck.py
├── settings.py            # .env (pydantic-settings)
├── config.py              # config.yaml (pydantic)
├── camera_worker.py · shopify_worker.py · scheduler.py · logger.py
├── detection/barcode.py
├── integrations/shopify_client.py   # GraphQL
├── storage/{database,snapshots}.py
├── licensing/{license,keys}.py
├── monitoring/health.py
└── web/                   # FastAPI panel (routes, server, security, templates, static)
config/config.yaml
scripts/{test_camera,test_shopify,generate_license}.py
tests/                     # pytest
Dockerfile · docker-compose.yml · requirements*.txt · pyproject.toml
.github/workflows/ci.yml
```

---

**Lisans:** Proprietary. Tüm bileşenler açık kaynak kütüphanelerle, sıfır ek
donanım maliyetiyle mevcut altyapı üzerine kurulur.
