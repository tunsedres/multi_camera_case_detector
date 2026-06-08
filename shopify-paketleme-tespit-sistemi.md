# Shopify Paketleme Tespit Sistemi
## Proje Dokümanı

**Tarih:** Mayıs 2026
**Konum:** Türkiye
**Geliştirici:** Tuncay (in-house)
**Versiyon:** 1.0 (POC tasarımı)

---

## İçindekiler

1. [Problem Tanımı](#1-problem-tanımı)
2. [Çözüm Özeti](#2-çözüm-özeti)
3. [Donanım Envanteri](#3-donanım-envanteri)
4. [Sistem Mimarisi](#4-sistem-mimarisi)
5. [Teknik Kararlar ve Gerekçeleri](#5-teknik-kararlar-ve-gerekçeleri)
6. [Yazılım Bileşenleri](#6-yazılım-bileşenleri)
7. [Veri Akışı](#7-veri-akışı)
8. [Konfigürasyon](#8-konfigürasyon)
9. [Shopify Entegrasyonu](#9-shopify-entegrasyonu)
10. [Kurulum ve Çalıştırma](#10-kurulum-ve-çalıştırma)
11. [Yaygın Sorunlar ve Çözümleri](#11-yaygın-sorunlar-ve-çözümleri)
12. [Geliştirme Yol Haritası](#12-geliştirme-yol-haritası)
13. [Maliyet Analizi](#13-maliyet-analizi)
14. [Gelecek Özellikler](#14-gelecek-özellikler)

---

## 1. Problem Tanımı

### Mevcut Durum

- Depoda **8 adet sipariş paketleme masası** bulunmaktadır
- Her masa üzerinde **1 adet IP kamera** (toplam 8 kamera) paketleme işlemini üstten kayıt altına alır
- Tüm kameralar bir **NVR cihazına** bağlıdır ve sürekli kayıt yapar

### Sorun

Müşteriden bir şikayet geldiğinde (örn: "eksik ürün geldi", "yanlış ürün geldi"):

- O siparişin **tam olarak ne zaman paketlendiği bilinmiyor**
- Kamera kayıtlarının uzun uzun **manuel olarak taranması** gerekiyor
- Hangi masada paketlendiği belirsiz, **8 kameradan da arama yapılıyor**
- Bu süreç **dakikalar değil, saatler** alabiliyor
- Müşteri hizmetleri ve operasyon için ciddi bir verimlilik kaybı

### Çözüm Hedefi

Paketleme sırasında kamera, sipariş etiketindeki barkodu otomatik okusun ve **Shopify siparişine "şu kamerada, şu zamanda paketlendi" bilgisi otomatik olarak yazılsın**. Böylece şikayet geldiğinde:

1. Shopify admin → sipariş aç → yorumda kamera ve zaman bilgisi var
2. NVR'da direkt o kamera ve o zamana git
3. Saniyeler içinde ilgili kayıt bulunur

---

## 2. Çözüm Özeti

### Yüksek Seviye Çözüm

```
┌─────────────────────────────────────────────────────────────────┐
│  MEVCUT ALTYAPI (Dokunulmayacak)                                │
│                                                                  │
│  8 IP Kamera ──RTSP──► NVR (mevcut kayıt sistemi devam eder)   │
│       │                                                          │
│       └──RTSP substream (paralel)──┐                            │
└─────────────────────────────────────┼───────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│  DEPO LOKAL PC (Dell Pro Max Tower T2)                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Docker Container: packing-detector                      │   │
│  │                                                           │   │
│  │  • 8 thread (her kamera için 1)                          │   │
│  │  • pyzbar ile Code128 barkod okuma                       │   │
│  │  • SQLite (dedup + event log)                            │   │
│  │  • Shopify API client                                    │   │
│  │  • Snapshot saklama (delil amaçlı)                       │   │
│  └─────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
                          ┌────────────────┐
                          │  Shopify API   │
                          │  (Order Note + │
                          │   Metafield)   │
                          └────────────────┘
```

### İş Akışı

1. Paketleyici, sipariş etiketini kameraya gösterir
2. Sistem barkodu otomatik tespit eder (Code128)
3. Sipariş no parse edilir (örn: `#1234`)
4. Shopify API'den ilgili sipariş bulunur
5. Sipariş üzerine yorum eklenir: `📦 [22.05.2026 14:30:15] Paketleme: Masa 3 (Kamera #3)`
6. Aynı bilgi metafield olarak da saklanır (yapısal veri için)
7. Tespit anındaki frame snapshot olarak diske kaydedilir (kanıt amaçlı)

---

## 3. Donanım Envanteri

### Kameralar (8 Adet)

**Model:** Hikvision **DS-2CD1043G2-LIUF/M**

| Özellik | Değer |
|---------|-------|
| Çözünürlük | 4 MP (2560×1440) |
| Lens | 2.8mm sabit (ultra geniş açı) |
| Frame Rate | 25 fps (ana stream) |
| IR Mesafesi | 30m |
| ColorVu | ✅ (F harfi) — Gece bile renkli çekim |
| Dual Light | ✅ Beyaz LED + IR |
| Built-in Mic | ✅ (U harfi) — Bu projede kullanılmayacak |
| Codec | H.265+, H.265, H.264+, H.264 |
| RTSP Desteği | ✅ Main + Sub stream |
| SD Kart | ✅ (failover için kullanılabilir) |
| Güç | PoE (802.3af) |

**Stream URL Formatı:**
```
Ana stream (4MP):
rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/101

Substream (yaklaşık 640×480):
rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/102
```

**Önemli:** Detection için **substream kullanılacak** (bandwidth ve CPU tasarrufu, barkod okuma için yeterli).

### NVR

**Model:** Hikvision **DS-7616NI-Q2**

| Özellik | Değer |
|---------|-------|
| Kanal Sayısı | 16 (8 kamera kullanılacak, 8 boş kapasite) |
| HDD Slot | 2 (RAID 1 yapılabilir) |
| Maks. Çözünürlük | 4K |
| Codec Desteği | H.265+, H.265, H.264+, H.264 |
| API | ISAPI + HikCGI |
| Web Erişim | ✅ |
| Programatik Playback | ✅ (ISAPI üzerinden) |

**Önemli:** ISAPI üzerinden programatik playback URL üretilebilir → Shopify yorumuna direkt tıklanabilir link eklenebilir (gelecek faz).

### Sunucu / Lokal PC

**Model:** Dell **Pro Max Tower T2**

| Bileşen | Spec | Proje Yeterliliği |
|---------|------|-------------------|
| CPU | Intel Core Ultra 7 265 (20 core: 8P + 12E) | ✅ Fazlasıyla yeterli |
| RAM | 32 GB DDR5 (1×32) | ✅ Rahat |
| Disk | 1 TB NVMe M.2 SSD | ✅ 3+ yıllık veri/snapshot |
| GPU | NVIDIA A1000 8GB (Ada Lovelace) | ✅ YOLO inference imkanı |
| OS | Windows 11 Pro | ⚠️ Bkz. OS notu aşağıda |

**Kapasite Notu:** Bu donanım, planlanan iş yükünün yaklaşık 3-4 katını rahat kaldırır. 8 kamera artırılsa ya da yeni özellikler (ürün sayma, OCR) eklense bile aynı PC'de kalınabilir.

### Ağ

- Tüm kameralar ve PC **aynı subnet'te** (örn: `192.168.1.0/24`)
- Gigabit switch önerilir
- Statik IP atanmalı (kameralara ve PC'ye)
- UPS (kesintisiz güç kaynağı) önerilir

---

## 4. Sistem Mimarisi

### Mimari Tipi: Lokal, Tek Container

Bulut veya merkezi sunucu **kullanılmıyor**. Tüm işlem depodaki Dell PC üzerinde, tek Docker container içinde gerçekleşiyor.

**Neden bu seçim?**
- Mevcut altyapı (NVR + kameralar) korunuyor
- Düşük gecikme (lokal işlem)
- İnternet kesilse dahi tespit devam eder (Shopify'a yazma kuyruğa alınır, internet gelince gönderilir)
- Düşük maliyet
- Basit deployment

### Stream Yaklaşımı: Substream

Detection için **substream** (`Channels/102`) kullanılıyor. Sebebi:

- 4 MP ana stream: saniyede ~25 frame × 8 kamera = 200 frame yüksek çözünürlükte
- Substream (~640×480): saniyede ~25 frame × 8 kamera ama 30x daha az veri
- Detection için 3 FPS yeterli → toplam 24 frame/sn işleniyor
- CPU kullanımı %80 azalıyor
- Barkod okuma için **substream fazlasıyla yeterli** (paketleyici barkodu 30cm mesafeden gösteriyor)

**NVR ana stream'i kaydetmeye devam ediyor** — kalite kaybı yok.

### İşlem Pipeline'ı

```
Kamera (RTSP) → OpenCV decode → Grayscale → pyzbar decode
                                                  │
                                                  ▼
                                          Regex doğrula (#\d+)
                                                  │
                                                  ▼
                                          Dedup kontrolü (30sn)
                                                  │
                                                  ▼
                                          Snapshot kaydet
                                                  │
                                                  ▼
                                          SQLite event ekle
                                                  │
                                                  ▼
                                          Shopify queue (DB)
                                                  │
                                                  ▼
                                          ShopifyWorker → API
                                                  │
                                                  ▼
                                          Order note + Metafield
```

---

## 5. Teknik Kararlar ve Gerekçeleri

### Karar 1: Tek Container, Çok Thread

**Alternatifler değerlendirildi:**
- Microservices (her şey ayrı container) → Aşırı karmaşık, küçük ölçek için gereksiz
- Multiprocess (her kamera ayrı process) → SQLite paylaşımı zor
- **Multithread (seçilen)** → Basit, yeterli, pyzbar/OpenCV C koduna iniyor, GIL bırakılıyor

### Karar 2: pyzbar (YOLO Yerine Başlangıçta)

GPU'lu sistemimiz olmasına rağmen başlangıçta **pyzbar** ile başlıyoruz:

- Code128 için son derece güvenilir
- CPU'da çalışır, GPU memory yer kaplamaz
- Kurulumu kolay
- Yeterli olmadığı durumda **YOLO ROI tespit + pyzbar decode** kombinasyonuna geçilebilir

A1000 GPU bekliyor, gerekirse YOLO ile barkod konumunu bulup pyzbar'a vermek ileride yapılabilir.

### Karar 3: SQLite (PostgreSQL Yerine)

**Neden SQLite:**
- Tek PC'de tek uygulama, dağıtık veritabanı gereksiz
- Ekstra container yok, daha az hareketli parça
- WAL modu açık → eş zamanlı okumalar + tek yazma sorunsuz
- Backup = tek dosya kopyala
- Yeterli (günde 1000-5000 event = SQLite için çok düşük)

### Karar 4: Detection ve Shopify Yazma Ayrı

İki ayrı worker var:
- **CameraWorker** (her kamera için 1) — Sadece tespit eder, DB'ye yazar
- **ShopifyWorker** (toplam 1 adet) — DB'den pending event'leri çekip Shopify'a yazar

**Faydası:**
- Internet kesilse tespit devam eder, kuyruk birikir, internet gelince işlenir
- Shopify rate limit'i tek noktadan yönetilir (2 req/sn)
- Retry mantığı temiz (failed event'ler tekrar denenir)
- Camera worker'lar Shopify API gecikmesinden etkilenmez

### Karar 5: Dedup Penceresi (30 Saniye)

Aynı sipariş aynı kamerada 30 saniye içinde tekrar okunursa yoksayılır. Sebep:

- Paketleyici barkodu birkaç saniye gösterebilir → 5-10 frame'de okunur
- Aynı sipariş kısa süre içinde tekrar gösterilebilir
- 30 saniye gerçekçi bir paketleme süresi alt sınırı

**Farklı kamerada** okunursa yeni event sayılır (paketleme masaları arası transfer durumu).

### Karar 6: Snapshot Saklama (Her Tespitte)

Her tespit anında o frame JPEG olarak kaydediliyor:

- 1 TB SSD'de günde ~5000 tespit × 200 KB = 1 GB/gün
- 3 yıl kapasite var
- Müşteri şikayetinde "işte o anki etiket fotoğrafı, üstünde sizin sipariş no yazıyor" kanıtı
- Disk ucuz, sigorta pahalı

### Karar 7: TCP Transport (UDP Yerine)

RTSP için TCP transport zorunlu kılındı:

```python
OPENCV_FFMPEG_CAPTURE_OPTIONS = "rtsp_transport;tcp|stimeout;5000000"
```

- UDP daha hızlı ama paket kaybına duyarlı
- TCP biraz daha yüksek gecikme ama paket kaybı yok
- Bizim için gecikme önemli değil, doğruluk önemli

### Karar 8: Order Note + Metafield (İkisi Birden)

Shopify'a iki yöntemle yazıyoruz:

- **order.note** → İnsan okuyacak, admin panelde Timeline'da görünür
- **metafield** → Sistem okuyacak, yapısal veri, ileride raporlama için

Her tespit ayrı bir metafield key alır → birikimli kayıt (note üzerine append yapılır).

---

## 6. Yazılım Bileşenleri

### Klasör Yapısı

```
shopify-packing-detector/
├── app/
│   ├── main.py                       # Entry point + orchestration
│   ├── config.py                     # YAML + .env yükleyici
│   ├── logger.py                     # Yapılandırılmış log
│   ├── camera_worker.py              # Kamera başına thread
│   ├── shopify_worker.py             # Shopify queue consumer
│   ├── detection/
│   │   └── barcode.py                # pyzbar wrapper, regex
│   ├── integrations/
│   │   └── shopify_client.py         # Shopify Admin API
│   └── storage/
│       ├── database.py               # SQLite (events + dedup)
│       └── snapshots.py              # Frame kaydetme
├── config/
│   └── config.yaml                   # Kameralar, ayarlar
├── scripts/
│   ├── test_camera.py                # Tek kamera testi
│   └── test_shopify.py               # Shopify bağlantı testi
├── data/                             # SQLite + snapshot (runtime, git'te yok)
├── logs/                             # App logları (runtime, git'te yok)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                              # Sırlar (git'te yok)
├── .env.example
├── .gitignore
└── README.md
```

### Modüller

| Modül | Sorumluluk |
|-------|-----------|
| `main.py` | Tüm worker'ları başlatır, graceful shutdown yönetir |
| `config.py` | config.yaml'i okur, .env'den sırları doldurur |
| `camera_worker.py` | RTSP stream + barkod tespit + callback |
| `shopify_worker.py` | DB'den pending event çek → Shopify API |
| `detection/barcode.py` | pyzbar wrapper, Code128/QR, regex filtre |
| `storage/database.py` | SQLite operasyonları (insert, dedup, status update) |
| `storage/snapshots.py` | JPEG kaydetme + retention cleanup |
| `integrations/shopify_client.py` | Shopify REST API + retry + rate limit |

### Bağımlılıklar (requirements.txt)

```
opencv-python-headless==4.10.0.84
pyzbar==0.1.9
numpy==1.26.4
requests==2.32.3
python-dotenv==1.0.1
PyYAML==6.0.2
```

Toplam disk: ~150 MB. Sistem kütüphaneleri: `libzbar0`, `libgl1`, `libglib2.0-0`, `ffmpeg`.

---

## 7. Veri Akışı

### Veritabanı Şeması (SQLite)

```sql
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no        TEXT NOT NULL,            -- #1234
    camera_id       INTEGER NOT NULL,
    camera_name     TEXT NOT NULL,            -- "Masa 3"
    detected_at     TIMESTAMP NOT NULL,
    snapshot_path   TEXT,                     -- /app/data/snapshots/...
    shopify_status  TEXT DEFAULT 'pending',   -- pending/success/failed/not_found
    shopify_error   TEXT,
    shopify_synced_at TIMESTAMP,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexler: order_no, detected_at, shopify_status
```

### Snapshot Dosya Yapısı

```
data/snapshots/
├── 2026-05-22/
│   ├── cam1_14-30-15_1042.jpg
│   ├── cam3_14-32-08_1043.jpg
│   └── ...
├── 2026-05-23/
└── ...
```

90 günden eski klasörler otomatik silinir (config'den ayarlanır).

### Event Yaşam Döngüsü

```
[Kamera tespit eder]
        │
        ▼
[Dedup kontrolü] ── duplicate ise atla
        │
        ▼
[Snapshot kaydet]
        │
        ▼
[DB: shopify_status='pending']
        │
        ▼
[ShopifyWorker 2sn'de bir tarama]
        │
        ▼
   ┌─── başarılı ───► status='success'
   │
   ├─── sipariş yok ─► status='not_found' (retry edilmez)
   │
   └─── ağ/api hatası ► status='failed', retry_count++
                       (max 5 retry'a kadar)
```

---

## 8. Konfigürasyon

### config/config.yaml

```yaml
cameras:
  - id: 1
    name: "Masa 1"
    rtsp: "rtsp://{user}:{pass}@192.168.1.101:554/Streaming/Channels/102"
    enabled: true
  - id: 2
    name: "Masa 2"
    rtsp: "rtsp://{user}:{pass}@192.168.1.102:554/Streaming/Channels/102"
    enabled: true
  # ... 8'e kadar

detection:
  target_fps: 3                       # Saniyede kaç frame işle
  dedup_window_seconds: 30            # Aynı sipariş tekrar yoksayma süresi
  order_no_regex: '^#?\d{3,8}$'       # Sipariş no formatı
  add_hash_prefix: true               # '1234' → '#1234' dönüşümü

shopify:
  write_to_order_note: true           # order.note alanına append
  write_to_metafield: true            # Yapısal kayıt için metafield
  note_template: "📦 [{timestamp}] Paketleme: {camera_name} (Kamera #{camera_id})"

storage:
  db_path: "/app/data/events.db"
  snapshots_enabled: true
  snapshots_dir: "/app/data/snapshots"
  snapshot_retention_days: 90
```

### .env

```bash
SHOPIFY_SHOP_URL=magazaniz.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHOPIFY_API_VERSION=2024-01

CAMERA_USERNAME=admin
CAMERA_PASSWORD=Kamera_Sifreniz

LOG_LEVEL=INFO
```

---

## 9. Shopify Entegrasyonu

### Gerekli API İzinleri (Scopes)

Custom App üzerinden alınacak Admin API token için:

- `read_orders` — Sipariş arama
- `write_orders` — order.note güncelleme
- `read_order_edits`
- `write_order_edits`

### Sipariş Arama

```http
GET /admin/api/2024-01/orders.json?name=%231042&status=any&fields=id,name,note
```

**Önemli:** `status=any` parametresi şart, yoksa default `open` siparişler arar, paketleme aşamasındaki siparişlerin bazıları görünmez.

### Order Note'a Append

```http
PUT /admin/api/2024-01/orders/{id}.json
{
  "order": {
    "id": 12345,
    "note": "{önceki not}\n📦 [22.05.2026 14:30:15] Paketleme: Masa 3 (Kamera #3)"
  }
}
```

**Mantık:** Önce mevcut not okunur, yeni satır eklenir, geri yazılır. Üzerine yazmamak kritik.

### Metafield Ekleme

```http
POST /admin/api/2024-01/orders/{id}/metafields.json
{
  "metafield": {
    "namespace": "packing",
    "key": "event_1716383415",
    "value": "📦 [22.05.2026 14:30:15] Paketleme: Masa 3",
    "type": "multi_line_text_field"
  }
}
```

Her tespit unique key alır (epoch timestamp) → birikimli yapısal kayıt.

### Rate Limit Yönetimi

- Shopify REST: 2 req/sn (leaky bucket, 40 burst)
- Tek bir ShopifyWorker thread tüm yazımı yapar
- Her event arasında 500ms bekleme
- 429 alındığında `Retry-After` header'ına uyulur
- 5xx hatalarda exponential backoff (1s, 2s, 4s)

---

## 10. Kurulum ve Çalıştırma

### Ön Hazırlık

1. Dell PC'ye **Docker Desktop for Windows** kur
2. Statik IP ata (örn: `192.168.1.50`)
3. Kameraların IP'lerini not et
4. Kameraların RTSP yetkisi olan bir kullanıcı tanımla (Hikvision admin panelinden)
5. Shopify'da custom app oluştur, access token al

### Test Adımları (Sırayla)

**Adım 1: VLC ile RTSP doğrula**

```
Media → Open Network Stream
rtsp://admin:SIFRE@192.168.1.101:554/Streaming/Channels/102
```

Görüntü gelmezse Docker'a geçmeden bu sorunu çöz.

**Adım 2: Native Python ile barkod testi**

```powershell
python -m venv venv
venv\Scripts\activate
pip install opencv-python pyzbar numpy
python scripts\test_camera.py "rtsp://admin:SIFRE@192.168.1.101:554/Streaming/Channels/102"
```

Elinde bir Code128 barkod alıp kameranın önünde gösterdiğinde konsola tespit düşmeli.

**Adım 3: Shopify bağlantı testi**

```powershell
pip install requests python-dotenv pyyaml
# .env'i doldur
python scripts\test_shopify.py "#1001"
```

Test order yarat, sipariş no'yu ver, Shopify admin'de Timeline'a test yorumunun düştüğünü gör.

**Adım 4: Tam sistem (Docker)**

```powershell
docker compose up --build -d
docker compose logs -f
```

Durdurma:

```powershell
docker compose down
```

### Otomatik Başlatma

Docker Desktop "Start with Windows" seçeneği aktif olduğunda + `docker-compose.yml` içinde `restart: unless-stopped` tanımlı olduğundan:

- PC açıldığında Docker Desktop otomatik başlar
- Container otomatik kalkar
- Çökse bile yeniden başlar

---

## 11. Yaygın Sorunlar ve Çözümleri

### "Stream açılamadı"

1. VLC ile aynı URL'i aç, çalışıyor mu?
2. `ping <kamera_ip>` yanıt veriyor mu?
3. Kamera kullanıcısı RTSP yetkisi var mı?
4. Şifrede `@`, `:`, `/` gibi karakterler var mı? Varsa URL-encode et
5. Substream çalışmıyorsa main stream (`/101`) dene

### "Barkod okunmuyor"

- Etiket çok küçük mü? (ana stream'e geç veya FPS artır)
- Etiket eğik/bulanık mı? Sabit duracak şekilde göstermesi öğretilebilir
- Işık yetersiz mi? Hikvision'un dual light'ı devrede mi?
- pyzbar yetersizse → YOLO ROI tespit fazına geçilir

### "Barkod okunuyor, Shopify'a yazılmıyor"

```powershell
docker compose logs --tail=100 packing-detector

docker compose exec packing-detector sqlite3 /app/data/events.db `
  "SELECT order_no, shopify_status, shopify_error FROM events ORDER BY id DESC LIMIT 20;"
```

- `not_found` → Shopify'da o sipariş yok (regex yanlış olabilir, gerçekten yok olabilir)
- `failed` → API hatası, error mesajına bak
- `pending` çok birikiyor → ShopifyWorker çalışmıyor olabilir, restart et

### Yüksek CPU kullanımı

- `target_fps`'i 3'ten 2'ye düşür
- Substream kullandığından emin ol (`Channels/102`)
- Kapalı kameraları `enabled: false` yap

### Çok fazla false-positive

- `dedup_window_seconds`'ı artır (30 → 60)
- `order_no_regex`'i daralt (örn min 4 hane)
- Kameranın gördüğü alanda başka barkodlar var mı? (ürün barkodları paketleme barkoduyla karışabilir)

---

## 12. Geliştirme Yol Haritası

### Hafta 1: Keşif ve POC

- [ ] VLC ile RTSP doğrulama
- [ ] `test_camera.py` ile barkod tespit testi
- [ ] Shopify dev store kurulumu, custom app, token
- [ ] `test_shopify.py` ile end-to-end test
- [ ] Tek kamera + tek sipariş ile çalışan POC

### Hafta 2: Çoklu Kamera + Stabilite

- [ ] 8 kameraya yayma
- [ ] Reconnect mantığı test (kamera fişten çek, yeniden tak)
- [ ] Dedup test (aynı barkodu üst üste göster)
- [ ] SQLite'a tüm tespit kayıtları
- [ ] Snapshot doğrulaması

### Hafta 3: Production İhtiyaçları

- [ ] Dockerize + docker-compose
- [ ] Otomatik başlatma (Windows servis veya Docker auto-start)
- [ ] Snapshot retention (90 gün sonra otomatik temizlik)
- [ ] Shopify retry queue testi (internet kes, geri aç)
- [ ] Log rotation (RotatingFileHandler)
- [ ] UPS bağlantısı + yapılandırması

### Hafta 4: Saha Testi

- [ ] Depoda gerçek paketleme ile 3 gün test
- [ ] False-positive ayarlama
- [ ] Paketleyicilere barkod gösterme şekli eğitimi
- [ ] Müşteri hizmetleri ekibine sistem tanıtımı

### Hafta 5+: İyileştirme

- [ ] NVR ISAPI ile playback URL üretimi
- [ ] Shopify yorumuna direkt video link'i ekleme
- [ ] Admin web paneli (sipariş ara, snapshot gör, playback aç)
- [ ] Healthcheck/monitoring endpoint
- [ ] Eğer pyzbar yetersizse YOLO entegrasyonu

---

## 13. Maliyet Analizi

### Donanım Maliyeti

- ✅ **0 TL ek donanım** — Mevcut altyapı kullanılıyor
  - Kameralar: zaten kurulu
  - NVR: zaten kurulu
  - PC: Dell Pro Max T2 mevcut

### Yazılım Maliyeti

- ✅ **0 TL lisans** — Tüm bileşenler açık kaynak:
  - Python, OpenCV, pyzbar, SQLite, Docker — hepsi ücretsiz
  - Shopify API: mevcut Shopify aboneliğinde dahil
- Windows 11 Pro lisansı: mevcut (PC ile geliyor)

### Geliştirme Maliyeti

- In-house geliştirme (Tuncay) — Tahmini 4-5 hafta

### İşletim Maliyeti

- Elektrik: PC sürekli açık, ~150W × 24h × 30 gün ≈ 108 kWh/ay
- 2026 Mayıs ticari elektrik tarifesi ile aylık ~250-400 TL
- Bakım: minimum (Docker restart, ara sıra log kontrol)

### ROI Hesabı

**Mevcut kayıp:** Her şikayette ~30-60 dakika video tarama × ayda ~50 şikayet = 25-50 saat/ay
**Sonrası:** Her şikayette ~1-2 dakika (Shopify'da yorum oku, NVR'a git)
**Tasarruf:** ~24-48 saat/ay = ayda 1 personel-haftası
**Geri ödeme süresi:** Sistem ilk ay yatırımını çıkarır.

---

## 14. Gelecek Özellikler

Donanım kapasitesi (özellikle A1000 GPU) yüksek olduğundan ileride şu özellikler eklenebilir:

### Kısa Vadeli (1-3 ay)

**NVR ISAPI Entegrasyonu**
- Shopify yorumunda direkt tıklanabilir kayıt link'i
- Müşteri hizmetleri tek tıkla o ana atlar
- ISAPI: `/ISAPI/ContentMgmt/search` + `/ISAPI/streaming/tracks`

**Admin Panel (Web UI)**
- Sipariş no ile arama
- Snapshot önizleme
- Tüm event'lerin tablo görünümü
- Manuel "Shopify'a tekrar yaz" butonu (not_found olanlar için)
- React/Next.js veya HTMX + FastAPI

### Orta Vadeli (3-6 ay)

**YOLO ROI Tespit**
- A1000 GPU üzerinde YOLOv8n çalıştır
- Önce barkod konumunu bul (eğik, bulanık olsa bile)
- Bulunan bölgeyi kırp, pyzbar'a ver
- False-negative azalır

**OCR Fallback**
- Barkod okunamadığında etiket altındaki rakamı OCR ile oku
- PaddleOCR (GPU destekli, ücretsiz)

**Ürün Sayma**
- Kutuya konan ürünlerin barkodu okutuluyorsa, sipariştekiyle eşleştir
- Eksik/fazla ürün anlık uyarı
- "Eksik ürün geldi" şikayetinde en güçlü kanıt

### Uzun Vadeli (6+ ay)

**Operasyonel Metrikler**
- Paketleme süresi (sipariş bulunma → kutuya yerleştirilme)
- Masa bazında verimlilik raporu
- Yoğun saat analizi
- Boş masa / mola tespiti

**Anomali Tespiti**
- Belirli bir sipariş "paketlendi" ama Shopify'da "shipped" işaretlenmemişse uyarı
- Aynı sipariş 2 farklı masada okunduysa uyarı
- Çalışma saati dışı tespit alarmı

**Multi-Site**
- Birden fazla depo olursa, her depo kendi lokal PC'sinde çalışır
- Merkezi raporlama paneli (cloud) — opsiyonel

---

## Ekler

### Ek A: RTSP URL Referansı

```
Hikvision Format:
rtsp://<user>:<pass>@<ip>:<port>/Streaming/Channels/<channel><stream>

<channel>: Kamera numarası (1'den başlar)
<stream>:  1=main, 2=sub

Örnekler:
- Tek kameradan main: rtsp://admin:Pass@192.168.1.101:554/Streaming/Channels/101
- Tek kameradan sub:  rtsp://admin:Pass@192.168.1.101:554/Streaming/Channels/102
- NVR'dan 3. kanal:   rtsp://admin:Pass@192.168.1.50:554/Streaming/Channels/301
```

### Ek B: Shopify API Token Alma

1. Shopify admin → **Settings**
2. **Apps and sales channels** → **Develop apps**
3. **Create an app** → bir isim ver (örn: "Packing Detector")
4. **Configure Admin API scopes**:
   - `read_orders`, `write_orders`
   - `read_order_edits`, `write_order_edits`
5. **Install app**
6. **Admin API access token**'ı kopyala — **sadece bir kez gösterilir!**
7. `.env` dosyasına yaz

### Ek C: Test Code128 Barkodu Üretme

POC testi için online ücretsiz araçlar:
- https://barcode.tec-it.com/ → Code128 seç → "1001" yaz → indir, yazdır
- Veya Python ile: `pip install python-barcode` → script ile üret

Test için 5-10 farklı sipariş no barkodu yazdırılıp paketleyicilere verilebilir.

---

## Sonuç

Bu sistem, mevcut donanım altyapısı (Hikvision kameralar + NVR + Dell PC) üzerine sıfır ek donanım maliyeti ile inşa edilebilir. Açık kaynak yazılımlar kullanılarak Shopify entegrasyonu sağlanır.

**Kritik başarı faktörleri:**

1. Etiketlerin Code128 barkod taşıması (paketleme süreci güncellemesi gerekli)
2. Kamera açısının etiketi net göstermesi
3. Aydınlatma yeterliliği
4. Paketleyicilerin barkodu birkaç saniye sabit göstermesi
5. PC ve kameraların ağ stabilitesi
6. Shopify API token'ının düzgün scope'larla alınması

**Bu sistemin sağlayacağı değer:**

- Müşteri şikayetlerinde saatlerce video arama yerine saniyelerle çözüm
- Paketleme delili kanıt amaçlı saklanır (snapshot)
- Gelecek operasyonel iyileştirmeler için sağlam altyapı
- Mevcut Shopify iş akışına minimum müdahale (yorum eklenir, başka şey değişmez)

---

**Doküman versiyonu:** 1.0
**Son güncelleme:** Mayıs 2026
**Hazırlayan:** Tuncay (AI yardımıyla)
