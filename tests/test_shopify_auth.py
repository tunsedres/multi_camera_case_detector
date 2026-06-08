"""Shopify client_credentials token provider testleri (ağ mock'lanır)."""

import json

import pytest

from app.integrations import shopify_auth as sa
from app.integrations.shopify_auth import ShopifyAuthError, TokenProvider


class FakeResp:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


@pytest.fixture
def provider():
    return TokenProvider(
        shop_url="test.myshopify.com",
        client_id="cid",
        client_secret="csecret",
    )


def test_requires_all_credentials():
    with pytest.raises(ValueError):
        TokenProvider(shop_url="", client_id="cid", client_secret="csecret")
    with pytest.raises(ValueError):
        TokenProvider(shop_url="test.myshopify.com", client_id="", client_secret="csecret")


def test_get_token_fetches_and_caches(provider, monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResp({"access_token": "shpat_new", "expires_in": 86400})

    monkeypatch.setattr(sa.requests, "post", fake_post)

    assert provider.get_token() == "shpat_new"
    # ikinci çağrı önbellekten gelir, yeni istek yapılmaz
    assert provider.get_token() == "shpat_new"
    assert len(calls) == 1
    # doğru endpoint ve form gövdesi
    url, kwargs = calls[0]
    assert url == "https://test.myshopify.com/admin/oauth/access_token"
    assert kwargs["data"]["grant_type"] == "client_credentials"
    assert kwargs["data"]["client_id"] == "cid"


def test_invalidate_forces_refresh(provider, monkeypatch):
    tokens = ["shpat_1", "shpat_2"]

    def fake_post(url, **kwargs):
        return FakeResp({"access_token": tokens.pop(0), "expires_in": 86400})

    monkeypatch.setattr(sa.requests, "post", fake_post)

    assert provider.get_token() == "shpat_1"
    assert provider.invalidate() == "shpat_2"
    assert provider.get_token() == "shpat_2"  # yeni token önbelleğe alındı


def test_expiry_triggers_refresh(provider, monkeypatch):
    tokens = ["shpat_1", "shpat_2"]

    def fake_post(url, **kwargs):
        # kısa ttl → pay düşülünce hemen süresi dolmuş sayılır
        return FakeResp({"access_token": tokens.pop(0), "expires_in": 1})

    monkeypatch.setattr(sa.requests, "post", fake_post)

    # monotonic'i ileri sar: ilk çağrıdan sonra zaman geçmiş gibi
    t = [1000.0]
    monkeypatch.setattr(sa.time, "monotonic", lambda: t[0])

    assert provider.get_token() == "shpat_1"
    t[0] += 10_000  # cache süresi geçti
    assert provider.get_token() == "shpat_2"


def test_http_error_raises(provider, monkeypatch):
    monkeypatch.setattr(
        sa.requests, "post", lambda url, **k: FakeResp({"error": "invalid_client"}, 401)
    )
    with pytest.raises(ShopifyAuthError, match="Token alınamadı"):
        provider.get_token()


def test_missing_access_token_raises(provider, monkeypatch):
    monkeypatch.setattr(sa.requests, "post", lambda url, **k: FakeResp({"scope": "x"}))
    with pytest.raises(ShopifyAuthError, match="access_token yok"):
        provider.get_token()
