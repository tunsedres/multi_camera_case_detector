"""
Tüm camera worker'larından gelen tespitleri Shopify'a yazan tek bir worker.
Tek thread olması rate limit yönetimini basitleştirir.

Akış:
1. Pending event'leri DB'den çek
2. Her birini Shopify'a yaz
3. Başarı/hata DB'ye yansıt
4. Retry mekanizması (failed olanlar tekrar denenir)
"""
import time
import logging
import threading

from app.storage.database import Database
from app.integrations.shopify_client import (
    ShopifyClient,
    OrderNotFound,
    ShopifyError,
)


logger = logging.getLogger("packing.shopify_worker")


class ShopifyWorker(threading.Thread):
    """Pending event'leri 2 saniyede bir tarar, Shopify'a yazar."""

    def __init__(
        self,
        db: Database,
        client: ShopifyClient,
        note_template: str,
        write_note: bool = True,
        write_metafield: bool = True,
        poll_interval: float = 2.0,
        max_retries: int = 5,
        stop_event: threading.Event = None,
    ):
        super().__init__(name="ShopifyWorker", daemon=True)
        self.db = db
        self.client = client
        self.note_template = note_template
        self.write_note = write_note
        self.write_metafield = write_metafield
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.stop_event = stop_event or threading.Event()

    def run(self):
        logger.info("ShopifyWorker başladı")
        while not self.stop_event.is_set():
            try:
                self._process_batch()
            except Exception as e:
                logger.exception(f"Batch hatası: {e}")
            self.stop_event.wait(timeout=self.poll_interval)

        logger.info("ShopifyWorker durdu")

    def _process_batch(self):
        events = self.db.get_pending_events(max_retries=self.max_retries, limit=20)
        if not events:
            return

        logger.debug(f"{len(events)} pending event işleniyor")

        for event in events:
            if self.stop_event.is_set():
                break
            self._process_one(event)
            # Rate limit'e takılmamak için
            time.sleep(0.5)

    def _process_one(self, event: dict):
        from datetime import datetime

        event_id = event["id"]
        order_no = event["order_no"]

        # detected_at SQLite'tan string olarak gelebilir
        detected_at = event["detected_at"]
        if isinstance(detected_at, str):
            detected_at = datetime.fromisoformat(detected_at)

        try:
            self.client.log_packing_event(
                order_no=order_no,
                camera_id=event["camera_id"],
                camera_name=event["camera_name"],
                timestamp=detected_at,
                note_template=self.note_template,
                write_note=self.write_note,
                write_metafield=self.write_metafield,
            )
            self.db.mark_shopify_success(event_id)
        except OrderNotFound as e:
            # Retry edilmemeli - sipariş gerçekten yok
            logger.warning(f"Sipariş yok: {order_no}")
            self.db.mark_shopify_failed(event_id, str(e), status="not_found")
        except ShopifyError as e:
            logger.error(f"Shopify hatası ({order_no}): {e}")
            self.db.mark_shopify_failed(event_id, str(e), status="failed")
