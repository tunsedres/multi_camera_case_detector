"""
Bir kamera için RTSP stream okuyup barkod tespiti yapan worker.

- RTSP TCP transport (UDP'ye göre paket kaybına dayanıklı)
- Buffer size 1 (lag birikimini önler)
- Otomatik reconnect
- FPS throttle (hedef FPS'e göre frame işle)
- HealthRegistry'ye durum raporlar (bağlantı, frame, tespit, reconnect)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime

import cv2
import numpy as np

from app.detection.types import BarcodeResult
from app.monitoring.health import HealthRegistry

# OpenCV FFmpeg backend için TCP transport — cv2 ilk kullanılmadan set edilmeli
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
)

logger = logging.getLogger("packing.worker")

DetectionCallback = Callable[[int, str, BarcodeResult, np.ndarray, datetime], None]


class CameraWorker(threading.Thread):
    """Her kamera için 1 thread. Sonsuz döngüde RTSP okur, barkod arar."""

    def __init__(
        self,
        camera_id: int,
        camera_name: str,
        rtsp_url: str,
        on_detection: DetectionCallback,
        target_fps: int = 3,
        order_regex: str = r"^#?\d{6,10}$",
        add_hash_prefix: bool = True,
        symbols: list[str] | None = None,
        mode: str = "ocr",
        ocr_min_confidence: float = 60.0,
        yolo_model_path: str = "models/barcode_yolov8s.pt",
        yolo_conf: float = 0.35,
        paddle_model_root: str = "models/paddleocr/whl",
        paddle_min_confidence: float = 0.80,
        min_votes: int = 3,
        vote_window_seconds: float = 4.0,
        dedup_window_seconds: float = 30.0,
        health: HealthRegistry | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(name=f"CamWorker-{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.on_detection = on_detection
        self.frame_interval = 1.0 / max(target_fps, 1)
        self.health = health
        self.stop_event = stop_event or threading.Event()
        self.mode = mode
        # mode'a göre tespit zinciri. Tembel import: her kurulum yalnızca kendi
        # ağır bağımlılığını (pyzbar / tesseract / torch) yükler.
        self._barcode = None
        self._ocr = None
        self._yolo = None
        self._paddle = None
        if mode in ("barcode", "both"):
            from app.detection.barcode import BarcodeDetector

            self._barcode = BarcodeDetector(order_regex, add_hash_prefix, symbols)
        if mode in ("ocr", "both"):
            from app.detection.ocr import OCRDetector

            self._ocr = OCRDetector(order_regex, add_hash_prefix, min_confidence=ocr_min_confidence)
        if mode == "paddle":
            from app.detection.paddle_ocr import PaddleOCRDetector

            self._paddle = PaddleOCRDetector(
                order_regex=order_regex,
                add_hash_prefix=add_hash_prefix,
                min_confidence=paddle_min_confidence,
                model_root=paddle_model_root,
            )
        if mode == "yolo":
            from app.detection.yolo_barcode import YoloBarcodeDetector

            self._yolo = YoloBarcodeDetector(
                order_regex=order_regex,
                add_hash_prefix=add_hash_prefix,
                symbols=symbols,
                model_path=yolo_model_path,
                conf=yolo_conf,
            )

        # Çoklu-kare oylama: yanlış okumaları eler. Cooldown'ı dedup penceresine
        # hizala ki onaylanan bir numara aynı süre boyunca tekrar tetiklenmesin.
        from app.detection.voting import DetectionVoter

        self._voter = DetectionVoter(
            min_votes=min_votes,
            window_seconds=vote_window_seconds,
            cooldown_seconds=max(dedup_window_seconds, vote_window_seconds),
        )

    def _detect(self, frame: np.ndarray) -> list[BarcodeResult]:
        """mode'a göre tespit. paddle/yolo tek başına; 'both'ta barkod→OCR fallback."""
        if self._paddle is not None:
            return self._paddle.detect(frame)
        if self._yolo is not None:
            return self._yolo.detect(frame)
        if self._barcode is not None:
            results = self._barcode.detect(frame)
            if results or self._ocr is None:
                return results
        if self._ocr is not None:
            return self._ocr.detect(frame)
        return []

    def run(self):
        logger.info("[Cam %s] %s başlıyor...", self.camera_id, self.camera_name)
        while not self.stop_event.is_set():
            try:
                self._stream_loop()
            except Exception as e:  # noqa: BLE001
                logger.exception("[Cam %s] Beklenmeyen hata: %s", self.camera_id, e)
                self._disconnected(str(e))
                self._sleep(5)
        logger.info("[Cam %s] Durduruluyor.", self.camera_id)

    def _stream_loop(self):
        safe_url = self._mask_url(self.rtsp_url)
        logger.info("[Cam %s] Bağlanılıyor: %s", self.camera_id, safe_url)

        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # geç frame'leri biriktirme

        if not cap.isOpened():
            logger.warning("[Cam %s] Stream açılamadı, 5sn sonra retry", self.camera_id)
            self._disconnected("Stream açılamadı")
            self._sleep(5)
            return

        logger.info("[Cam %s] ✓ Bağlandı", self.camera_id)
        if self.health:
            self.health.camera_connected(self.camera_id)
        last_process = 0.0
        consecutive_failures = 0

        try:
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 30:
                        logger.warning(
                            "[Cam %s] 30 ardışık okuma hatası, reconnect", self.camera_id
                        )
                        self._disconnected("Ardışık frame okuma hatası")
                        if self.health:
                            self.health.record_reconnect(self.camera_id)
                        return
                    time.sleep(0.1)
                    continue

                consecutive_failures = 0

                now = time.time()
                if now - last_process < self.frame_interval:
                    continue
                last_process = now

                if self.health:
                    self.health.record_frame(self.camera_id)

                for result in self._detect(frame):
                    # Oylama: bu okuma eşiği geçmediyse henüz tetikleme
                    # (tek-tük yanlış okumalar burada elenir).
                    if self._voter.record(result.normalized) is None:
                        continue
                    ts = datetime.now()
                    if self.health:
                        self.health.record_detection(self.camera_id, ts)
                    logger.info(
                        "[Cam %s] Onaylandı (oylama): %s", self.camera_id, result.normalized
                    )
                    try:
                        self.on_detection(
                            self.camera_id, self.camera_name, result, frame.copy(), ts
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.exception("[Cam %s] Callback hatası: %s", self.camera_id, e)
        finally:
            cap.release()
            self._disconnected(None)

    def _disconnected(self, error: str | None):
        if self.health:
            self.health.camera_disconnected(self.camera_id, error)

    def _sleep(self, seconds: float):
        self.stop_event.wait(timeout=seconds)

    @staticmethod
    def _mask_url(url: str) -> str:
        """RTSP URL'indeki şifreyi maskele (log güvenliği)."""
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)
