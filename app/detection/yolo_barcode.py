"""
YOLO + pyzbar barkod tespiti.

Sorun: barkod kamerada küçük/uzak kalınca pyzbar tüm kareyi tarayıp çözemez.
Çözüm: YOLO barkod BÖLGESİNİ bulur → kırp → büyüt → pyzbar o net/büyük bölgeyi
okur. YOLO yer bulur (olasılıksal ama hata uydurmaz), pyzbar deterministik okur.

Model: Piero2411/YOLOV8s-Barcode-Detection (models/barcode_yolov8s.pt, image'a gömülü).
ultralytics/torch ağır olduğu için tembel import edilir (web/test katmanı torch'suz
yüklenir). CPU'da çalışır; GPU varsa ultralytics otomatik kullanır.

Çıktı BarcodeResult (barcode.py ile aynı) → camera_worker zinciri değişmez.
"""

from __future__ import annotations

import logging
import re

import cv2
import numpy as np

from app.detection.types import BarcodeResult

logger = logging.getLogger("packing.yolo")

DEFAULT_MODEL_PATH = "models/barcode_yolov8s.pt"


class YoloBarcodeDetector:
    """YOLO ile barkod bölgesi bul → kırp/büyüt → pyzbar ile çöz."""

    def __init__(
        self,
        order_regex: str = r"^\d{6,20}$",
        add_hash_prefix: bool = False,
        symbols: list[str] | None = None,
        model_path: str = DEFAULT_MODEL_PATH,
        conf: float = 0.35,
        upscale: float = 3.0,
        pad: int = 12,
    ):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        self.conf = conf
        self.upscale = upscale
        self.pad = pad
        self.model_path = model_path
        self._model = None  # tembel yüklenir (torch ağır)
        self._zbar_symbols = self._resolve_symbols(symbols)

    @staticmethod
    def _resolve_symbols(symbols: list[str] | None):
        """Config sembol isimlerini ZBarSymbol'a çevir (pyzbar tembel import)."""
        if not symbols:
            return None
        from pyzbar.pyzbar import ZBarSymbol

        mapping = {
            "EAN13": ZBarSymbol.EAN13,
            "EAN8": ZBarSymbol.EAN8,
            "CODE128": ZBarSymbol.CODE128,
            "CODE39": ZBarSymbol.CODE39,
            "CODE93": ZBarSymbol.CODE93,
            "QRCODE": ZBarSymbol.QRCODE,
            "UPCA": ZBarSymbol.UPCA,
            "UPCE": ZBarSymbol.UPCE,
            "ITF": ZBarSymbol.I25,
        }
        resolved = [mapping[s] for s in symbols if s in mapping]
        return resolved or None

    def _load_model(self):
        if self._model is None:
            from ultralytics import YOLO

            logger.info("YOLO barkod modeli yükleniyor: %s", self.model_path)
            self._model = YOLO(self.model_path)
        return self._model

    def detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """Frame'de barkod bölgelerini bulup içlerindeki kodu çözer."""
        from pyzbar import pyzbar

        model = self._load_model()
        # verbose=False: ultralytics her çıkarımda log basmasın
        preds = model.predict(frame, conf=self.conf, verbose=False)
        if not preds:
            return []

        h, w = frame.shape[:2]
        results: list[BarcodeResult] = []
        seen: set[str] = set()

        for box in self._boxes(preds[0]):
            x1, y1, x2, y2 = self._pad_box(box, w, h)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            big = cv2.resize(
                gray, None, fx=self.upscale, fy=self.upscale, interpolation=cv2.INTER_CUBIC
            )
            for d in pyzbar.decode(big, symbols=self._zbar_symbols):
                try:
                    raw = d.data.decode("utf-8").strip()
                except UnicodeDecodeError:
                    continue
                if not self.pattern.match(raw):
                    continue
                norm = self._normalize(raw)
                if norm in seen:
                    continue
                seen.add(norm)
                results.append(
                    BarcodeResult(
                        raw_value=raw,
                        normalized=norm,
                        symbol_type=f"YOLO+{d.type}",
                        polygon=[(x1, y1), (x2, y2)],
                    )
                )
        return results

    @staticmethod
    def _boxes(result):
        """YOLO sonucundan (x1,y1,x2,y2) kutularını çıkar."""
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        out = []
        for xyxy in boxes.xyxy.tolist():
            out.append([int(v) for v in xyxy])
        return out

    def _pad_box(self, box: list[int], w: int, h: int) -> tuple[int, int, int, int]:
        """Kutuyu biraz genişlet (barkod kenarları kırpılmasın) ve sınırlara kelepçele."""
        x1, y1, x2, y2 = box
        x1 = max(x1 - self.pad, 0)
        y1 = max(y1 - self.pad, 0)
        x2 = min(x2 + self.pad, w)
        y2 = min(y2 + self.pad, h)
        return x1, y1, x2, y2

    def _normalize(self, raw: str) -> str:
        if self.add_hash_prefix and not raw.startswith("#"):
            return f"#{raw}"
        return raw
