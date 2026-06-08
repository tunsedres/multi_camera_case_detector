"""
YAML tabanlı yapısal konfigürasyon (config/config.yaml).

pydantic ile doğrulanır → hatalı/eksik config uygulamayı erken ve net mesajla durdurur.
RTSP URL'lerindeki {user}/{pass} placeholder'ları .env'deki CAMERA_* ile doldurulur.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from app.settings import Settings, get_settings


class CameraConfig(BaseModel):
    id: int = Field(ge=1)
    name: str
    rtsp: str
    enabled: bool = True


class DetectionConfig(BaseModel):
    target_fps: int = Field(default=3, ge=1, le=25)
    dedup_window_seconds: int = Field(default=30, ge=0)
    order_no_regex: str = r"^#?\d{3,8}$"
    add_hash_prefix: bool = True
    symbols: list[str] = Field(default_factory=lambda: ["CODE128", "QRCODE"])

    @field_validator("order_no_regex")
    @classmethod
    def _valid_regex(cls, v: str) -> str:
        import re

        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"order_no_regex geçersiz: {e}") from e
        return v


class ShopifyConfig(BaseModel):
    write_to_order_note: bool = True
    write_to_metafield: bool = True
    metafield_namespace: str = "packing"
    note_template: str = "📦 [{timestamp}] Paketleme: {camera_name} (Kamera #{camera_id})"
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    max_retries: int = Field(default=5, ge=0)


class StorageConfig(BaseModel):
    db_path: str = "data/events.db"
    snapshots_enabled: bool = True
    snapshots_dir: str = "data/snapshots"
    snapshot_retention_days: int = Field(default=90, ge=0)
    jpeg_quality: int = Field(default=85, ge=1, le=100)


class MaintenanceConfig(BaseModel):
    cleanup_interval_hours: float = Field(default=6.0, gt=0)
    license_recheck_hours: float = Field(default=12.0, gt=0)


class MonitoringConfig(BaseModel):
    camera_stale_seconds: int = Field(default=60, ge=5)


class AppConfig(BaseModel):
    cameras: list[CameraConfig]
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    shopify: ShopifyConfig = Field(default_factory=ShopifyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    @field_validator("cameras")
    @classmethod
    def _unique_ids(cls, cameras: list[CameraConfig]) -> list[CameraConfig]:
        ids = [c.id for c in cameras]
        if len(ids) != len(set(ids)):
            raise ValueError("Kamera id'leri benzersiz olmalı")
        return cameras

    @property
    def enabled_cameras(self) -> list[CameraConfig]:
        return [c for c in self.cameras if c.enabled]


def load_config(
    config_path: str = "config/config.yaml",
    settings: Settings | None = None,
) -> AppConfig:
    """config.yaml'i yükler, doğrular, RTSP placeholder'larını .env ile doldurur."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config bulunamadı: {config_path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    config = AppConfig.model_validate(raw)

    settings = settings or get_settings()
    user = settings.camera_username
    password = settings.camera_password
    for cam in config.cameras:
        cam.rtsp = cam.rtsp.replace("{user}", user).replace("{pass}", password)

    return config
