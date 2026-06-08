"""
Orchestrator — tüm bileşenleri kurar ve çalıştırır.

Bileşenler:
  * Config + Settings + Logger
  * Lisans değerlendirme (enforce ise startup'ta engelle)
  * Storage (SQLite + snapshots)
  * HealthRegistry
  * CameraWorker (kamera başına) → tespit → dedup → snapshot → DB
  * ShopifyWorker (tek) → pending event'leri Shopify'a yaz
  * MaintenanceWorker → retention temizliği + lisans recheck
  * Admin Web Panel (FastAPI/uvicorn) — ana blocking döngü

Web etkinse uvicorn ana thread'de çalışır (sinyalleri yönetir); diğer her şey
daemon thread'dir. Web kapalıysa basit bir sinyal-bekleme döngüsü kullanılır.
"""

from __future__ import annotations

import signal
import sys
import threading
from datetime import datetime

import numpy as np

from app import __version__
from app.camera_worker import CameraWorker
from app.config import AppConfig, load_config
from app.detection.barcode import BarcodeResult
from app.integrations.shopify_client import ShopifyClient
from app.licensing import LicenseManager, LicenseStatus
from app.logger import setup_logger
from app.monitoring.health import HealthRegistry, LicenseHealth
from app.scheduler import MaintenanceWorker
from app.settings import Settings, get_settings
from app.shopify_worker import ShopifyWorker
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore
from app.web.context import AppContext


