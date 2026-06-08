"""
Shopify token üretimi — client_credentials akışı.

Neden: Statik `shpat_` token'ı elle yapıştırmak yerine, mağazaya ait
`client_id` + `client_secret` ile `/admin/oauth/access_token` uç noktasından
token alınır. Bu token süreli (`expires_in`) olduğu için süresi dolmadan
proaktif yenilenir; 401 alınırsa zorla yenilenir.

İstek gövdesi (x-www-form-urlencoded):
    grant_type=client_credentials
    client_id=...
    client_secret=...

Yanıt (JSON):
    {"access_token": "shpat_...", "scope": "...", "expires_in": 86400}

Not: Bazı mağazalar `expires_in` döndürmez (kalıcı token). O durumda yenileme
yapılmaz, sadece 401 üzerine bir kez tazelenir.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

logger = logging.getLogger("packing.shopify_auth")

# Süre dolmadan ne kadar önce yenileyelim (saniye). Token tam sınırda iken
# yapılan bir istek 401 yememesi için güvenlik payı.
_EXPIRY_MARGIN_SECONDS = 300

# expires_in yoksa varsayılan TTL (Shopify client_credentials token'ları tipik
# olarak ~24 saat). Kalıcıymış gibi davranmak yerine yine de periyodik tazeleriz.
_DEFAULT_TTL_SECONDS = 86400


class ShopifyAuthError(Exception):
    """Token alınamadı (ağ, kimlik bilgileri, sunucu)."""


class TokenProvider:
    """
    client_credentials ile token alır, önbelleğe alır, süresi dolmadan yeniler.

    Thread-safe: ShopifyWorker tek thread olsa da test_connection vb. başka
    çağıranlar olabilir; kilit ile aynı anda tek yenileme garanti edilir.
    """

    def __init__(
        self,
        shop_url: str,
        client_id: str,
        client_secret: str,
        timeout: int = 15,
    ):
        if not (shop_url and client_id and client_secret):
            raise ValueError("shop_url, client_id ve client_secret gerekli")
        self.shop_url = shop_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.token_url = f"https://{shop_url}/admin/oauth/access_token"

        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0  # monotonic saniye; 0 = token yok

    def get_token(self) -> str:
        """Geçerli token döner; yoksa/süresi dolmuşsa yeniler."""
        with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            return self._refresh_locked()

    def invalidate(self) -> str:
        """Token'ı zorla tazele (ör. 401 sonrası). Yeni token döner."""
        with self._lock:
            return self._refresh_locked()

    # ------------------------------------------------------------------ #
    def _refresh_locked(self) -> str:
        """Kilidi tutan çağıran içinde token alır. Çift yenilemeyi önler."""
        try:
            resp = requests.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise ShopifyAuthError(f"Token isteği ağ hatası: {e}") from e

        if resp.status_code != 200:
            raise ShopifyAuthError(
                f"Token alınamadı ({resp.status_code}): "
                f"client_id/secret kontrol et — {resp.text[:200]}"
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise ShopifyAuthError(f"Token yanıtı JSON değil: {resp.text[:200]}") from e

        token = body.get("access_token")
        if not token:
            raise ShopifyAuthError(f"Yanıtta access_token yok: {body}")

        ttl = int(body.get("expires_in") or _DEFAULT_TTL_SECONDS)
        # Pay düşülünce negatif kalmasın diye alt sınır koy.
        effective = max(ttl - _EXPIRY_MARGIN_SECONDS, 60)
        self._token = token
        self._expires_at = time.monotonic() + effective
        logger.info("Shopify token yenilendi (ttl=%ss, yenileme=%ss sonra)", ttl, effective)
        return token
