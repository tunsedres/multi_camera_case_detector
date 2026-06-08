"""
Barkod tespit modülü.
pyzbar Code128 dahil tüm yaygın formatları destekler.
"""
import re
from typing import List, Optional
from dataclasses import dataclass

import cv2
import numpy as np
from pyzbar import pyzbar
from pyzbar.pyzbar import ZBarSymbol


@dataclass
class BarcodeResult:
    """Tespit edilen bir barkodun sonucu."""
    raw_value: str       # Barkoddan okunan ham değer
    normalized: str      # Shopify'a yazılacak normalize edilmiş hali (örn: #1234)
    symbol_type: str     # CODE128, EAN13 vb.
    polygon: list        # Barkod konumu (debug için)


class BarcodeDetector:
    """Frame içinde barkod arar, sipariş no formatına uyanları döner."""

    def __init__(self, order_regex: str = r"^#?\d{3,8}$", add_hash_prefix: bool = True):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        # Sadece Code128 ve QR'a odaklanırsak biraz daha hızlı
        # İstersen kaldırıp tüm formatları taratabilirsin
        self.symbols = [ZBarSymbol.CODE128, ZBarSymbol.QRCODE]

    def detect(self, frame: np.ndarray) -> List[BarcodeResult]:
        """
        Frame içinde sipariş no formatına uyan barkodları bulur.
        Görüntü iyileştirme: grayscale + hafif blur azaltma.
        """
        # Performans için grayscale'e çevir (pyzbar zaten içeride yapar ama daha hızlı)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        decoded = pyzbar.decode(gray, symbols=self.symbols)

        results = []
        for d in decoded:
            try:
                raw = d.data.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue

            # Format filtresi - sipariş no'ya benzemiyorsa atla
            if not self.pattern.match(raw):
                continue

            normalized = self._normalize(raw)

            results.append(BarcodeResult(
                raw_value=raw,
                normalized=normalized,
                symbol_type=d.type,
                polygon=[(p.x, p.y) for p in d.polygon],
            ))

        return results

    def _normalize(self, raw: str) -> str:
        """
        Etikette '1234' yazıyor olabilir ama Shopify'da '#1234' aranır.
        Bu fonksiyon normalize eder.
        """
        if self.add_hash_prefix and not raw.startswith("#"):
            return f"#{raw}"
        return raw
