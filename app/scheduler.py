"""
Bakım worker'ı — periyodik arka plan görevleri.

* Snapshot retention temizliği (doküman: 90 günden eski klasörler silinir).
  Önceki POC'ta cleanup_old() tanımlıydı ama HİÇ çağrılmıyordu — disk sonsuz
  büyüyordu. Bu worker o açığı kapatır.
* Lisans yeniden kontrolü (süre dolumu runtime'da yakalansın diye).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from app.storage.snapshots import SnapshotStore

logger = logging.getLogger("packing.scheduler")


class MaintenanceWorker(threading.Thread):
    def __init__(
        self,
        snapshots: SnapshotStore,
        retention_days: int,
        cleanup_interval_hours: float = 6.0,
        license_recheck_hours: float = 12.0,
        license_check: Callable[[], None] | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(name="MaintenanceWorker", daemon=True)
        self.snapshots = snapshots
        self.retention_days = retention_days
        self.cleanup_interval = cleanup_interval_hours * 3600
        self.license_interval = license_recheck_hours * 3600
        self.license_check = license_check
        self.stop_event = stop_event or threading.Event()
        self._tick = 60.0  # uyanma çözünürlüğü

    def run(self):
        logger.info("MaintenanceWorker başladı (retention=%s gün)", self.retention_days)
        last_cleanup = 0.0
        last_license = 0.0

        # Başlangıçta bir kez çalıştır
        self._run_cleanup()
        if self.license_check:
            self._run_license_check()

        while not self.stop_event.is_set():
            now = time.monotonic()
            if now - last_cleanup >= self.cleanup_interval:
                self._run_cleanup()
                last_cleanup = now
            if self.license_check and now - last_license >= self.license_interval:
                self._run_license_check()
                last_license = now
            self.stop_event.wait(timeout=self._tick)

        logger.info("MaintenanceWorker durdu")

    def _run_cleanup(self):
        if self.retention_days <= 0:
            return
        try:
            removed = self.snapshots.cleanup_old(self.retention_days)
            if removed:
                logger.info("Retention: %s eski snapshot klasörü silindi", removed)
        except Exception as e:  # noqa: BLE001
            logger.exception("Retention temizliği hatası: %s", e)

    def _run_license_check(self):
        try:
            self.license_check()
        except Exception as e:  # noqa: BLE001
            logger.exception("Lisans yeniden kontrol hatası: %s", e)
