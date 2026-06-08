"""Panelden kamera yönetimi: SQLite CRUD katmanı + web route'ları."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import resolve_camera
from app.settings import Settings
from app.web.server import create_app


# --------------------------------------------------------------------------- #
#  Database kamera CRUD
# --------------------------------------------------------------------------- #
def test_add_and_list(db):
    db.add_camera(1, "Masa 1", "rtsp://{user}:{pass}@h/1", enabled=True)
    db.add_camera(2, "Masa 2", "rtsp://{user}:{pass}@h/2", enabled=False)
    cams = db.list_cameras()
    assert [c["id"] for c in cams] == [1, 2]
    assert cams[0]["name"] == "Masa 1"
    assert cams[1]["enabled"] == 0


def test_duplicate_id_raises(db):
    db.add_camera(1, "Masa 1", "rtsp://h/1")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_camera(1, "Çakışma", "rtsp://h/x")


def test_update_changes_id(db):
    db.add_camera(2, "Masa 2", "rtsp://h/2")
    assert db.update_camera(2, 9, "Yeni", "rtsp://h/9", enabled=True) is True
    assert {c["id"] for c in db.list_cameras()} == {9}


def test_update_to_existing_id_raises(db):
    db.add_camera(1, "Masa 1", "rtsp://h/1")
    db.add_camera(2, "Masa 2", "rtsp://h/2")
    with pytest.raises(sqlite3.IntegrityError):
        db.update_camera(2, 1, "Masa 2", "rtsp://h/2", enabled=True)


def test_update_missing_returns_false(db):
    assert db.update_camera(99, 99, "yok", "rtsp://h/x", enabled=True) is False


def test_delete(db):
    db.add_camera(1, "Masa 1", "rtsp://h/1")
    assert db.delete_camera(1) is True
    assert db.delete_camera(1) is False
    assert db.list_cameras() == []


def test_toggle(db):
    db.add_camera(1, "Masa 1", "rtsp://h/1", enabled=True)
    assert db.toggle_camera(1) is True
    assert db.get_camera(1)["enabled"] == 0
    db.toggle_camera(1)
    assert db.get_camera(1)["enabled"] == 1
    assert db.toggle_camera(999) is False


def test_next_camera_id(db):
    assert db.next_camera_id() == 1
    db.add_camera(1, "a", "rtsp://h/1")
    db.add_camera(5, "b", "rtsp://h/5")
    assert db.next_camera_id() == 6


def test_resolve_camera_fills_placeholders(db):
    db.add_camera(1, "Masa 1", "rtsp://{user}:{pass}@h/1")
    settings = Settings(_env_file=None, camera_username="admin", camera_password="s3cret")
    cam = resolve_camera(db.get_camera(1), settings)
    assert cam.rtsp == "rtsp://admin:s3cret@h/1"
    # DB'de ham şablon korunur (sır yazılmadı)
    assert "{user}" in db.get_camera(1)["rtsp"]


# --------------------------------------------------------------------------- #
#  Web route'ları
# --------------------------------------------------------------------------- #
@pytest.fixture
def client(context):
    # context.db boş kamera tablosuyla gelir; testler kendi kameralarını ekler.
    return TestClient(create_app(context))


def test_cameras_page_empty(client):
    r = client.get("/settings/cameras")
    assert r.status_code == 200
    assert "Henüz kamera yok" in r.text


def test_add_camera_route(client, context):
    r = client.post(
        "/settings/cameras/save",
        data={
            "camera_id": 3,
            "name": "Masa 3",
            "rtsp": "rtsp://{user}:{pass}@192.168.1.103:554/Streaming/Channels/102",
            "enabled": "1",
            "original_id": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    cams = context.db.list_cameras()
    assert any(c["id"] == 3 and c["name"] == "Masa 3" for c in cams)
    assert context.restart_needed is True


def test_edit_camera_route_changes_id(client, context):
    context.db.add_camera(1, "Masa 1", "rtsp://h/1")
    context.db.add_camera(2, "Masa 2", "rtsp://h/2")
    r = client.post(
        "/settings/cameras/save",
        data={
            "camera_id": 9,
            "name": "Masa Yeni",
            "rtsp": "rtsp://{user}:{pass}@h/9",
            "original_id": "2",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert {c["id"] for c in context.db.list_cameras()} == {1, 9}


def test_add_duplicate_id_shows_error(client, context):
    context.db.add_camera(1, "Masa 1", "rtsp://h/1")
    r = client.post(
        "/settings/cameras/save",
        data={
            "camera_id": 1,
            "name": "Çakışma",
            "rtsp": "rtsp://{user}:{pass}@h/x",
            "original_id": "",
        },
    )
    assert r.status_code == 200  # redirect değil, hata sayfası
    assert "zaten kullanımda" in r.text
    assert len(context.db.list_cameras()) == 1  # eklenmedi


def test_invalid_id_shows_error(client, context):
    r = client.post(
        "/settings/cameras/save",
        data={"camera_id": 0, "name": "Bad", "rtsp": "rtsp://h/x", "original_id": ""},
    )
    assert r.status_code == 200
    assert context.db.list_cameras() == []  # id<1 reddedildi


def test_toggle_route(client, context):
    context.db.add_camera(1, "Masa 1", "rtsp://h/1", enabled=True)
    r = client.post("/settings/cameras/1/toggle", follow_redirects=False)
    assert r.status_code == 303
    assert context.db.get_camera(1)["enabled"] == 0


def test_delete_route(client, context):
    context.db.add_camera(2, "Masa 2", "rtsp://h/2")
    r = client.post("/settings/cameras/2/delete", follow_redirects=False)
    assert r.status_code == 303
    assert context.db.list_cameras() == []


def test_delete_missing_404(client):
    assert client.post("/settings/cameras/999/delete").status_code == 404


def test_restart_banner_after_change(client, context):
    context.db.add_camera(1, "Masa 1", "rtsp://h/1", enabled=True)
    assert "yeniden başlat" not in client.get("/settings/cameras").text
    client.post("/settings/cameras/1/toggle")
    assert "yeniden başlat" in client.get("/settings/cameras").text


def test_restart_button_visible_in_banner(client, context):
    context.db.add_camera(1, "Masa 1", "rtsp://h/1", enabled=True)
    context.db.toggle_camera(1)  # restart_needed işaretle
    context.mark_restart_needed()
    body = client.get("/settings/cameras").text
    assert 'action="/settings/restart"' in body
    assert "Yeniden Başlat" in body


def test_restart_route_invokes_restart_fn(context):
    """Restart route process'i öldürmek yerine stub restart_fn'i çağırmalı."""
    called = []
    context.restart_fn = lambda: called.append(True)
    client = TestClient(create_app(context))

    r = client.post("/settings/restart")
    assert r.status_code == 200
    assert "yeniden başlatılıyor" in r.text.lower()
    assert called == [True]  # gerçek SIGTERM yerine stub çağrıldı
