"""
Tespit anındaki frame'i diske kaydeder.
Sonradan müşteri şikayetinde kanıt olarak kullanılır.
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


class SnapshotStore:
    """Klasör yapısı: snapshots/YYYY-MM-DD/camN_HH-MM-SS_orderno.jpg"""

    def __init__(self, base_dir: str, enabled: bool = True):
        self.base_dir = Path(base_dir)
        self.enabled = enabled
        if enabled:
            self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        frame: np.ndarray,
        camera_id: int,
        order_no: str,
        timestamp: datetime,
    ) -> Optional[str]:
        """Frame'i JPEG olarak kaydet, dosya yolunu döner."""
        if not self.enabled:
            return None

        # Klasör: tarih bazlı
        day_dir = self.base_dir / timestamp.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        # Dosya adı (order_no'daki # ve özel karakterleri temizle)
        safe_order = order_no.replace("#", "").replace("/", "_")
        time_str = timestamp.strftime("%H-%M-%S")
        filename = f"cam{camera_id}_{time_str}_{safe_order}.jpg"
        filepath = day_dir / filename

        # JPEG kalitesini düşür (85), boyutu küçük tut
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        return str(filepath)

    def cleanup_old(self, retention_days: int):
        """retention_days'den eski snapshot klasörlerini siler."""
        if retention_days <= 0 or not self.enabled:
            return

        import shutil
        from datetime import timedelta

        cutoff_date = datetime.now().date() - timedelta(days=retention_days)

        for day_dir in self.base_dir.iterdir():
            if not day_dir.is_dir():
                continue
            try:
                dir_date = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
                if dir_date < cutoff_date:
                    shutil.rmtree(day_dir)
            except ValueError:
                continue  # tarih formatına uymayan klasör, atla
