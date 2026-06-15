"""
Bakım worker'ı — periyodik arka plan görevleri.

* Snapshot retention temizliği (doküman: 90 günden eski klasörler silinir).
  Önceki POC'ta cleanup_old() tanımlıydı ama HİÇ çağrılmıyordu — disk sonsuz
  büyüyordu. Bu worker o açığı kapatır.
* Lisans yeniden kontrolü (süre dolumu runtime'da yakalansın diye).
* Periyodik süreç yeniden başlatma (paddlepaddle native bellek sızıntısı kesin
  çözümü — bellek yalnızca süreç çıkınca bırakıldığı için uptime sınırında SIGTERM).
"""

from __future__ import annotations

import logging
import os
import signal
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
        paddle_recycle_hours: float = 6.0,
        paddle_recycle: Callable[[], int] | None = None,
        max_uptime_minutes: float = 0.0,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(name="MaintenanceWorker", daemon=True)
        self.snapshots = snapshots
        self.retention_days = retention_days
        self.cleanup_interval = cleanup_interval_hours * 3600
        self.license_interval = license_recheck_hours * 3600
        self.license_check = license_check
        # PaddleOCR motor geri dönüşümü (native bellek emniyet kemeri). 0 = kapalı.
        self.paddle_recycle_interval = paddle_recycle_hours * 3600
        self.paddle_recycle = paddle_recycle
        # Periyodik tam süreç yeniden başlatma (paddle native sızıntısı kesin çözümü).
        # 0 = kapalı. Saniyeye çevir.
        self.max_uptime_seconds = max_uptime_minutes * 60
        self.stop_event = stop_event or threading.Event()
        self._tick = 60.0  # uyanma çözünürlüğü

    def run(self):
        logger.info("MaintenanceWorker başladı (retention=%s gün)", self.retention_days)
        boot = time.monotonic()
        last_cleanup = 0.0
        last_license = 0.0
        last_recycle = boot  # boot'taki taze motoru hemen geri dönüştürme
        if self.max_uptime_seconds > 0:
            logger.info(
                "Periyodik süreç yeniden başlatma açık: uptime %s dk geçince SIGTERM",
                self.max_uptime_seconds / 60,
            )

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
            if (
                self.paddle_recycle
                and self.paddle_recycle_interval > 0
                and now - last_recycle >= self.paddle_recycle_interval
            ):
                self._run_paddle_recycle()
                last_recycle = now
            # Uptime sınırı: native bellek sızıntısı süreç çıkınca bırakıldığı için
            # nazikçe SIGTERM gönder → Docker restart:unless-stopped taze RSS ile döner.
            if self.max_uptime_seconds > 0 and now - boot >= self.max_uptime_seconds:
                self._trigger_restart(now - boot)
                return  # SIGTERM gönderildi; loop'tan çık (stop_event de set olacak)
            self.stop_event.wait(timeout=self._tick)

        logger.info("MaintenanceWorker durdu")

    def _trigger_restart(self, uptime_seconds: float) -> None:
        """Süreci nazikçe sonlandır (paddle native belleğini bırakmanın tek güvenilir
        yolu). os.kill(SIGTERM) → uvicorn/sinyal handler yakalar, worker'lar join edilir,
        süreç 0 ile çıkar, Docker restart:unless-stopped taze RSS ile geri getirir.
        Panel restart'ı ile aynı mekanizma (app/web/context.py)."""
        logger.warning(
            "Uptime %s dk (sınır aşıldı) — paddle bellek sızıntısı için süreç yeniden "
            "başlatılıyor (SIGTERM).",
            round(uptime_seconds / 60, 1),
        )
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception as e:  # noqa: BLE001
            logger.exception("Yeniden başlatma SIGTERM gönderilemedi: %s", e)

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

    def _run_paddle_recycle(self):
        try:
            self.paddle_recycle()
        except Exception as e:  # noqa: BLE001
            logger.exception("PaddleOCR geri dönüşüm hatası: %s", e)
