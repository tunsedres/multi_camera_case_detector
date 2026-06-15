# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Format [Keep a Changelog](https://keepachangelog.com/) temellidir ve proje
[Semantic Versioning](https://semver.org/) kullanır.

## [Unreleased]

### Eklendi
- **Tespit motorları — OCR / PaddleOCR / YOLO** (`detection.mode`): etiketteki
  sipariş numarasını okumak için çoklu yöntem. `paddle` (PaddleOCR, **varsayılan** —
  en doğru, offline gömülü model), `ocr` (Tesseract — hızlı ama rakam karıştırabilir),
  `barcode` (pyzbar), `yolo` (YOLO barkod-bölge tespiti, opsiyonel/GPU). Barkod bu
  kamera açısında çok küçük kaldığı için OCR yolu kullanılıyor.
  `app/detection/{ocr,paddle_ocr,yolo_barcode,voting,types}.py` eklendi.
- **Çoklu-kare oylama** (`min_votes`, `vote_window_seconds`): bir numara pencere
  içinde N kez tutarlı okununca onaylanır → tek-tük yanlış OCR okumaları elenir.
- **Günlük tekrar engelleme** (`dedup_mode: daily`): aynı sipariş günde 1 kez
  yazılır (kameradan bağımsız); 'window' modu eski saniye-tabanlı davranış.
- **Panel girişi (login)**: `ADMIN_PASSWORD` tanımlıysa `/login` ekranı + imzalı
  session cookie (HMAC, stdlib) + "Çıkış". `SESSION_SECRET` ile kalıcı oturum.
  Eski HTTP Basic kaldırıldı. `app/web/security.py` yeniden yazıldı.
- **Panelden yeniden başlatma**: kamera ayarı değişince banner'da "🔄 Şimdi Yeniden
  Başlat" — süreç SIGTERM ile çıkar, Docker `restart: unless-stopped` geri getirir.
- **Shopify order ID ile arama** (`lookup='id'`): barkod modunda order name yerine
  order ID ile doğrudan sorgu (`find_order_by_id`, `node(id:)`).
- **Panelden kamera yönetimi (SQLite)**: Admin Panel'de `/settings/cameras` sayfası —
  kamera ekle / düzenle / sil / aç-kapat. Kameralar artık `config.yaml` yerine
  **SQLite** (`events.db` `cameras` tablosu) içinde tutulur. RTSP `{user}/{pass}`
  ham şablon olarak saklanır (sır DB'ye yazılmaz; `.env` `CAMERA_*` ile doldurulur).
  Worker'lar açılışta kurulduğu için değişiklik sonrası "yeniden başlat" banner'ı
  gösterilir. `Database`'e kamera CRUD (`list/add/update/delete/toggle_camera`,
  `next_camera_id`), `config.py`'a `resolve_camera()` eklendi.
- **Shopify client_credentials akışı**: `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET`
  tanımlıysa token `/admin/oauth/access_token`'dan otomatik alınır ve süresi
  dolmadan/401 alınca otomatik yenilenir. Statik `SHOPIFY_ACCESS_TOKEN` artık
  isteğe bağlı (fallback). `app/integrations/shopify_auth.py` (`TokenProvider`)
  ve `ShopifyClient.from_settings()` eklendi.
- `DEPLOYMENT.md` — deploy süreci, kritik durumlar/riskler, bakım & rollback,
  sürüm öncesi kontrol listesi
- CLAUDE.md'ye **dokümantasyon disiplini** kuralı: her geliştirme/fix ilgili
  `.md` dosyalarını da güncellemeli

### Düzeltildi
- **PaddleOCR native bellek sızıntısı — KESİN çözüm: periyodik süreç yeniden başlatma**
  (`maintenance.max_uptime_minutes`, varsayılan 45 dk): paddlepaddle 2.6.2 her inference'ta
  native bellek sızdırıyor — üretimde **ÖLÇÜLDÜ: ~130 MB/dk, lineer**, thread sayısı sabit
  (135) → thread değil, per-inference native sızıntı. `enable_mkldnn=False` ve idle-recycle
  bunu DURDURMADI (sızıntı motorlar meşgulken oluyor; paddle belleği yalnızca SÜREÇ ÇIKINCA
  bırakıyor). `MaintenanceWorker` artık uptime sınırını geçince `os.kill(SIGTERM)` ile süreci
  nazikçe sonlandırır (panel restart'ı ile aynı mekanizma, `app/web/context.py`); Docker
  `restart: unless-stopped` taze RSS ile geri getirir (~2-3 sn kesinti). Runway boot→OOM
  ~68 dk olduğu için 45 dk güvenli. 0 = kapalı. (`app/scheduler.py`, `app/config.py`,
  `app/app.py`, `config/config.yaml`)
- **Bellek emniyet kemeri + thread oversubscription**: `docker-compose.yml` `mem_limit: 10g`
  — periyodik restart yanlış ayarlanırsa bile HOST (15.6 GB) swap thrash'e DÜŞMESİN, konteyner
  OOM-kill + `restart: unless-stopped` ile dönsün. Ayrıca Dockerfile `OMP/OPENBLAS/MKL_NUM_THREADS=1`
  + `FLAGS_use_mkldnn=0`: paddle CPU backend ayarsızken çekirdek sayısı kadar OpenMP thread
  açıp load avg'i ~12'ye çıkarıyordu (oversubscription); thread'leri sabitler. NOT: bu BELLEK
  sızıntısını çözmez (ölçümle doğrulandı) — yalnızca CPU/load baskısını azaltır.
  (`Dockerfile`, `docker-compose.yml`)
- **PaddleOCR native bellek sızıntısı** (`enable_mkldnn=False`): MKLDNN açıkken (paddle
  varsayılanı) CPU backend her FARKLI girdi şekli için bir kernel/primitive önbelleğe
  alıp asla atmıyordu. Canlı RTSP karelerinin det boyutu kare-kare değiştiği için bu
  önbellek sınırsız büyüyordu → native bellek ~200 MB/dk sızıyor (üretimde 7→10 GB /
  15 dk), Python gc'ye görünmüyordu (C++ allocator'da). `PaddleEnginePool._make_engine`
  artık `enable_mkldnn=False` veriyor → sızıntı kaynağında durur. Ek emniyet kemeri:
  `PaddleEnginePool.recycle()` + `MaintenanceWorker` periyodik boş-motor geri dönüşümü
  (`maintenance.paddle_recycle_hours`, varsayılan 6 saat; 0 = kapalı) — uzun çalışmada
  artık native büyümeyi sıfırlar. (`app/detection/paddle_ocr.py`, `app/scheduler.py`,
  `app/app.py`, `app/config.py`)
- **Olaylar sayfasında boş kamera filtresi 422 hatası veriyordu**: form boş alanları
  boş string olarak gönderiyor (`camera_id=`), `int | None` query param bunu parse
  edemeyip `int_parsing` hatası dönüyordu. `camera_id` artık string alınıp endpoint
  içinde int'e çevriliyor; boş → `None`, geçersiz → 400. (`app/web/routes.py`)
- **Telefon no'su yanlış sipariş olarak okunuyordu**: `order_no_regex` `'#'`i opsiyonel
  yapıyordu (`^#?\d{6,10}$`), bu yüzden etiket arkasındaki fişte boşlukları atılmış
  telefon ("0850 222 22 00" → "0850222200", 10 hane) geçerli sipariş sanılıyordu.
  Artık `'#'` zorunlu (`^#\d{6,10}$`) — gerçek sipariş no'su her zaman `#` ile başlar.
- **Çoklu kamerada RAM patlaması** (`PaddleEnginePool`): her `CameraWorker` kendi
  PaddleOCR modelini kuruyordu → 8 kamera = 8 model kopyası → 16 GB RAM dolup swap'e
  düşüyor, sistem thrash ediyordu. Artık `app.py` **paylaşılan** bir motor havuzu
  kurar (`detection.paddle_pool_size`, varsayılan 2) ve tüm worker'lara enjekte eder.
  RAM = `size`× model (8× değil); PaddleOCR thread-safe olmadığı için her motor tek
  thread'e ödünç verilir.

### Değişti
- **Paketleme bilgisi artık order.note yerine yalnızca metafield'e yazılıyor**
  (`shopify.write_to_order_note: false` varsayılan). Müşteri talebi: bilgi
  paylaşılan Notes kutusunu kirletmesin, Timeline'da görünsün. Ancak Shopify Admin
  API'si Timeline'a comment yazamaz (yalnızca note/tags/metafield) → en yakın temiz
  çözüm yapısal metafield. `order.note`'u geri açmak için flag'i `true` yap.
- **Kameralar YAML'dan SQLite'a taşındı**: `config.yaml`'daki `cameras` bölümü
  artık **yoksayılır** (yapısal config — detection/shopify/storage — YAML'da kalır).
  `app.py` worker'ları DB'den kurar (`_load_cameras`). Mevcut kullanıcılar
  kameralarını panelden yeniden girmeli (otomatik göç yok).
- `ShopifyClient` artık her isteğin auth header'ını `token_provider`'dan dinamik
  okur; 401 alındığında (provider varsa) token bir kez tazelenip istek tekrarlanır.
- `app.py` startup kontrolü: `SHOPIFY_ACCESS_TOKEN` yerine artık token **veya**
  client_id+secret'tan biri yeterli.

## [1.0.0] — 2026-06-08

### Eklendi
- Çoklu kamera RTSP barkod tespiti (pyzbar / Code128) — kamera başına thread
- SQLite event store + dedup penceresi + Shopify yazma kuyruğu
- Shopify **GraphQL** Admin API entegrasyonu (order note + metafield)
- Snapshot saklama + otomatik retention temizliği (scheduler)
- Lisanslama/aktivasyon katmanı (Ed25519 imzalı offline lisans anahtarı)
- Admin Web Panel (FastAPI + HTMX): dashboard, sipariş arama, snapshot önizleme,
  event yeniden kuyruğa alma, sistem/kamera sağlık durumu
- Sağlık (health) registry + `/health` JSON endpoint (Docker healthcheck)
- Tipli config doğrulama (pydantic-settings)
- Test paketi (barcode, database, licensing, shopify, config, web)
- GitHub Actions CI (lint + test), sürümleme ve paketleme

### Notlar
- İlk sürüm "önce tek müşteri" odaklı; mimari ileride çoklu-müşteri/bulut panel
  eklenebilecek şekilde modüler kuruldu.
