"""
Tespit anındaki frame'i diske kaydeder (müşteri şikayetinde kanıt).

Klasör yapısı:  snapshots/YYYY-MM-DD/camN_HH-MM-SS_orderno.jpg
Retention: cleanup_old() eski klasörleri siler (scheduler tarafından periyodik çağrılır).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # tip ipucu için; runtime'da cv2 tembel yüklenir
    import numpy as np

logger = logging.getLogger("packing.snapshots")


class SnapshotStore:
    def __init__(self, base_dir: str, enabled: bool = True, jpeg_quality: int = 85):
        self.base_dir = Path(base_dir)
        self.enabled = enabled
        self.jpeg_quality = jpeg_quality
        if enabled:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        frame: np.ndarray,
        camera_id: int,
        order_no: str,
        timestamp: datetime,
    ) -> str | None:
        """Frame'i JPEG olarak kaydet, dosya yolunu döner (kapalıysa None)."""
        if not self.enabled:
            return None

        import cv2  # tembel import: web/storage katmanı cv2'siz de yüklenebilsin

        day_dir = self.base_dir / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        safe_order = order_no.replace("#", "").replace("/", "_").replace("\\", "_")
        time_str = timestamp.strftime("%H-%M-%S")
        filename = f"cam{camera_id}_{time_str}_{safe_order}.jpg"
        filepath = day_dir / filename

        try:
            ok = cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        except cv2.error as e:  # pragma: no cover
            logger.warning("Snapshot yazılamadı (%s): %s", filepath, e)
            return None
        if not ok:
            logger.warning("Snapshot yazılamadı: %s", filepath)
            return None
        return str(filepath)

    def cleanup_old(self, retention_days: int) -> int:
        """retention_days'den eski tarih klasörlerini siler. Silinen klasör sayısını döner."""
        if retention_days <= 0 or not self.enabled or not self.base_dir.exists():
            return 0

        cutoff = datetime.now().date() - timedelta(days=retention_days)
        removed = 0
        for day_dir in self.base_dir.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
            except ValueError:
                continue  # tarih formatına uymayan klasör, atla
            if dir_date < cutoff:
                shutil.rmtree(day_dir, ignore_errors=True)
                removed += 1
        return removed
