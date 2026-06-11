# 🚀 Deployment & Operasyon Rehberi — Packing Detector

Bu dosya **kuruluma çıkmadan önce ne yapmalıyız**, **deploy adımları** ve
**kritik durumlar/riskler** için tek referanstır. Her sürümde güncel tutulur.

> Kısa kurulum için [README.md](README.md), mimari için [CLAUDE.md](CLAUDE.md),
> değişiklikler için [CHANGELOG.md](CHANGELOG.md).

---

## 1. Ne yapmalıyız? (durum + sıradaki adımlar)

### Bu oturumda tamamlanan (✅ hazır)
- Çekirdek tespit + dedup + snapshot + SQLite kuyruğu
- Shopify **GraphQL** entegrasyonu (metafield; order note opsiyonel/varsayılan kapalı)
- Ed25519 **offline lisanslama** + vendor üretici script
- **Admin Web Panel** (dashboard, arama, snapshot, retry, `/health`)
- Health/monitoring + scheduler (retention temizliği)
- Tipli config doğrulama, pytest (50 test), GitHub Actions CI, Docker healthcheck

### İlk müşteriye çıkmadan ÖNCE yapılması gerekenler (sırayla)
1. **Gerçek lisans anahtar çifti üret** — `keys.py`'deki dev anahtarını değiştir:
   `python scripts/generate_license.py keygen` → `private_key.pem`'i güvenli yedekle.
2. **Shopify GraphQL'i gerçek dev store'da doğrula** — `scripts/test_shopify.py "#1001"`
   ile metafield (ve `write_to_order_note: true` ise note) gerçekten yazılıyor mu?
3. **Saha testi (3 gün)** — gerçek paketleme akışında false-positive ayarı,
   `dedup_window_seconds` / `order_no_regex` kalibrasyonu.
4. **Etiket süreci** — paketleme etiketleri Code128 barkod taşımalı; paketleyicilere
   barkodu 1–2 sn sabit gösterme eğitimi.
5. **Admin panel parolası** — `.env` `ADMIN_PASSWORD` set et, `LICENSE_ENFORCE=true` yap.

### Ürünleştirme yol haritası (sonraki sürümler)
- **Kısa**: NVR ISAPI playback link (Shopify yorumuna tıklanabilir kayıt), installer/tek-tık kurulum
- **Orta**: YOLO ROI fallback (eğik/bulanık barkod), OCR fallback, ürün sayma
- **Uzun**: çoklu-müşteri bulut yönetim/izleme paneli, operasyonel metrikler, anomali uyarıları

---

## 2. Deploy süreci (adım adım)

### 2.1 Ön hazırlık (donanım + ağ)
- [ ] Dell PC'ye **Docker Desktop for Windows** kur, "Start with Windows" aç
- [ ] PC'ye **statik IP** ver (örn. `192.168.1.50`)
- [ ] Kameralara statik IP, **RTSP yetkili ayrı kullanıcı** tanımla (admin DEĞİL)
- [ ] **Saat senkronizasyonu**: PC ve NVR aynı NTP kaynağı + aynı saat dilimi (bkz. §3.1)
- [ ] **UPS** (kesintisiz güç) bağla

### 2.2 Yazılım kurulumu
```bash
git clone <repo> packing-detector && cd packing-detector
cp .env.example .env            # Windows: copy
#  .env doldur:  Shopify token, kamera şifresi, ADMIN_PASSWORD, LICENSE_KEY
#  config/config.yaml:  kamera IP'leri + enabled

# Lisans (müşteri makinesine yalnızca ANAHTAR konur, private key DEĞİL):
#   .env LICENSE_KEY=...  ya da  config/license.key dosyası
```

### 2.3 Aşamalı doğrulama (atla­ma!)
1. **VLC** ile RTSP URL → görüntü var mı?
2. `python scripts/test_camera.py "<rtsp_url>"` → barkod konsola düşüyor mu?
3. `python scripts/test_shopify.py "#1001"` → Shopify Timeline'a test yorumu düştü mü?
4. `docker compose up --build -d` → `docker compose logs -f`
5. `http://localhost:8080` panel açılıyor, kamera "ok", `/health` 200.

### 2.4 Go-live
- [ ] Tek kamerayla başla (`enabled: true` sadece 1), doğrula, sonra 8'e çıkar
- [ ] `restart: unless-stopped` + Docker auto-start → PC açılınca otomatik kalkar
- [ ] Müşteri hizmetleri ekibine panel + akış tanıtımı

---

## 3. Kritik durumlar ve riskler

### 3.1 ⏰ Saat senkronizasyonu (EN KRİTİK)
Sistemin tüm değeri "Shopify'daki zamana göre NVR'da o ana git"e dayanır. **PC saati
ile NVR saati kayarsa**, Shopify'a yazılan zaman damgası NVR kaydıyla tutmaz → sistem
işe yaramaz. PC ve NVR **aynı NTP sunucusunu** kullanmalı, **aynı saat dilimi**
(`Europe/Istanbul`). Kurulumda ve periyodik olarak iki saati karşılaştır.

### 3.2 🔐 Sırlar ve lisans private key
- `.env`, `config/license.key`, `config/private_key.pem` **asla** git'e/imaja girmez
  (`.gitignore` + `.dockerignore` ile korunur — değiştirme).
- **`private_key.pem` YALNIZCA satıcıda kalır**, müşteri makinesine **gönderilmez**.
  Müşteriye sadece imzalı `LICENSE_KEY` verilir.
