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

### Değişti
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
