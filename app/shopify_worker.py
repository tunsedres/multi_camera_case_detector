"""
Camera worker'larından gelen tespitleri Shopify'a yazan tek worker.

Tek thread olması rate limit yönetimini basitleştirir. Internet kesilse tespit
devam eder, kuyruk birikir, internet gelince işlenir.

Akış:
  1. Pending event'leri DB'den çek
  2. Her birini Shopify'a yaz (note + metafield)
  3. Başarı/hata DB'ye + HealthRegistry'ye yansıt
  4. Retry (failed olanlar max_retries'a kadar tekrar denenir)
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from app.integrations.shopify_client import OrderNotFound, ShopifyClient, ShopifyError
from app.monitoring.health import HealthRegistry
from app.storage.database import Database

logger = logging.getLogger("packing.shopify_worker")


class ShopifyWorker(threading.Thread):
    """Pending event'leri poll_interval'da bir tarar, Shopify'a yazar."""

    def __init__(
        self,
        db: Database,
        client: ShopifyClient,
        note_template: str,
        write_note: bool = True,
        write_metafield: bool = True,
        metafield_namespace: str = "packing",
        poll_interval: float = 2.0,
        max_retries: int = 5,
        health: HealthRegistry | None = None,
        stop_event: threading.Event | None = None,
    ):
        super().__init__(name="ShopifyWorker", daemon=True)
        self.db = db
        self.client = client
        self.note_template = note_template
        self.write_note = write_note
        self.write_metafield = write_metafield
        self.metafield_namespace = metafield_namespace
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.health = health
        self.stop_event = stop_event or threading.Event()

    def run(self):
        logger.info("ShopifyWorker başladı")
        while not self.stop_event.is_set():
            try:
                self._process_batch()
            except Exception as e:  # noqa: BLE001
                logger.exception("Batch hatası: %s", e)
            self.stop_event.wait(timeout=self.poll_interval)
        logger.info("ShopifyWorker durdu")

    def _process_batch(self):
        events = self.db.get_pending_events(max_retries=self.max_retries, limit=20)
        if not events:
            return
        logger.debug("%s pending event işleniyor", len(events))
        for event in events:
            if self.stop_event.is_set():
                break
            self._process_one(event)
            time.sleep(0.5)  # rate limit'e takılmamak için ek pay

    def _process_one(self, event: dict):
        event_id = event["id"]
        order_no = event["order_no"]

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
                metafield_namespace=self.metafield_namespace,
            )
            self.db.mark_shopify_success(event_id)
            if self.health:
                self.health.shopify_success()
        except OrderNotFound as e:
            logger.warning("Sipariş yok: %s", order_no)
            self.db.mark_shopify_failed(event_id, str(e), status="not_found")
            if self.health:
                self.health.shopify_failed(str(e), not_found=True)
        except ShopifyError as e:
            logger.error("Shopify hatası (%s): %s", order_no, e)
            self.db.mark_shopify_failed(event_id, str(e), status="failed")
            if self.health:
                self.health.shopify_failed(str(e))
