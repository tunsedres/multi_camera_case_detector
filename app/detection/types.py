"""
Tespit sonucu ortak tipi.

Hem barkod (pyzbar) hem OCR (tesseract) detector'ları aynı sonuç tipini döner →
camera_worker → on_detection → DB → Shopify zinciri yöntemden bağımsız çalışır.
Ayrı modülde ki OCR, pyzbar'a (barcode.py) dolaylı bağımlı olmasın.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BarcodeResult:
    raw_value: str  # Okunan ham değer (barkod verisi ya da OCR metni)
    normalized: str  # Shopify'a yazılacak hali (örn: #939141)
    symbol_type: str  # CODE128, QRCODE, OCR vb.
    polygon: list = field(default_factory=list)  # Konum (debug/çizim; OCR'da boş)
