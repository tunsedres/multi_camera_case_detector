"""
Shopify Admin API client.
- Sipariş arama (name ile)
- Order note'a append
- Metafield ekleme

Rate limit: REST API 2 req/sec (leaky bucket, 40 burst).
Retry: 429 ve 5xx için exponential backoff.
"""
import time
import logging
import urllib.parse
from typing import Optional
from datetime import datetime

import requests


logger = logging.getLogger("packing.shopify")


class ShopifyError(Exception):
    pass


class OrderNotFound(ShopifyError):
    pass


class ShopifyClient:
    def __init__(
        self,
        shop_url: str,
        access_token: str,
        api_version: str = "2024-01",
        timeout: int = 15,
    ):
        if not shop_url or not access_token:
            raise ValueError("Shopify shop_url ve access_token gerekli")

        self.base_url = f"https://{shop_url}/admin/api/{api_version}"
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs):
        """Rate-limit ve retry'lı request."""
        url = f"{self.base_url}{path}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise ShopifyError(f"Ağ hatası: {e}") from e
                time.sleep(2 ** attempt)
                continue

            # 429 = rate limit, Retry-After header'a bak
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2))
                logger.warning(f"Rate limit, {wait}s bekleniyor...")
                time.sleep(wait)
                continue

            # 5xx = sunucu hatası, retry
            if 500 <= resp.status_code < 600 and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue

            return resp

        raise ShopifyError("Max retry'a ulaşıldı")

    def find_order_by_name(self, name: str) -> Optional[dict]:
        """
        Sipariş no ile arama. 'name' alanı '#1234' formatındadır.
        Shopify'da bu alan URL-encoded olarak gönderilir.
        """
        params = {
            "name": name,
            "status": "any",  # 'open' default - tüm durumlardakiler için 'any'
            "fields": "id,name,note",
            "limit": 1,
        }
        # URL encoding (# karakteri için kritik)
        query = urllib.parse.urlencode(params)
        resp = self._request("GET", f"/orders.json?{query}")

        if resp.status_code != 200:
            raise ShopifyError(f"Sipariş arama hatası: {resp.status_code} - {resp.text[:200]}")

        orders = resp.json().get("orders", [])
        return orders[0] if orders else None

    def append_to_note(self, order_id: int, current_note: Optional[str], new_line: str):
        """
        order.note alanına yeni satır ekler (üzerine yazmaz).
        DİKKAT: Bu API çağrısı tüm order'ı update eder, sadece note değil.
        """
        # Mevcut not + yeni satır
        existing = (current_note or "").strip()
        updated_note = f"{existing}\n{new_line}".strip() if existing else new_line

        payload = {"order": {"id": order_id, "note": updated_note}}
        resp = self._request("PUT", f"/orders/{order_id}.json", json=payload)

        if resp.status_code != 200:
            raise ShopifyError(f"Note güncelleme hatası: {resp.status_code} - {resp.text[:200]}")

    def add_metafield(self, order_id: int, key: str, value: str, namespace: str = "packing"):
        """
        Sipariş üzerine metafield ekler. Her tespit ayrı bir key olur,
        birikimli kayıt elde edilir.
        """
        payload = {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "type": "multi_line_text_field",
            }
        }
        resp = self._request("POST", f"/orders/{order_id}/metafields.json", json=payload)

        if resp.status_code not in (200, 201):
            raise ShopifyError(f"Metafield ekleme hatası: {resp.status_code} - {resp.text[:200]}")

    # ============ HIGH LEVEL ============

    def log_packing_event(
        self,
        order_no: str,
        camera_id: int,
        camera_name: str,
        timestamp: datetime,
        note_template: str,
        write_note: bool = True,
        write_metafield: bool = True,
    ):
        """
        Tüm akış: sipariş bul → note'a ekle → metafield ekle.
        OrderNotFound atılırsa retry edilmemeli (sipariş gerçekten yok).
        """
        order = self.find_order_by_name(order_no)
        if not order:
            raise OrderNotFound(f"Sipariş bulunamadı: {order_no}")

        order_id = order["id"]
        timestamp_str = timestamp.strftime("%d.%m.%Y %H:%M:%S")

        note_text = note_template.format(
            timestamp=timestamp_str,
            camera_name=camera_name,
            camera_id=camera_id,
            order_no=order_no,
        )

        if write_note:
            self.append_to_note(order_id, order.get("note"), note_text)

        if write_metafield:
            # Her tespit için unique key (timestamp epoch)
            key = f"event_{int(timestamp.timestamp())}"
            self.add_metafield(order_id, key, note_text)

        logger.info(f"Shopify'a yazıldı: {order_no} (order_id={order_id})")
        return order_id
