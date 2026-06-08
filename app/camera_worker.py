"""
Bir kamera için stream okuyup barkod tespiti yapan worker.
- RTSP TCP transport (UDP'ye göre daha stabil)
- Buffer size 1 (lag birikimini önler)
- Otomatik reconnect
- FPS throttle
"""
import os
import time
import logging
import threading
from datetime import datetime
from typing import Callable

import cv2
import numpy as np

from app.detection.barcode import BarcodeDetector, BarcodeResult


# OpenCV FFmpeg backend için TCP transport (UDP yerine - daha stabil)
# Bu env değişkeni cv2 import edilmeden önce set edilmeli
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
)


logger = logging.getLogger("packing.worker")


class CameraWorker(threading.Thread):
    """
    Her kamera için 1 thread. Sonsuz döngüde RTSP okur, barkod arar.
    Tespit olunca on_detection callback'i çağırır.
    """

    def __init__(
        self,
        camera_id: int,
        camera_name: str,
        rtsp_url: str,
        on_detection: Callable[[int, str, BarcodeResult, np.ndarray, datetime], None],
        target_fps: int = 3,
        order_regex: str = r"^#?\d{3,8}$",
        add_hash_prefix: bool = True,
        stop_event: threading.Event = None,
    ):
        super().__init__(name=f"CamWorker-{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.on_detection = on_detection
        self.frame_interval = 1.0 / max(target_fps, 1)
        self.stop_event = stop_event or threading.Event()
        self.detector = BarcodeDetector(order_regex, add_hash_prefix)

    def run(self):
        logger.info(f"[Cam {self.camera_id}] {self.camera_name} başlıyor...")
        while not self.stop_event.is_set():
            try:
                self._stream_loop()
            except Exception as e:
                logger.exception(f"[Cam {self.camera_id}] Beklenmeyen hata: {e}")
                self._sleep(5)

        logger.info(f"[Cam {self.camera_id}] Durduruluyor.")

    def _stream_loop(self):
        """RTSP stream'i aç, frame'leri işle, bağlantı koparsa exception fırlat."""
        # Şifreyi log'a basma! URL'i loglayacaksak maskeyelim
        safe_url = self._mask_url(self.rtsp_url)
        logger.info(f"[Cam {self.camera_id}] Bağlanılıyor: {safe_url}")

        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)

        # KRİTİK: Buffer'ı 1'e indir, geç frame'leri biriktirme
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            logger.warning(f"[Cam {self.camera_id}] Stream açılamadı, 5sn sonra retry")
            self._sleep(5)
            return

        logger.info(f"[Cam {self.camera_id}] ✓ Bağlandı")
        last_process_time = 0.0
        consecutive_failures = 0

        try:
            while not self.stop_event.is_set():
                ret, frame = cap.read()
                if not ret or frame is None:
                    consecutive_failures += 1
                    if consecutive_failures >= 30:
                        logger.warning(f"[Cam {self.camera_id}] 30 ardışık frame okuma hatası, reconnect")
                        return
                    time.sleep(0.1)
                    continue

                consecutive_failures = 0

                # FPS throttle - her frame'i değil, hedef FPS'e göre işle
                now = time.time()
                if now - last_process_time < self.frame_interval:
                    continue
                last_process_time = now

                # Barkod tespiti
                results = self.detector.detect(frame)

                if results:
                    timestamp = datetime.now()
                    for result in results:
                        try:
                            self.on_detection(
                                self.camera_id,
                                self.camera_name,
                                result,
                                frame.copy(),  # callback async ise frame değişebilir
                                timestamp,
                            )
                        except Exception as e:
                            logger.exception(f"[Cam {self.camera_id}] Callback hatası: {e}")
        finally:
            cap.release()

    def _sleep(self, seconds: float):
        """stop_event tetiklenirse erken uyan."""
        self.stop_event.wait(timeout=seconds)

    @staticmethod
    def _mask_url(url: str) -> str:
        """RTSP URL'indeki şifreyi maskele (log için güvenli)."""
        # rtsp://user:pass@host -> rtsp://user:***@host
        import re
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", url)
