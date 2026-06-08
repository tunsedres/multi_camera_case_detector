"""Admin Web Panel smoke testleri (FastAPI TestClient)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.monitoring.health import HealthRegistry
from app.settings import Settings
from app.storage.snapshots import SnapshotStore
from app.web.context import AppContext
from app.web.server import create_app


@pytest.fixture
def client(context):
    return TestClient(create_app(context))


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code in (200, 503)
    body = r.json()
    assert "status" in body and "cameras" in body


def test_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Dashboard" in r.text


def test_events_page_lists_inserted(context, client):
    context.db.insert_event("#1042", 1, "Masa 1", datetime.now())
    r = client.get("/events")
    assert r.status_code == 200
    assert "#1042" in r.text


def test_event_detail_and_retry(context, client):
    eid = context.db.insert_event("#1042", 1, "Masa 1", datetime.now())
    context.db.mark_shopify_failed(eid, "yok", status="not_found")

    r = client.get(f"/events/{eid}")
    assert r.status_code == 200
    assert "#1042" in r.text

    r2 = client.post(f"/events/{eid}/retry", follow_redirects=False)
    assert r2.status_code == 303
    assert context.db.get_event(eid)["shopify_status"] == "pending"


def test_event_not_found(client):
    assert client.get("/events/99999").status_code == 404


def test_snapshot_serving(context, client):
    ts = datetime.now()
    day_dir = context.snapshots.base_dir / ts.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    img = day_dir / "cam1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")  # minik sahte jpeg
    eid = context.db.insert_event("#1042", 1, "Masa 1", ts, snapshot_path=str(img))

    r = client.get(f"/events/{eid}/snapshot")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"


def test_snapshot_path_traversal_blocked(context, client):
    # snapshot dizini dışını gösteren bir kayıt → 404
    eid = context.db.insert_event("#1042", 1, "Masa 1", datetime.now(), snapshot_path="/etc/passwd")
    assert client.get(f"/events/{eid}/snapshot").status_code == 404


def test_auth_required_when_password_set(tmp_path, app_config):
    settings = Settings(_env_file=None, admin_username="admin", admin_password="secret")
    health = HealthRegistry()
    health.register_camera(1, "Masa 1")
    from app.storage.database import Database

    ctx = AppContext(
        db=Database(str(tmp_path / "e.db")),
        health=health,
        snapshots=SnapshotStore(str(tmp_path / "s"), enabled=False),
        settings=settings,
        config=app_config,
    )
    c = TestClient(create_app(ctx))

    # /health auth'suz erişilebilir
    assert c.get("/health").status_code in (200, 503)
    # / korunur
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("admin", "secret")).status_code == 200
    assert c.get("/", auth=("admin", "wrong")).status_code == 401
