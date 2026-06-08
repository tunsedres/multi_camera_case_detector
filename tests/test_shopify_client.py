"""Shopify GraphQL client testleri (ağ mock'lanır)."""

import json
from datetime import datetime

import pytest

from app.integrations import shopify_client as sc
from app.integrations.shopify_client import OrderNotFound, ShopifyClient, ShopifyError


class FakeResp:
    def __init__(self, json_data, status_code=200, headers=None):
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


@pytest.fixture
def client():
    return ShopifyClient(shop_url="test.myshopify.com", access_token="shpat_x")


def _order_resp(gid="gid://shopify/Order/1", name="#1042", note=None):
    return FakeResp(
        {"data": {"orders": {"edges": [{"node": {"id": gid, "name": name, "note": note}}]}}}
    )


def test_find_order(client, monkeypatch):
    monkeypatch.setattr(client.session, "post", lambda *a, **k: _order_resp())
    node = client.find_order_by_name("#1042")
    assert node["id"] == "gid://shopify/Order/1"


def test_find_order_none(client, monkeypatch):
    monkeypatch.setattr(
        client.session, "post", lambda *a, **k: FakeResp({"data": {"orders": {"edges": []}}})
    )
    assert client.find_order_by_name("#9999") is None


def test_auth_error_raises(client, monkeypatch):
    monkeypatch.setattr(client.session, "post", lambda *a, **k: FakeResp({}, status_code=401))
    with pytest.raises(ShopifyError, match="Yetki"):
        client.find_order_by_name("#1")


def test_throttle_then_success(client, monkeypatch):
    monkeypatch.setattr(sc.time, "sleep", lambda *_a, **_k: None)
    throttled = FakeResp(
        {
            "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
            "extensions": {
                "cost": {
                    "requestedQueryCost": 10,
                    "throttleStatus": {"currentlyAvailable": 0, "restoreRate": 50},
                }
            },
        }
    )
    responses = [throttled, _order_resp()]
    monkeypatch.setattr(client.session, "post", lambda *a, **k: responses.pop(0))
    node = client.find_order_by_name("#1042")
    assert node["name"] == "#1042"


def test_user_errors_raise(client, monkeypatch):
    monkeypatch.setattr(
        client,
        "_graphql",
        lambda *a, **k: {"orderUpdate": {"userErrors": [{"field": "note", "message": "bad"}]}},
    )
    with pytest.raises(ShopifyError, match="userErrors"):
        client.append_to_note("gid://shopify/Order/1", None, "yeni")


def test_log_packing_event_not_found(client, monkeypatch):
    monkeypatch.setattr(client, "_graphql", lambda *a, **k: {"orders": {"edges": []}})
    with pytest.raises(OrderNotFound):
        client.log_packing_event(
            order_no="#9999",
            camera_id=1,
            camera_name="Masa 1",
            timestamp=datetime(2026, 5, 22, 14, 30, 15),
            note_template="📦 [{timestamp}] {camera_name} (#{camera_id})",
        )


def test_log_packing_event_full_flow(client, monkeypatch):
    calls = []

    def fake_graphql(query, variables, **k):
        calls.append((query, variables))
        if "findOrder" in query:
            return {
                "orders": {"edges": [{"node": {"id": "gid://1", "name": "#1042", "note": "eski"}}]}
            }
        if "updateNote" in query:
            return {"orderUpdate": {"order": {"id": "gid://1"}, "userErrors": []}}
        if "setMetafield" in query:
            return {"metafieldsSet": {"metafields": [{"id": "m1"}], "userErrors": []}}
        return {}

    monkeypatch.setattr(client, "_graphql", fake_graphql)
    gid = client.log_packing_event(
        order_no="#1042",
        camera_id=3,
        camera_name="Masa 3",
        timestamp=datetime(2026, 5, 22, 14, 30, 15),
        note_template="📦 [{timestamp}] Paketleme: {camera_name} (Kamera #{camera_id})",
    )
    assert gid == "gid://1"
    # mevcut not'a append yapıldı, üzerine yazılmadı
    note_call = next(v for q, v in calls if "updateNote" in q)
    assert note_call["note"].startswith("eski\n")
    assert "Masa 3" in note_call["note"]


def test_throttle_wait_calc():
    body = {
        "extensions": {
            "cost": {
                "requestedQueryCost": 100,
                "throttleStatus": {"currentlyAvailable": 0, "restoreRate": 50},
            }
        }
    }
    assert ShopifyClient._throttle_wait(body) == 2.0