class Application:
    def __init__(self, config: AppConfig | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.logger = setup_logger("packing", level=self.settings.log_level)
        self.config = config or load_config(settings=self.settings)
        self.stop_event = threading.Event()

        self.health = HealthRegistry(stale_seconds=self.config.monitoring.camera_stale_seconds)
        self.db = Database(self.config.storage.db_path)
        self.snapshots = SnapshotStore(
            base_dir=self.config.storage.snapshots_dir,
            enabled=self.config.storage.snapshots_enabled,
            jpeg_quality=self.config.storage.jpeg_quality,
        )
        self.license_manager = LicenseManager()
        self._workers: list[threading.Thread] = []

    # ------------------------------------------------------------------ #
    #  Lisans
    # ------------------------------------------------------------------ #
    def _evaluate_license(self) -> LicenseStatus:
        key = self.settings.resolve_license_key()
        active = len(self.config.enabled_cameras)
        status, lic = self.license_manager.evaluate(key, active_cameras=active)

        health = LicenseHealth(status=status.value)
        if lic:
            health.customer = lic.customer
            health.plan = lic.plan
            health.expires_at = lic.expires_at.isoformat() if lic.expires_at else None
            health.days_remaining = lic.days_remaining()
            health.max_cameras = lic.max_cameras
        self.health.set_license(health)
        return status

    def _enforce_license_or_exit(self):
        status = self._evaluate_license()
        if status == LicenseStatus.VALID:
            self.logger.info(
                "Lisans geçerli (%s)", self.health.snapshot()["license"].get("customer")
            )
            return
        msg = {
            LicenseStatus.MISSING: "Lisans anahtarı bulunamadı (LICENSE_KEY / config/license.key).",
            LicenseStatus.INVALID: "Lisans anahtarı geçersiz (imza/format).",
            LicenseStatus.EXPIRED: "Lisans süresi dolmuş.",
            LicenseStatus.OVER_LIMIT: "Aktif kamera sayısı lisans limitini aşıyor.",
        }.get(status, "Lisans doğrulanamadı.")

        if self.settings.license_enforce:
            self.logger.critical("LİSANS HATASI: %s Sistem durduruluyor.", msg)
            sys.exit(2)
        self.logger.warning("LİSANS UYARISI (geliştirme modu, enforce=false): %s", msg)

    # ------------------------------------------------------------------ #
    #  Tespit callback'i
    # ------------------------------------------------------------------ #
    def _on_detection(
        self,
        camera_id: int,
        camera_name: str,
        result: BarcodeResult,
        frame: np.ndarray,
        timestamp: datetime,
    ):
        order_no = result.normalized
        window = self.config.detection.dedup_window_seconds
        if self.db.is_duplicate(order_no, camera_id, window):
            self.logger.debug("[Cam %s] Dedup: %s", camera_id, order_no)
            return

        snapshot_path = self.snapshots.save(frame, camera_id, order_no, timestamp)
        event_id = self.db.insert_event(
            order_no=order_no,
            camera_id=camera_id,
            camera_name=camera_name,
            detected_at=timestamp,
            snapshot_path=snapshot_path,
        )
        self.logger.info(
            "✓ [Cam %s/%s] TESPİT: %s (event_id=%s)", camera_id, camera_name, order_no, event_id
        )

    # ------------------------------------------------------------------ #
    #  Kurulum
    # ------------------------------------------------------------------ #
    def _build_workers(self):
        active = self.config.enabled_cameras
        if not active:
            self.logger.error("Hiç aktif kamera yok! config.yaml'da 'enabled: true' yap.")
            sys.exit(1)

        det = self.config.detection
        for cam in active:
            self.health.register_camera(cam.id, cam.name)
            worker = CameraWorker(
                camera_id=cam.id,
                camera_name=cam.name,
                rtsp_url=cam.rtsp,
                on_detection=self._on_detection,
                target_fps=det.target_fps,
                order_regex=det.order_no_regex,
                add_hash_prefix=det.add_hash_prefix,
                symbols=det.symbols,
                health=self.health,
                stop_event=self.stop_event,
            )
            self._workers.append(worker)
        self.logger.info("%s kamera worker'ı hazırlandı", len(self._workers))

        sh = self.config.shopify
        shopify_client = ShopifyClient.from_settings(self.settings)
        self._workers.append(
            ShopifyWorker(
                db=self.db,
                client=shopify_client,
                note_template=sh.note_template,
                write_note=sh.write_to_order_note,
                write_metafield=sh.write_to_metafield,
                metafield_namespace=sh.metafield_namespace,
                poll_interval=sh.poll_interval_seconds,
                max_retries=sh.max_retries,
                health=self.health,
                stop_event=self.stop_event,
            )
        )

        m = self.config.maintenance
        self._workers.append(
            MaintenanceWorker(
                snapshots=self.snapshots,
                retention_days=self.config.storage.snapshot_retention_days,
                cleanup_interval_hours=m.cleanup_interval_hours,
                license_recheck_hours=m.license_recheck_hours,
                license_check=self._evaluate_license,
                stop_event=self.stop_event,
            )
        )

    def context(self) -> AppContext:
        return AppContext(
            db=self.db,
            health=self.health,
            snapshots=self.snapshots,
            settings=self.settings,
            config=self.config,
            version=__version__,
        )

    # ------------------------------------------------------------------ #
    #  Çalıştırma
    # ------------------------------------------------------------------ #
    def run(self):
        self.logger.info("=" * 60)
        self.logger.info("Packing Detector v%s başlıyor", __version__)
        self.logger.info("=" * 60)

        if not self.settings.shopify_shop_url:
            self.logger.error("SHOPIFY_SHOP_URL .env'de tanımlı değil!")
            sys.exit(1)
        if not (self.settings.shopify_access_token or self.settings.shopify_use_client_credentials):
            self.logger.error(
                "Shopify kimlik bilgisi yok: SHOPIFY_ACCESS_TOKEN ya da "
                "SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET tanımla!"
            )
            sys.exit(1)

        self._enforce_license_or_exit()
        self._build_workers()

        for w in self._workers:
            w.start()
        self.logger.info("Tüm worker'lar başladı.")

        if self.settings.web_enabled:
            self._run_web()  # ana thread'i bloklar, sinyalleri yönetir
        else:
            self._run_headless()

        self.shutdown()

    def _run_web(self):
        import uvicorn

        from app.web.server import create_app

        fastapi_app = create_app(self.context())
        self.logger.info(
            "Admin Panel: http://%s:%s", self.settings.web_host, self.settings.web_port
        )
        uv_config = uvicorn.Config(
            app=fastapi_app,
            host=self.settings.web_host,
            port=self.settings.web_port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(uv_config)
        try:
            server.run()  # SIGINT/SIGTERM'i kendi yakalar
        except KeyboardInterrupt:
            pass

    def _run_headless(self):
        def _handler(signum, _frame):
            self.logger.info("Sinyal alındı (%s), kapatılıyor...", signum)
            self.stop_event.set()

        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGTERM, _handler)
        self.logger.info("Web kapalı — headless mod. Ctrl+C ile durdur.")
        while not self.stop_event.is_set():
            self.stop_event.wait(timeout=1.0)

    def shutdown(self):
        self.logger.info("Worker'lar durduruluyor...")
        self.stop_event.set()
        for w in self._workers:
            w.join(timeout=10)
        self.logger.info("Tüm worker'lar durdu. Çıkılıyor.")


def main():
    Application().run()


if __name__ == "__main__":
    main()
