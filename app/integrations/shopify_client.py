"""
Shopify Admin API client — GraphQL.

Neden GraphQL: Shopify REST Orders API'yi deprecate ediyor; yeni custom app'ler
için GraphQL zorunlu hale geliyor. Tek endpoint, tipli sorgular, maliyet-tabanlı
rate limit.

Public arayüz (worker'ın gördüğü) REST sürümüyle aynı tutuldu:
  - ShopifyClient, ShopifyError, OrderNotFound
  - log_packing_event(...)

Rate limit: GraphQL maliyet-tabanlı (leaky bucket). throttleStatus okunur, kova
azaldığında proaktif beklenir; THROTTLED hatasında geri çekilip yeniden denenir.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

from app.integrations.shopify_auth import ShopifyAuthError, TokenProvider

logger = logging.getLogger("packing.shopify")

DEFAULT_API_VERSION = "2025-01"

# ---- GraphQL belgeleri ----

_QUERY_FIND_ORDER = """
query findOrder($q: String!) {
  orders(first: 1, query: $q) {
    edges { node { id name note } }
  }
}
"""

# Order ID (GID) ile doğrudan sorgu. Barkod sipariş ID'sini kodladığı için
# isimle aramak yerine ID ile çekmek deterministik ve hızlıdır.
_QUERY_GET_ORDER_BY_ID = """
query getOrder($id: ID!) {
  order(id: $id) { id name note }
}
"""

_MUTATION_UPDATE_NOTE = """
mutation updateNote($id: ID!, $note: String!) {
  orderUpdate(input: { id: $id, note: $note }) {
    order { id }
    userErrors { field message }
  }
}
"""

_MUTATION_SET_METAFIELD = """
mutation setMetafield($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { id key namespace }
    userErrors { field message }
  }
}
"""

_QUERY_SHOP = "query { shop { name myshopifyDomain } }"


class ShopifyError(Exception):
    """Shopify API çağrısı başarısız (ağ, kimlik, sunucu, userError)."""


class OrderNotFound(ShopifyError):
    """Aranan sipariş bulunamadı — retry edilmemeli."""


class ShopifyClient:
    def __init__(
        self,
        shop_url: str,
        access_token: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
        timeout: int = 15,
        min_available_points: int = 100,
        token_provider: TokenProvider | None = None,
    ):
        if not shop_url:
            raise ValueError("Shopify shop_url gerekli")
        if not access_token and token_provider is None:
            raise ValueError("Shopify access_token veya token_provider gerekli")

        self.endpoint = f"https://{shop_url}/admin/api/{api_version}/graphql.json"
        self.timeout = timeout
        self.min_available_points = min_available_points
        self.token_provider = token_provider
        self._static_token = access_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def _auth_token(self) -> str:
        """Geçerli token: provider varsa ondan (önbellekli/yenilenen), yoksa statik."""
        if self.token_provider is not None:
            return self.token_provider.get_token()
        return self._static_token  # type: ignore[return-value]

    @classmethod
    def from_settings(cls, settings) -> ShopifyClient:
        """
        Settings'ten client kur. client_id+secret varsa otomatik token akışı
        (TokenProvider) kullanılır; yoksa statik SHOPIFY_ACCESS_TOKEN'a düşülür.
        """
        if settings.shopify_use_client_credentials:
            provider = TokenProvider(
                shop_url=settings.shopify_shop_url,
                client_id=settings.shopify_client_id,
                client_secret=settings.shopify_client_secret,
            )
            return cls(
                shop_url=settings.shopify_shop_url,
                api_version=settings.shopify_api_version,
                token_provider=provider,
            )
        return cls(
            shop_url=settings.shopify_shop_url,
            access_token=settings.shopify_access_token,
            api_version=settings.shopify_api_version,
        )

    # ------------------------------------------------------------------ #
    #  Düşük seviye GraphQL
    # ------------------------------------------------------------------ #
    def _graphql(self, query: str, variables: dict, max_retries: int = 4) -> dict:
        payload = {"query": query, "variables": variables}
        token_refreshed = False  # token_provider'da 401 sonrası bir kez tazele

        for attempt in range(max_retries):
            try:
                token = self._auth_token()
            except ShopifyAuthError as e:
                raise ShopifyError(f"Token alınamadı: {e}") from e

            headers = {"X-Shopify-Access-Token": token}
            try:
                resp = self.session.post(
                    self.endpoint, json=payload, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    raise ShopifyError(f"Ağ hatası: {e}") from e
                time.sleep(2**attempt)
                continue

            # 401 — token süresi dolmuş olabilir. Provider varsa bir kez tazele
            # ve yeniden dene; statik token'da ya da ikinci 401'de hata ver.
            if resp.status_code == 401:
                if self.token_provider is not None and not token_refreshed:
                    logger.warning("HTTP 401 — Shopify token tazeleniyor")
                    try:
                        self.token_provider.invalidate()
                    except ShopifyAuthError as e:
                        raise ShopifyError(f"Token tazelenemedi: {e}") from e
                    token_refreshed = True
                    continue
                raise ShopifyError("Yetki hatası (401): access token / scope kontrol et")

            # 403 — scope/yetki sorunu, token tazelemek çözmez
            if resp.status_code == 403:
                raise ShopifyError("Yetki hatası (403): access token / scope kontrol et")

            # 429 — nadiren (GraphQL genelde 200+THROTTLED döner)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 2))
                logger.warning("HTTP 429, %ss bekleniyor", wait)
                time.sleep(wait)
                continue

            if 500 <= resp.status_code < 600:
                if attempt == max_retries - 1:
                    raise ShopifyError(f"Sunucu hatası {resp.status_code}: {resp.text[:200]}")
                time.sleep(2**attempt)
                continue

            if resp.status_code != 200:
                raise ShopifyError(f"Beklenmeyen durum {resp.status_code}: {resp.text[:200]}")

            body = resp.json()

            # GraphQL throttling: top-level errors içinde THROTTLED
            errors = body.get("errors")
            if errors:
                if self._is_throttled(errors):
                    wait = self._throttle_wait(body)
                    logger.warning("GraphQL THROTTLED, %.1fs bekleniyor", wait)
                    time.sleep(wait)
                    continue
                raise ShopifyError(f"GraphQL hata: {errors}")

            self._respect_cost(body)
            return body.get("data", {})

        raise ShopifyError("Max retry'a ulaşıldı")

    @staticmethod
    def _is_throttled(errors: list) -> bool:
        return any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors)

    @staticmethod
    def _throttle_wait(body: dict) -> float:
        cost = (body.get("extensions") or {}).get("cost") or {}
        status = cost.get("throttleStatus") or {}
        requested = cost.get("requestedQueryCost", 0)
        available = status.get("currentlyAvailable", 0)
        restore = status.get("restoreRate", 50) or 50
        deficit = max(requested - available, 0)
        return min(max(deficit / restore, 1.0), 10.0)

    def _respect_cost(self, body: dict) -> None:
        """Kova kritik seviyenin altındaysa proaktif kısa bekleme."""
        cost = (body.get("extensions") or {}).get("cost") or {}
        status = cost.get("throttleStatus") or {}
        available = status.get("currentlyAvailable")
        restore = status.get("restoreRate", 50) or 50
        if available is not None and available < self.min_available_points:
            wait = min((self.min_available_points - available) / restore, 5.0)
            if wait > 0:
                time.sleep(wait)

    @staticmethod
    def _check_user_errors(data: dict, field: str) -> None:
        node = data.get(field) or {}
        user_errors = node.get("userErrors") or []
        if user_errors:
            msgs = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in user_errors)
            raise ShopifyError(f"{field} userErrors: {msgs}")

    # ------------------------------------------------------------------ #
    #  Yüksek seviye işlemler
    # ------------------------------------------------------------------ #
    def test_connection(self) -> dict:
        """Bağlantı + token doğrulama. Shop bilgisini döner."""
        data = self._graphql(_QUERY_SHOP, {})
        return data.get("shop") or {}

    def find_order_by_name(self, name: str) -> dict | None:
        """Sipariş no ('#1042') ile arar. {id (gid), name, note} döner ya da None."""
        data = self._graphql(_QUERY_FIND_ORDER, {"q": f"name:{name}"})
        edges = ((data.get("orders") or {}).get("edges")) or []
        if not edges:
            return None
        return edges[0]["node"]

    @staticmethod
    def to_order_gid(order_id: str) -> str:
        """Sayısal order ID'yi GID'e çevirir. Zaten gid:// ise dokunmaz."""
        oid = str(order_id).strip().lstrip("#")
        if oid.startswith("gid://"):
            return oid
        return f"gid://shopify/Order/{oid}"

    def find_order_by_id(self, order_id: str) -> dict | None:
        """Order ID (barkod değeri) ile doğrudan çeker. {id, name, note} ya da None."""
        gid = self.to_order_gid(order_id)
        data = self._graphql(_QUERY_GET_ORDER_BY_ID, {"id": gid})
        return data.get("order")  # yoksa None

    def append_to_note(self, order_gid: str, current_note: str | None, new_line: str) -> None:
        """order.note alanına yeni satır ekler (üzerine yazmaz)."""
        existing = (current_note or "").strip()
        updated = f"{existing}\n{new_line}".strip() if existing else new_line
        data = self._graphql(_MUTATION_UPDATE_NOTE, {"id": order_gid, "note": updated})
        self._check_user_errors(data, "orderUpdate")

    def add_metafield(
        self, order_gid: str, key: str, value: str, namespace: str = "packing"
    ) -> None:
        """Siparişe metafield ekler/günceller (namespace+key benzersiz)."""
        metafields = [
            {
                "ownerId": order_gid,
                "namespace": namespace,
                "key": key,
                "type": "multi_line_text_field",
                "value": value,
            }
        ]
        data = self._graphql(_MUTATION_SET_METAFIELD, {"metafields": metafields})
        self._check_user_errors(data, "metafieldsSet")

    def log_packing_event(
        self,
        order_no: str,
        camera_id: int,
        camera_name: str,
        timestamp: datetime,
        note_template: str,
        write_note: bool = True,
        write_metafield: bool = True,
        metafield_namespace: str = "packing",
        lookup: str = "name",
    ) -> str:
        """
        Tam akış: sipariş bul → note'a ekle → metafield ekle.

        lookup='name' → order_no bir sipariş ismi ('#1042'); name ile aranır (OCR).
        lookup='id'   → order_no bir Shopify order ID (barkod değeri); ID ile çekilir.
        OrderNotFound atılırsa retry edilmemeli (sipariş gerçekten yok).
        Sipariş gid döner.
        """
        if lookup == "id":
            order = self.find_order_by_id(order_no)
        else:
            order = self.find_order_by_name(order_no)
        if not order:
            raise OrderNotFound(f"Sipariş bulunamadı ({lookup}): {order_no}")

        order_gid = order["id"]
        timestamp_str = timestamp.strftime("%d.%m.%Y %H:%M:%S")
        note_text = note_template.format(
            timestamp=timestamp_str,
            camera_name=camera_name,
            camera_id=camera_id,
            # Notta gerçek sipariş ismini göster (barkod ID değil); yoksa okunan değer.
            order_no=order.get("name") or order_no,
        )

        if write_note:
            self.append_to_note(order_gid, order.get("note"), note_text)

        if write_metafield:
            key = f"event_{int(timestamp.timestamp())}"
            self.add_metafield(order_gid, key, note_text, namespace=metafield_namespace)

        logger.info("Shopify'a yazıldı: %s (order_gid=%s)", order_no, order_gid)
        return order_gid
