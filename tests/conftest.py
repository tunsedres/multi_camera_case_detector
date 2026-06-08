"""Ortak pytest fixture'ları."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import AppConfig, CameraConfig
from app.monitoring.health import HealthRegistry
from app.settings import Settings
from app.storage.database import Database
from app.storage.snapshots import SnapshotStore
from app.web.context import AppContext


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(str(tmp_path / "events.db"))


@pytest.fixture
def settings() -> Settings:
    # _env_file=None → testler repodaki olası .env'den etkilenmez
    return Settings(_env_file=None, admin_password="", shopify_access_token="x")


@pytest.fixture
def app_config() -> AppConfig:
    return AppConfig(
        cameras=[
            CameraConfig(id=1, name="Masa 1", rtsp="rtsp://x:y@host/1", enabled=True),
            CameraConfig(id=2, name="Masa 2", rtsp="rtsp://x:y@host/2", enabled=False),
        ]
    )


@pytest.fixture
def context(tmp_path, db, settings, app_config) -> AppContext:
    snaps = SnapshotStore(str(tmp_path / "snapshots"), enabled=True)
    health = HealthRegistry(stale_seconds=60)
    health.register_camera(1, "Masa 1")
    return AppContext(db=db, health=health, snapshots=snaps, settings=settings, config=app_config)


@pytest.fixture
def keypair():
    """Test için ephemeral Ed25519 anahtar çifti + lisans imzalama yardımcısı."""
    priv = Ed25519PrivateKey.generate()
    pub_hex = (
        priv.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )

    def issue(payload: dict) -> str:
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        sig = priv.sign(payload_b64.encode("ascii"))
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        return f"{payload_b64}.{sig_b64}"

    return pub_hex, issue
