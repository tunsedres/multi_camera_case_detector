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

from app.detection.barcode import BarcodeDetector, BarcodeResult
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
        order_regex: str = r"^#?\d{3,8}$",
        add_hash_prefix: bool = True,
        symbols: list[str] | None = None,
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
        self.detector = BarcodeDetector(order_regex, add_hash_prefix, symbols)

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

                results = self.detector.detect(frame)
                if results:
                    ts = datetime.now()
                    for result in results:
                        if self.health:
                            self.health.record_detection(self.camera_id, ts)
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
