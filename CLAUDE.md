# CLAUDE.md

Bu dosya, bu repoda çalışan Claude (ve geliştiriciler) için mimari rehberdir.

## 📝 Dokümantasyon disiplini (ZORUNLU KURAL)

**Her geliştirme veya fix'te, ilgili `.md` dosyalarını aynı değişiklikle birlikte
güncelle.** Kod ve doküman asla ayrışmamalı. Hangi durumda hangisi:

| Değişiklik türü | Güncellenecek doküman |
|-----------------|------------------------|
| Her değişiklik (özellik/fix) | `CHANGELOG.md` (Unreleased altına madde) |
| Kullanım/kurulum/ayar değişti | `README.md` |
| Mimari/katman/karar değişti | `CLAUDE.md` (bu dosya) |
| Deploy/operasyon/risk etkisi var | `DEPLOYMENT.md` |
| Yeni `.env`/`config.yaml` anahtarı | `.env.example` + `config/config.yaml` + ilgili `.md` |
| Sürüm çıkışı | `VERSION` + `CHANGELOG.md` (tarih + sürüm) |

Bir değişiklik "tamam" sayılmaz; ilgili doküman güncellenmeden ve `ruff check`/
`pytest` yeşil olmadan bitmez.

## Ne yapar?

Hikvision IP kameralardan RTSP substream alır, paketleme etiketindeki **Code128
barkodu** okur, sipariş no'yu çözer ve **Shopify siparişine** "şu kamerada, şu
zamanda paketlendi" bilgisini (yapısal metafield; order note opsiyonel/varsayılan
kapalı — Shopify API Timeline'a comment yazamaz) otomatik yazar. Amaç:
müşteri şikâyetinde saatlerce kamera kaydı taramak yerine saniyeler içinde ilgili
ana gitmek. Tespit anının snapshot'ı kanıt olarak saklanır.

Her şey **tek konteynerde, lokal** çalışır (bulut yok; RTSP LAN'da olduğu için
tespit zorunlu olarak yerel). İnternet kesilse tespit devam eder, Shopify yazımı
kuyruğa alınır.

## Mimari

```
RTSP (substream) → CameraWorker (kamera başına 1 thread)
                       → BarcodeDetector (pyzbar, regex filtre)
                       → on_detection: dedup → snapshot → SQLite (pending)
SQLite (pending) → ShopifyWorker (tek thread) → Shopify GraphQL (metafield; note opsiyonel)
MaintenanceWorker → snapshot retention temizliği + lisans recheck
Admin Web Panel (FastAPI/uvicorn, ana thread) → dashboard, arama, snapshot, kamera CRUD, /health
```

Orchestrator: [app/app.py](app/app.py) `Application` sınıfı her şeyi kurar.
Worker'lar daemon thread; web sunucusu ana thread'i bloklar ve sinyalleri yönetir.

## Katmanlar (nerede ne var)

| Yol | Sorumluluk |
|-----|-----------|
| `app/settings.py` | `.env` → sırlar/deployment (pydantic-settings) |
| `app/config.py` | `config.yaml` → yapısal config (pydantic) + `resolve_camera` (DB→RTSP) |
| `app/camera_worker.py` | RTSP oku, throttle, reconnect, health raporla |
| `app/detection/barcode.py` | pyzbar wrapper, regex filtre, normalize |
| `app/shopify_worker.py` | pending event'leri Shopify'a yaz (retry/rate-limit) |
| `app/integrations/shopify_client.py` | Shopify **GraphQL** Admin API |
| `app/integrations/shopify_auth.py` | client_credentials token al/önbellekle/yenile |
| `app/storage/database.py` | SQLite (events, dedup, **kamera CRUD**, admin sorguları, stats) |
| `app/storage/snapshots.py` | JPEG kaydet + retention cleanup (cv2 tembel import) |
| `app/licensing/` | Ed25519 offline lisans doğrulama |
| `app/monitoring/health.py` | bellek-içi sağlık registry (thread-safe) |
| `app/scheduler.py` | periyodik bakım (retention, lisans) |
| `app/web/` | FastAPI admin panel (Jinja2 + lokal statik, CDN yok) — kamera CRUD dâhil |

## Kritik tasarım kararları

