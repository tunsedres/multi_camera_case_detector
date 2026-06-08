"""
OCR tabanlı sipariş-no tespiti (Tesseract).

Barkod yerine etiketteki insan-okur sipariş numarasını (#939141 gibi) okur.
Neden: bazı etiketlerde barkod sipariş no'yu DEĞİL başka bir değeri (ürün/EAN)
kodluyor; oysa büyük matbu "#numara" doğru ve doğrudan okunabiliyor.

Çıktı barkod ile aynı arayüzü (BarcodeResult) kullanır → camera_worker →
on_detection → DB → Shopify zinciri değişmeden çalışır (symbol_type="OCR").

Görüntü ön-işleme (gri + kontrast + threshold + upscale) Tesseract'ın matbu
rakamlardaki doğruluğunu belirgin artırır; kamera odağı yine de kritik.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract

from app.detection.types import BarcodeResult

logger = logging.getLogger("packing.ocr")


@dataclass
class _Candidate:
    text: str
    confidence: float


class OCRDetector:
    """
    Frame içinde sipariş-no formatına ('#' + rakam) uyan metni Tesseract ile bulur.

    Tesseract 'image_to_data' ile kelime + güven (confidence) döner; regex'e uyan
    ve güveni eşiği aşan adaylar BarcodeResult olarak verilir.
    """

    def __init__(
        self,
        order_regex: str = r"^#?\d{6,10}$",
        add_hash_prefix: bool = True,
        min_confidence: float = 60.0,
        # Sadece rakam + '#' tara → Tesseract'ı yanlış karakterlerden uzak tut.
        tesseract_config: str = "--psm 11 -c tessedit_char_whitelist=#0123456789",
    ):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        self.min_confidence = min_confidence
        self.tesseract_config = tesseract_config

    # ------------------------------------------------------------------ #
    @staticmethod
    def _preprocess(frame: np.ndarray) -> np.ndarray:
        """Gri + CLAHE kontrast + Otsu threshold + 2x upscale (OCR doğruluğu için)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Küçük/uzak rakamlar için ölçek büyüt — Tesseract büyük metni daha iyi okur.
        return cv2.resize(thresh, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    def detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """Frame'de sipariş-no formatına uyan metinleri döner (en güvenli ilk)."""
        proc = self._preprocess(frame)
        try:
            data = pytesseract.image_to_data(
                proc, config=self.tesseract_config, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractError as e:
            logger.warning("Tesseract hatası: %s", e)
            return []

        candidates: list[_Candidate] = []
        for text, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
            token = (text or "").strip()
            if not token:
                continue
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                continue
            if confidence < self.min_confidence:
                continue
            if self.pattern.match(token):
                candidates.append(_Candidate(text=token, confidence=confidence))

        # Aynı değeri tekrar üretme; en güvenliyi başa al.
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        seen: set[str] = set()
        results: list[BarcodeResult] = []
        for c in candidates:
            norm = self._normalize(c.text)
            if norm in seen:
                continue
            seen.add(norm)
            results.append(
                BarcodeResult(
                    raw_value=c.text,
                    normalized=norm,
                    symbol_type="OCR",
                    polygon=[],
                )
            )
        return results

    def _normalize(self, raw: str) -> str:
        """'939141' → '#939141' (Shopify '#...' arar)."""
        if self.add_hash_prefix and not raw.startswith("#"):
            return f"#{raw}"
        return raw
