"""
Ana entry point.
- Config yükle
- Database init
- Her aktif kamera için CameraWorker başlat
- ShopifyWorker başlat
- Graceful shutdown (Ctrl+C)
"""
import signal
import sys
import threading
from datetime import datetime

import numpy as np

from app.config import load_config, get_shopify_config
from app.logger import setup_logger
from app.camera_worker import CameraWorker
from app.shopify_worker import ShopifyWorker
from app.detection.barcode import BarcodeResult
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore
from app.integrations.shopify_client import ShopifyClient


# Global state - stop_event tüm worker'lar tarafından paylaşılır
stop_event = threading.Event()


def main():
    logger = setup_logger("packing")
    logger.info("=" * 60)
    logger.info("Shopify Paketleme Tespit Sistemi başlıyor")
    logger.info("=" * 60)

    # 1. Config yükle
    config = load_config()
    shopify_cfg = get_shopify_config()

    if not shopify_cfg["access_token"]:
        logger.error("SHOPIFY_ACCESS_TOKEN .env'de tanımlı değil!")
        sys.exit(1)

    # 2. Storage
    db = Database(config["storage"]["db_path"])
    snapshots = SnapshotStore(
        base_dir=config["storage"]["snapshots_dir"],
        enabled=config["storage"]["snapshots_enabled"],
    )

    # 3. Shopify client
    shopify_client = ShopifyClient(
        shop_url=shopify_cfg["shop_url"],
        access_token=shopify_cfg["access_token"],
        api_version=shopify_cfg["api_version"],
    )

    # 4. Dedup kontrolü + DB kayıt + snapshot - bunlar callback içinde olacak
    dedup_window = config["detection"]["dedup_window_seconds"]

    def on_detection(
        camera_id: int,
        camera_name: str,
        result: BarcodeResult,
        frame: np.ndarray,
        timestamp: datetime,
    ):
        """Bir kamera worker'ı barkod tespit ettiğinde çağrılır."""
        order_no = result.normalized

        # Dedup: aynı sipariş + aynı kamerada N saniye içinde tekrar
        if db.is_duplicate(order_no, camera_id, dedup_window):
            logger.debug(f"[Cam {camera_id}] Dedup: {order_no} (yakın zamanda okundu)")
            return

        # Snapshot kaydet
        snapshot_path = snapshots.save(frame, camera_id, order_no, timestamp)

        # DB'ye kaydet (Shopify worker buradan çekecek)
        event_id = db.insert_event(
            order_no=order_no,
            camera_id=camera_id,
            camera_name=camera_name,
            detected_at=timestamp,
            snapshot_path=snapshot_path,
        )

        logger.info(
            f"✓ [Cam {camera_id}/{camera_name}] TESPİT: {order_no} "
            f"(event_id={event_id}, snapshot={snapshot_path})"
        )

    # 5. Camera worker'ları başlat
    workers = []
    active_cameras = [c for c in config["cameras"] if c.get("enabled", True)]

    if not active_cameras:
        logger.error("Hiç aktif kamera yok! config.yaml'da 'enabled: true' yap.")
        sys.exit(1)

    for cam in active_cameras:
        worker = CameraWorker(
            camera_id=cam["id"],
            camera_name=cam["name"],
            rtsp_url=cam["rtsp"],
            on_detection=on_detection,
            target_fps=config["detection"]["target_fps"],
            order_regex=config["detection"]["order_no_regex"],
            add_hash_prefix=config["detection"]["add_hash_prefix"],
            stop_event=stop_event,
        )
        worker.start()
        workers.append(worker)

    logger.info(f"{len(workers)} kamera worker'ı başladı")

    # 6. Shopify worker
    shopify_worker = ShopifyWorker(
        db=db,
        client=shopify_client,
        note_template=config["shopify"]["note_template"],
        write_note=config["shopify"]["write_to_order_note"],
        write_metafield=config["shopify"]["write_to_metafield"],
        stop_event=stop_event,
    )
    shopify_worker.start()

    # 7. Graceful shutdown
    def shutdown(signum, frame):
        logger.info("Shutdown sinyali alındı, worker'lar durduruluyor...")
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Sistem hazır. Ctrl+C ile durdur.")

    # Ana thread - tüm worker'lar bitene kadar bekle
    try:
        for w in workers:
            w.join()
        shopify_worker.join()
    except KeyboardInterrupt:
        stop_event.set()

    logger.info("Tüm worker'lar durdu. Çıkılıyor.")


if __name__ == "__main__":
    main()