- **İki katmanlı config**: sırlar `.env`'de, yapısal config `config.yaml`'da. Sır asla YAML'a.
- **Kameralar SQLite'ta** (config.yaml'da değil): operasyonel veri (panelden CRUD)
  olduğu için DB'ye taşındı. `Database` kamera CRUD'u tutar; `cameras.rtsp` **ham**
  şablon (`{user}/{pass}`) saklanır, sır DB'ye yazılmaz. `config.resolve_camera`
  okuma sırasında `.env` `CAMERA_*` ile doldurur. `app.py` worker'ları DB'den kurar.
  Yapısal config (detection/shopify/storage/...) hâlâ YAML'da. Worker'lar boot'ta
  kurulur: kamera değişikliği **yeniden başlatmada** etkin olur (hot-reload yok),
  panel banner uyarır (`AppContext.mark_restart_needed`). `config.yaml`'daki olası
  `cameras` bölümü `load_config` tarafından yoksayılır.
- **Paylaşılan PaddleOCR motor havuzu** (`PaddleEnginePool`, `detection.paddle_pool_size`):
  PaddleOCR modeli ağır (~GB). Kamera başına bir model kurulursa N kamera = N model
  → RAM dolar, swap thrash (8 kamerada üretimde yaşandı). Bu yüzden `app.py` **tek**
  havuz kurar (`size` motor), tüm `CameraWorker`'lara aynı paylaşılan
  `PaddleOCRDetector`'ı enjekte eder. PaddleOCR thread-safe değil → her motor kuyruktan
  tek thread'e ödünç verilir; eşzamanlılık `size` ile sınırlı. RAM = `size`× model.
  Çok kamerada CPU ana darboğaz: ana akış yerine substream (`.../<ch>02`) düşünülmeli.
- **Shopify GraphQL** (REST değil): REST Orders API deprecate ediliyor.
  Public arayüz (`ShopifyClient`, `OrderNotFound`, `ShopifyError`) REST'ten miras.
- **Shopify auth — iki yöntem**: (A) `client_id`+`client_secret` ile
  client_credentials token akışı (önerilen; `TokenProvider` token'ı önbelleğe alır,
  süre dolmadan/401'de otomatik yeniler) veya (B) statik `SHOPIFY_ACCESS_TOKEN`
  (fallback). İkisi de varsa (A) önceliklidir. `ShopifyClient.from_settings()` seçer.
  Token, auth header'a **istek başına** dinamik yazılır (token döndüğü için).
- **Lisans offline**: phone-home yok (internetsiz depo). Asimetrik imza — public
  key koda gömülü ([app/licensing/keys.py](app/licensing/keys.py)), private key
  yalnızca satıcıda (`config/private_key.pem`, gitignore'lu).
- **cv2 tembel import** snapshots'ta → web/storage/test katmanı cv2'siz yüklenir.
- **Dedup**: aynı sipariş + aynı kamera, `dedup_window_seconds` içinde yoksayılır;
  farklı kamera yeni event.

## Geliştirme

```bash
pip install -r requirements-dev.txt   # cv2/pyzbar için sistem: libzbar0, ffmpeg
ruff check . && ruff format --check .
pytest                                 # cv2 yoksa barkod testleri atlanır (skip)
```

- Lisans üret/dene: `python scripts/generate_license.py issue --customer X --cameras 8 --days 365`
- Kamera testi: `python scripts/test_camera.py <rtsp_url>`
- Shopify testi: `python scripts/test_shopify.py "#1001"`

## Sürüm uyumu / dikkat

- Python 3.10+ (Docker 3.11). `from __future__ import annotations` her yerde.
- `requirements.txt` pin'li; numpy 1.26 (opencv uyumu) — 2.x ile de çalışır ama
  Docker'da pin korunur.
- Shopify API sürümü `.env` `SHOPIFY_API_VERSION` ile; varsayılan kod içinde.
- `app/web/static/` CDN bağımlılığı **içermemeli** (offline çalışmalı).

## Yol haritası (dökümandan, henüz yapılmadı)

NVR ISAPI playback link, YOLO ROI tespiti (A1000 GPU), OCR fallback, ürün sayma,
çoklu-müşteri/bulut yönetim paneli. Detay: [shopify-paketleme-tespit-sistemi.md](shopify-paketleme-tespit-sistemi.md) §12, §14.
