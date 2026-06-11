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
import queue
import re
import threading
from contextlib import contextmanager

import numpy as np

from app.detection.types import BarcodeResult

logger = logging.getLogger("packing.paddle")

# Image'a gömülü model dizinleri (offline). PaddleOCR varsayılan ~/.paddleocr
# yerine bunları kullanır → internet/indirme gerekmez.
DEFAULT_MODEL_ROOT = "models/paddleocr/whl"


class PaddleEnginePool:
    """
    PAYLAŞILAN PaddleOCR motor havuzu (kamera başına 1 model YERİNE havuzda N model).

    Neden: her CameraWorker kendi PaddleOCR'ını kurarsa 8 kamera = 8 model kopyası
    → 16 GB RAM dolup swap'e düşer (üretimde yaşandı). Tek havuz N motor tutar:
      - RAM: N× model (8× değil),
      - eşzamanlılık: aynı anda N OCR (PaddleOCR thread-safe DEĞİL; her motor tek
        thread'e ödünç verilir),
      - throughput: N motor sırayla kuyruktan ödünç alınır.
    Motorlar tembel kurulur (ilk ihtiyaçta, size'a kadar) → paddle import'u yalnızca
    gerçekten kullanılınca olur (web/test katmanı onsuz yüklenir).
    """

    def __init__(
        self,
        size: int = 2,
        model_root: str = DEFAULT_MODEL_ROOT,
        lang: str = "en",
    ):
        self.size = max(int(size), 1)
        self.model_root = model_root
        self.lang = lang
        self._idle: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._created = 0

    def _make_engine(self):
        from paddleocr import PaddleOCR

        logger.info(
            "PaddleOCR motoru kuruluyor (%s/%s, offline: %s)",
            self._created + 1,
            self.size,
            self.model_root,
        )
        return PaddleOCR(
            use_angle_cls=False,
            lang=self.lang,
            show_log=False,
            det_model_dir=f"{self.model_root}/det/{self.lang}/en_PP-OCRv3_det_infer",
            rec_model_dir=f"{self.model_root}/rec/{self.lang}/en_PP-OCRv4_rec_infer",
            cls_model_dir=f"{self.model_root}/cls/ch_ppocr_mobile_v2.0_cls_infer",
        )

    def _acquire(self):
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.size:
                    self._created += 1
                    return self._make_engine()
        # Havuz dolu → bir motor boşalana kadar bekle (eşzamanlılığı size ile sınırla).
        return self._idle.get()

    @contextmanager
    def borrow(self):
        engine = self._acquire()
        try:
            yield engine
        finally:
            self._idle.put(engine)

    def run_ocr(self, frame: np.ndarray):
        """Havuzdan bir motor ödünç alıp .ocr() çalıştırır, ham çıktıyı döner."""
        with self.borrow() as engine:
            return engine.ocr(frame, cls=False)


class PaddleOCRDetector:
    def __init__(
        self,
        order_regex: str = r"^#?\d{6,10}$",
        add_hash_prefix: bool = True,
        min_confidence: float = 0.80,
        model_root: str = DEFAULT_MODEL_ROOT,
        lang: str = "en",
        engine_pool: PaddleEnginePool | None = None,
    ):
        self.pattern = re.compile(order_regex)
        self.add_hash_prefix = add_hash_prefix
        self.min_confidence = min_confidence
        self.model_root = model_root
        self.lang = lang
        # Paylaşılan motor havuzu (önerilen — çok kameralı). Verilmezse tek motorlu
        # özel havuz (geriye uyumlu; tek-kamera/test). Filtre mantığı stateless.
        self._pool = engine_pool
        self._ocr = None  # tek-motor yolu (engine_pool yoksa tembel yüklenir)

    def _engine(self):
        if self._ocr is None:
            self._ocr = PaddleEnginePool(
                size=1, model_root=self.model_root, lang=self.lang
            )._make_engine()
        return self._ocr

    def _run_ocr(self, frame: np.ndarray):
        if self._pool is not None:
            return self._pool.run_ocr(frame)
        return self._engine().ocr(frame, cls=False)

    def detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """Frame'de sipariş-no formatına uyan metinleri döner (en güvenli ilk)."""
        result = self._run_ocr(frame)
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
