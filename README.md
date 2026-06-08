# Shopify Paketleme Tespit Sistemi

Hikvision IP kameralardan RTSP stream alıp, paketleme etiketindeki barkodu okuyarak Shopify siparişine otomatik yorum/metafield ekler.

## 📦 Mimari Özet

```
┌──────────────────────────────────────────────────────────┐
│ Hikvision Kameralar ──RTSP──► NVR (ana kayıt)            │
│         │                                                 │
│         └──RTSP (substream)──► Detection Container       │
│                                       │                   │
│                                       ▼                   │
│                          ┌──────────────────────┐        │
│                          │ 1. Barkod tespit     │        │
│                          │ 2. SQLite'a kayıt    │        │
│                          │ 3. Shopify API       │        │
│                          │ 4. Snapshot sakla    │        │
│                          └──────────────────────┘        │
└──────────────────────────────────────────────────────────┘
```

## ⚙️ Bileşenler

- **`app/camera_worker.py`** — Her kamera için 1 thread, RTSP stream → barkod tespit
- **`app/shopify_worker.py`** — DB'den pending event'leri çekip Shopify'a yazar (rate-limit-friendly)
- **`app/storage/database.py`** — SQLite (events + dedup)
- **`app/storage/snapshots.py`** — Tespit anındaki frame'i JPEG olarak saklar
- **`app/integrations/shopify_client.py`** — Shopify Admin API (REST)

## 🚀 Hızlı Başlangıç (Windows 11 + Docker Desktop)

### 1) Hazırlık

```powershell
# Repo'yu klonla veya kopyala
cd C:\Users\<sen>\projeler
git clone <repo-url> shopify-packing-detector
cd shopify-packing-detector
```

### 2) Konfigürasyon

```powershell
# .env oluştur
copy .env.example .env
notepad .env
```

`.env` içine doldur:

```
SHOPIFY_SHOP_URL=magazaniz.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
CAMERA_USERNAME=admin
CAMERA_PASSWORD=Kamera_Sifreniz
```

`config/config.yaml` içinde kamera IP'lerini gerçek değerlerle değiştir:

```yaml
cameras:
  - id: 1
    name: "Masa 1"
    rtsp: "rtsp://{user}:{pass}@192.168.1.101:554/Streaming/Channels/102"
    enabled: true
```

### 3) Shopify Access Token Alma

1. Shopify admin → **Settings** → **Apps and sales channels** → **Develop apps**
2. **Create an app** → bir isim ver
3. **Configure Admin API scopes** → şu izinleri seç:
   - `read_orders` (sipariş arama için)
   - `write_orders` (note güncelleme için)
   - `write_order_edits`
   - `read_order_edits`
4. **Install app** → **Admin API access token**'ı kopyala (sadece bir kez gösterilir!)

### 4) Önce Bağlantıları Test Et

Tam sistemi başlatmadan önce parça parça test et:

**Kamera testi (Docker'sız, native Python ile):**

```powershell
python -m venv venv
venv\Scripts\activate
pip install opencv-python pyzbar numpy
python scripts\test_camera.py "rtsp://admin:Sifre@192.168.1.101:554/Streaming/Channels/102"
```

Konsola "BARKOD: 1234" gibi satırlar düşmeli. Düşmüyorsa:
- Kamera IP'sini ping'le
- VLC ile aynı URL'i açıp deneme yap
- Substream (`/102`) çalışmıyorsa main stream (`/101`) dene

**Shopify testi:**

```powershell
pip install requests python-dotenv
python scripts\test_shopify.py "#1001"
```

Shopify dev store'unda gerçek bir sipariş no kullan.

### 5) Docker ile Çalıştır

```powershell
docker compose up --build -d
docker compose logs -f
```

Durdurma:

```powershell
docker compose down
```

## 🔧 Önemli Ayarlar

### Sipariş No Formatı

`config/config.yaml`:

```yaml
detection:
  order_no_regex: '^#?\d{3,8}$'    # 3-8 haneli sayı, opsiyonel #
  add_hash_prefix: true             # Etikette '1234' yazıyorsa, Shopify'da '#1234' ara
```

Etiketinde özel format varsa (örn `TR-2026-1234`):

```yaml
order_no_regex: '^TR-\d{4}-\d+$'
add_hash_prefix: false
```

### Dedup Penceresi

Aynı sipariş aynı kamerada art arda okunmasın diye:

```yaml
detection:
  dedup_window_seconds: 30  # 30 saniye içinde tekrar okunursa yoksay
```

### FPS Ayarı

```yaml
detection:
  target_fps: 3  # Saniyede kaç frame işle (kamera 25 FPS gönderir, biz 3'ünü işleriz)
```

Yüksek FPS = daha hızlı tespit ama daha fazla CPU. 3-5 FPS paketleme için ideal.

## 📂 Klasör Yapısı

```
shopify-packing-detector/
├── app/
│   ├── main.py                   # Entry point
│   ├── camera_worker.py          # Her kamera için thread
│   ├── shopify_worker.py         # Shopify queue consumer
│   ├── config.py
│   ├── logger.py
│   ├── detection/
│   │   └── barcode.py            # pyzbar wrapper
│   ├── integrations/
│   │   └── shopify_client.py     # Admin API
│   └── storage/
│       ├── database.py           # SQLite
│       └── snapshots.py          # Frame kaydetme
├── config/
│   └── config.yaml               # Kamera listesi, ayarlar
├── scripts/
│   ├── test_camera.py            # Tek kamera + barkod testi
│   └── test_shopify.py           # Shopify bağlantı testi
├── data/                         # SQLite + snapshot'lar (runtime)
├── logs/                         # Uygulama logları
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                          # Sırlar (git'e gitmez)
└── .env.example
```

## 🐛 Yaygın Sorunlar

### "Stream açılamadı"

1. VLC ile aynı RTSP URL'i açıp dene
2. `ping <kamera_ip>` çalışıyor mu?
3. Kamera kullanıcısı RTSP yetkisi var mı? (Hikvision admin paneli)
4. Şifrede özel karakter (`@`, `:`, `/`) varsa URL-encode et

### "Barkod okunuyor ama Shopify'a yazılmıyor"

```powershell
# Logları kontrol et
docker compose logs --tail=100

# DB'de pending event var mı?
docker compose exec packing-detector sqlite3 /app/data/events.db \
  "SELECT order_no, shopify_status, shopify_error FROM events ORDER BY id DESC LIMIT 20;"
```

`shopify_status='not_found'` görüyorsan: Shopify'da o sipariş yok ya da `status=any` dahi bulamıyor → manuel kontrol.

### Çok fazla false-positive

- `dedup_window_seconds` artır
- `order_no_regex` daraltacak şekilde değiştir (örn min 4 hane)
- Kamera açısını gözden geçir (etiket dik olmalı, parlama olmamalı)

### CPU çok yüksek

- `target_fps` azalt (3 → 2)
- Mainstream yerine substream kullandığından emin ol (`Channels/102`)

## 🔜 Sonraki Adımlar

POC çalışıyorsa şunları ekle:

- [ ] **Admin Panel**: Sipariş no ile arama, snapshot önizleme, NVR playback link'i
- [ ] **NVR ISAPI entegrasyonu**: Shopify yorumunda doğrudan tıklanabilir kayıt link'i
- [ ] **Monitoring**: Her kameranın son tespit zamanı, healthcheck endpoint
- [ ] **Bulk fix**: Geriye dönük tespitleri (snapshot + DB) sonradan Shopify'a yazma aracı
- [ ] **YOLO ROI tespiti**: pyzbar yetmediğinde GPU ile barkod konumu bul, kırp, decode et