- Kameralar için admin değil, **RTSP-only kullanıcı** kullan. Şifrede özel karakter
  varsa RTSP URL'de URL-encode et.

### 3.3 🌐 İnternet kesintisi
Tespit ve snapshot **devam eder**; Shopify yazımı `pending` olarak SQLite'ta birikir,
internet gelince `ShopifyWorker` drenajı yapar. Uzun kesintilerde panel → Olaylar →
`pending` sayısı artar; bu normaldir, veri kaybı olmaz.

### 3.4 💾 Disk / retention
~5000 tespit/gün × ~200 KB ≈ **1 GB/gün** snapshot. `snapshot_retention_days: 90`
ile scheduler eski klasörleri otomatik siler. 1 TB SSD'de rahat; yine de diski izle.
SQLite WAL modunda — `*.db-wal/*.db-shm` dosyaları normaldir.

### 3.5 🔌 Güç kesintisi
Ani kapanma SQLite WAL ile büyük ölçüde güvenli, ama **UPS şart**. Kapanma sonrası
Docker auto-start + `restart: unless-stopped` ile sistem kendiliğinden kalkar.

### 3.6 🔒 Ağ güvenliği (Admin Panel)
- Panel `:8080` **yalnızca LAN**'da kalmalı; internete açma, router'da port-forward etme.
- `.env` `ADMIN_PASSWORD` **mutlaka** set et (boşsa panel korumasız).
- `/health` bilinçli olarak kimlik doğrulamasızdır (healthcheck/izleme için).

### 3.7 📉 Shopify API
- GraphQL maliyet-tabanlı rate limit; tek `ShopifyWorker` yönetir, otomatik backoff.
- **API sürümü deprecation**: Shopify her çeyrek sürüm düşürür. `.env`
  `SHOPIFY_API_VERSION`'ı yılda ~1 güncelle (örn. `2025-01` → `2025-10`).
- `not_found` çok çıkıyorsa: `order_no_regex` yanlış olabilir ya da sipariş gerçekten yok.

### 3.8 📷 Sessiz kamera arızası
Bir kamera frame üretmeyi durdurursa tespit sessizce durur. Panel dashboard kamerayı
`stale`/`down` gösterir; `/health` JSON ile dışarıdan da izlenebilir. Günlük kontrol et.

### 3.9 🎫 Lisans süresi
Panel dashboard "lisans kalan gün"ü gösterir. `LICENSE_ENFORCE=true` iken süre dolarsa
sistem başlamaz/çalışmaya devam edemez. **Süre dolmadan önce yeni anahtar üret/ilet.**

### 3.10 🧠 Çoklu kamera — RAM/CPU ölçeklenmesi
İki ayrı kaynak baskısı kamera sayısıyla artar:
- **RAM** — PaddleOCR modeli paylaşılan havuzdan gelir (`detection.paddle_pool_size`,
  varsayılan 2). RAM ≈ `pool_size`× model + kamera başına frame tamponu. Kamera başına
  ayrı model **kurulmaz** (eski davranış 8 kamerada 16 GB'ı doldurup swap thrash
  yapıyordu).
- **CPU** — asıl darboğaz **kamera başına video çözme**. **Ana akış** (`.../<ch>01`,
  tam çözünürlük) çok ağırdır; 8 kamerada substream (`.../<ch>02`) tercih edilmeli.
  Substream OCR'ı zorlarsa o istasyonu ana akışta bırak (panelde kamera bazında karış).

**İzle**: `docker stats packing-detector` (CPU%/MEM) + host `uptime` (yük < çekirdek
sayısı olmalı) + `free -h` (swap dolmamalı) + `/health` (kamera `stale`/`reconnect`).
Yük çekirdeği aşıyor ya da swap doluyorsa: substream'e geç, `paddle_pool_size`/kamera
sayısını azalt. **Yeni kurulumda kademeli aç** (2 → 4 → 8, her adımda ölç).

---

## 4. Bakım & operasyon

| İş | Komut / yer |
|----|-------------|
| Logları izle | `docker compose logs -f` (ayrıca `logs/app.log`, rotating) |
| Sağlık | `http://<host>:8080/health` · panel dashboard |
| DB sorgusu | panel → Olaylar (sqlite3 CLI gerekmez) |
| **Yedek (DB)** | `data/events.db` (+ `-wal`,`-shm`) tek dosya kopyala; düzenli al |
| Snapshot temizliği | scheduler otomatik (`snapshot_retention_days`) |
| Yeniden başlat | `docker compose restart` |

---

## 5. Güncelleme & rollback

```bash
git pull
docker compose up --build -d     # şema additive (CREATE IF NOT EXISTS), migration gerekmez
docker compose logs -f
```
- **Rollback**: önceki git tag/commit'e dön + `docker compose up --build -d`.
- DB şeması geriye uyumlu tutulmalı (kolon ekle, silme/yeniden adlandırma yapma).
- Büyük değişiklik öncesi `data/events.db` yedeği al.

---

## 6. Sürüm öncesi kontrol listesi (CI dışı, manuel)

- [ ] `ruff check .` ve `ruff format --check .` temiz
- [ ] `pytest` yeşil
- [ ] CHANGELOG güncel, VERSION artırıldı
- [ ] Yeni ayar varsa `.env.example` + `config.yaml` + ilgili `.md` güncel
- [ ] Lisans `keys.py` üretim anahtarı (dev anahtarı değil)
- [ ] `private_key.pem` imaja/git'e sızmıyor (`.dockerignore`/`.gitignore` doğrula)
