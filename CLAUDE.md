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
- **PaddleOCR MKLDNN kapalı** (`enable_mkldnn=False`, ZORUNLU): MKLDNN açıkken (paddle
  varsayılanı) CPU backend her FARKLI girdi şekli için kernel/primitive önbelleğe alıp
  asla atmaz. Canlı RTSP karelerinin det boyutu kare-kare değiştiği için bu önbellek
  sınırsız büyür → native bellek ~200 MB/dk sızar (üretimde 7→10 GB / 15 dk; Python
  gc'ye görünmez çünkü C++ allocator'da). `_make_engine` `enable_mkldnn=False` verir →
  sızıntı kaynağında durur. Emniyet kemeri: `PaddleEnginePool.recycle()` boş motorları
  atıp taze kurar, `MaintenanceWorker` periyodik çağırır (`maintenance.paddle_recycle_hours`,
  varsayılan 6 sa; 0=kapalı) → uzun çalışmada artık native büyümeyi sıfırlar.
- **PaddleOCR native bellek sızıntısı — periyodik süreç restart KESİN çözüm**
  (`maintenance.max_uptime_minutes`): paddlepaddle 2.6.2 her inference'ta native bellek
  sızdırır. Üretimde ÖLÇÜLDÜ: ~130 MB/dk lineer, thread sabit (135) → thread değil,
  per-inference. `enable_mkldnn=False` ve idle-recycle DURDURMADI (motorlar meşgulken
  sızıyor; paddle belleği yalnızca SÜREÇ ÇIKINCA bırakır). `MaintenanceWorker` uptime
  sınırında `os.kill(SIGTERM)` → graceful çıkış → Docker `restart:unless-stopped` taze
  RSS ile döner (panel restart'ıyla aynı mekanizma). 45 dk varsayılan (runway boot→OOM
  ~68 dk). DERS: bellek sorununda ÖNCE ölç (`/proc/1/status` RSS slope + Threads), sonra
  düzelt — ekran görüntüsünden teşhis yanıltır (htop thread-başı paylaşılan RSS gösterir).
- **Thread pinning + mem_limit (yardımcı, bellek sızıntısı DEĞİL)**: Dockerfile
  `OMP/OPENBLAS/MKL_NUM_THREADS=1` paddle OpenMP oversubscription'ı keser (load ~12 →
  düşer) ama BELLEĞİ çözmez (ölçümle doğrulandı). `docker-compose.yml` `mem_limit` son
  emniyet kemeri: restart yanlış ayarlansa bile HOST swap thrash'e düşmez (konteyner
  OOM-kill+restart). İleride: substream'e geçince per-frame native churn azalır.
- **RTSP TCP zorlaması `docker-compose.yml`'de, Python'da DEĞİL** (`OPENCV_FFMPEG_CAPTURE_OPTIONS`):
  OpenCV bu env'i **`import cv2` anında** FFmpeg backend'ini kurarken okur. Modül
  seviyesinde `os.environ` yazmak, satır import'tan sonra kaldığı için sessizce
  ETKİSİZ kalır → stream FFmpeg varsayılanı UDP'ye düşer (üretimde yaşandı).
  UDP'de paket kaybı bozuk NAL unit üretir; belirti logda `RTP: bad cseq` (RTP
  sequence gap — TCP'de ÇIKMAZ, transport'un gerçekte ne olduğunun tek güvenilir
  göstergesi) ve buna bağlı `cu_qp_delta ... outside the valid range` → kare düşer.
  **`Could not find ref with POC N` bu tabloya AİT DEĞİL**: her bağlantıda ~1 kez
  çıkar (decoder stream ortasından girince ilk keyframe'e kadar referans bulamaz),
  TCP'de de çıkar, zararsızdır — transport teşhisinde bu satıra BAKMA (2026-07
  yanlış teşhize yol açtı). Sinsi tarafı: `scripts/test_camera.py` env'i
  cv2'den önce set ettiği için TESTTE TCP, ÜRETİMDE UDP çalışıyordu — "testte temiz,
  sahada gürültülü" tablosu. Bu yüzden asıl ayar konteyner env'i (import sırasından
  bağımsız); `camera_worker.py`'deki `setdefault` yalnızca konteyner dışı yedek ve
  cv2 import'unun ÜSTÜNDE olmak zorunda (E402 bilinçli susturuldu — satırı aşağı
  taşıma). `stimeout` FFmpeg 5.0'da `timeout` oldu; ikisi de veriliyor.
- **Shopify GraphQL** (REST değil): REST Orders API deprecate ediliyor.
  Public arayüz (`ShopifyClient`, `OrderNotFound`, `ShopifyError`) REST'ten miras.
- **Siparişi fulfill etme — fulfillment order üzerinden** (`shopify.fulfill_order`):
  modern GraphQL'de sipariş doğrudan fulfill EDİLMEZ; her sipariş lokasyon başına
  `fulfillmentOrder`'lara bölünür ve bunlar fulfill edilir. `fulfill_order` önce açık
  (`status:open`) fulfillment order'ları çeker, sonra `fulfillmentCreate` ile hepsini
  (tüm kalemler) fulfill eder. Açık fulfillment order yoksa (zaten fulfilled) sessizce
  `False` döner → **idempotent**: aynı sipariş tekrar tespit edilse hata vermez.
  `log_packing_event` metafield yazımından SONRA çağırır (sipariş gid zaten elde,
  ekstra lookup yok). `notify_customer` Shopify müşteri kargo e-postasını tetikler.
  Worker bunu config'ten geçirir; varsayılan açık.
  **Scope tuzağı (üretimde yaşandı, sipariş #966695)**: fulfillment için
  `write_orders` YETMEZ — `fulfillmentCreate` ayrı **fulfillment-order scope'ları**
  ister (`write_merchant_managed_fulfillment_orders` + okuma tarafı
  `read_merchant_managed_fulfillment_orders`). Üstelik `Order.fulfillmentOrders`
  bu scope'a göre filtrelenir: scope eksikse liste BOŞ döner → `fulfill_order`
  hata değil `False` üretir, not/metafield yazılmış olur ama sipariş fulfilled OLMAZ
  (sessiz başarısızlık). Bu yüzden `fulfill_order` durum UNFULFILLED iken liste boşsa
  artık `warning` basar (scope eksikliğini işaret eder).
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
