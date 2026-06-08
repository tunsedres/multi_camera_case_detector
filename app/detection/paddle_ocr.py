"""
PaddleOCR tabanlı sipariş-no tespiti.

Neden Tesseract yerine: Tesseract bu kamera görüntüsünde rakam karıştırıyordu
(#939146 → #839146/#939148), yani YANLIŞ ama geçerli bir siparişe not yazma riski.
PaddleOCR (PP-OCRv4) aynı videoda 3 etiketi de sıfır yanlış-hane ile okudu.

İki aşama: metin BÖLGELERİNİ bulur (det) + okur (rec) → koca sahnede gürültüsüz.
Modeller image'a gömülü (models/paddleocr/whl), tamamen offline. paddleocr/paddle
ağır olduğu için tembel import edilir (web/test katmanı onsuz yüklenir).

Çıktı BarcodeResult (barcode.py ile aynı) → camera_worker zinciri değişmez.
CPU'da kare başı ~0.9 sn; etiket masada saniyeler kaldığı için target_fps=1 yeter.
"""

from __future__ import annotations

import logging
import re

import numpy as np

from app.detection.types import BarcodeResult

logger = logging.getLogger("packing.paddle")

# Image'a gömülü model dizinleri (offline). PaddleOCR varsayılan ~/.paddleocr
# yerine bunları kullanır → internet/indirme gerekmez.
DEFAULT_MODEL_ROOT = "models/paddleocr/whl"


class PaddleOCRDetector:
    def __init__(
        self,
        order_regex: str = r"^#?\d{6,10}$",
        add_hash_prefix: bool = True,
        min_confidence: float = 0.80,
        model_root: str = DEFAULT_MODEL_ROOT,
        lang: str = "en",
    ):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        self.min_confidence = min_confidence
        self.model_root = model_root
        self.lang = lang
        self._ocr = None  # tembel yüklenir (paddle ağır)

    def _engine(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            logger.info("PaddleOCR yükleniyor (offline modeller: %s)", self.model_root)
            self._ocr = PaddleOCR(
                use_angle_cls=False,
                lang=self.lang,
                show_log=False,
                # Gömülü model yolları → indirme yok (offline depo gereksinimi)
                det_model_dir=f"{self.model_root}/det/{self.lang}/en_PP-OCRv3_det_infer",
                rec_model_dir=f"{self.model_root}/rec/{self.lang}/en_PP-OCRv4_rec_infer",
                cls_model_dir=f"{self.model_root}/cls/ch_ppocr_mobile_v2.0_cls_infer",
            )
        return self._ocr

    def detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """Frame'de sipariş-no formatına uyan metinleri döner (en güvenli ilk)."""
        result = self._engine().ocr(frame, cls=False)
        if not result or not result[0]:
            return []

        candidates: list[tuple[float, str]] = []
        for line in result[0]:
            text, conf = line[1][0], float(line[1][1])
            token = text.replace(" ", "").strip()
            if conf < self.min_confidence:
                continue
            if self.pattern.match(token):
                candidates.append((conf, token))

        candidates.sort(reverse=True)  # en güvenli ilk
        seen: set[str] = set()
        results: list[BarcodeResult] = []
        for _conf, token in candidates:
            norm = self._normalize(token)
            if norm in seen:
                continue
            seen.add(norm)
            results.append(
                BarcodeResult(
                    raw_value=token,
                    normalized=norm,
                    symbol_type="PADDLE",
                    polygon=[],
                )
            )
        return results

    def _normalize(self, raw: str) -> str:
        if self.add_hash_prefix and not raw.startswith("#"):
            return f"#{raw}"
        return raw
