"""
Barkod tespit modülü.

pyzbar Code128 dahil yaygın formatları destekler. Sipariş no formatına (regex)
uyan barkodlar döner; ürün barkodları gibi eşleşmeyenler elenir.

İleride pyzbar yetersiz kalırsa (eğik/bulanık etiket) bu modülün arkasına YOLO ROI
tespiti eklenebilir: önce barkod konumu bulunur, kırpılır, sonra pyzbar'a verilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np
from pyzbar import pyzbar
from pyzbar.pyzbar import ZBarSymbol

# config'deki string isimleri ZBarSymbol'a eşle
_SYMBOL_MAP = {
    "CODE128": ZBarSymbol.CODE128,
    "QRCODE": ZBarSymbol.QRCODE,
    "EAN13": ZBarSymbol.EAN13,
    "EAN8": ZBarSymbol.EAN8,
    "CODE39": ZBarSymbol.CODE39,
    "CODE93": ZBarSymbol.CODE93,
    "UPCA": ZBarSymbol.UPCA,
    "UPCE": ZBarSymbol.UPCE,
    "ITF": ZBarSymbol.I25,
}


@dataclass
class BarcodeResult:
    raw_value: str  # Barkoddan okunan ham değer
    normalized: str  # Shopify'a yazılacak hali (örn: #1234)
    symbol_type: str  # CODE128, QRCODE vb.
    polygon: list  # Barkod konumu (debug/çizim için)


class BarcodeDetector:
    def __init__(
        self,
        order_regex: str = r"^#?\d{3,8}$",
        add_hash_prefix: bool = True,
        symbols: list[str] | None = None,
    ):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        self.symbols = self._resolve_symbols(symbols)

    @staticmethod
    def _resolve_symbols(symbols: list[str] | None) -> list[ZBarSymbol] | None:
        """Config'deki isimleri ZBarSymbol'a çevir. Boş/None ise hepsi taranır."""
        if not symbols:
            return None
        resolved = [_SYMBOL_MAP[s] for s in symbols if s in _SYMBOL_MAP]
        return resolved or None

    def detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """Frame içinde sipariş no formatına uyan barkodları bulur."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        decoded = pyzbar.decode(gray, symbols=self.symbols)

        results: list[BarcodeResult] = []
        for d in decoded:
            try:
                raw = d.data.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if not self.pattern.match(raw):
                continue
            results.append(
                BarcodeResult(
                    raw_value=raw,
                    normalized=self._normalize(raw),
                    symbol_type=d.type,
                    polygon=[(p.x, p.y) for p in d.polygon],
                )
            )
        return results

    def _normalize(self, raw: str) -> str:
        """Etikette '1234' olabilir ama Shopify '#1234' arar — normalize et."""
        if self.add_hash_prefix and not raw.startswith("#"):
            return f"#{raw}"
        return raw
