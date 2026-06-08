# Changelog

Bu projedeki tüm önemli değişiklikler bu dosyada tutulur.
Format [Keep a Changelog](https://keepachangelog.com/) temellidir ve proje
[Semantic Versioning](https://semver.org/) kullanır.

## [Unreleased]

### Eklendi
- `DEPLOYMENT.md` — deploy süreci, kritik durumlar/riskler, bakım & rollback,
  sürüm öncesi kontrol listesi
- CLAUDE.md'ye **dokümantasyon disiplini** kuralı: her geliştirme/fix ilgili
  `.md` dosyalarını da güncellemeli

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
