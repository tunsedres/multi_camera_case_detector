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
    # Tespit yöntemi:
    #   'yolo'    → YOLO barkod bölgesini bulur + pyzbar okur (küçük/uzak barkod için)
    #   'barcode' → düz pyzbar (barkod büyük/net ise yeterli)
    #   'ocr'     → etiketteki #numarayı OCR ile oku (order name)
    #   'both'    → önce barkod, bulunamazsa OCR
    mode: str = "ocr"
    # YOLO barkod modeli (mode='yolo'). Image'a gömülü, offline.
    yolo_model_path: str = "models/barcode_yolov8s.pt"
    yolo_conf: float = Field(default=0.35, ge=0, le=1)
    # PaddleOCR (mode='paddle'). Tesseract'tan çok daha doğru; offline modeller.
    paddle_model_root: str = "models/paddleocr/whl"
    paddle_min_confidence: float = Field(default=0.80, ge=0, le=1)
    # Paylaşılan PaddleOCR motor havuzu boyutu (kamera başına DEĞİL, toplam). Tüm
    # kameralar bu havuzu paylaşır → RAM = size× model (8× değil). size kadar OCR
    # aynı anda çalışır. Çok kamerada 2-3 önerilir; arttıkça RAM+CPU artar.
    paddle_pool_size: int = Field(default=2, ge=1, le=8)
    target_fps: int = Field(default=3, ge=1, le=25)
    # Tekrar engelleme (dedup):
    #   'daily'  → aynı sipariş no günde 1 kez yazılır (kameradan bağımsız)
    #   'window' → aynı sipariş+kamera dedup_window_seconds içinde 1 kez
    dedup_mode: str = "daily"
    dedup_window_seconds: int = Field(default=30, ge=0)
    # OCR/barkod uzunluk esnek: 3-10 haneli sipariş no.
    order_no_regex: str = r"^#?\d{6,10}$"
    add_hash_prefix: bool = True
    symbols: list[str] = Field(default_factory=lambda: ["CODE128", "QRCODE"])
    # OCR güven eşiği (0-100). Düşük = daha çok okuma ama daha çok yanlış.
    ocr_min_confidence: float = Field(default=60.0, ge=0, le=100)
    # Çoklu-kare oylama: bir numara 'vote_window_seconds' içinde 'min_votes' kez
    # okununca onaylanır → tek-tük yanlış okumalar Shopify'a gitmez. min_votes=1
    # oylamayı kapatır (her okuma anında tetikler).
    min_votes: int = Field(default=3, ge=1)
    vote_window_seconds: float = Field(default=4.0, gt=0)

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        allowed = {"ocr", "barcode", "both", "yolo", "paddle"}
        if v not in allowed:
            raise ValueError(f"detection.mode '{v}' geçersiz; biri olmalı: {allowed}")
        return v

    @field_validator("dedup_mode")
    @classmethod
    def _valid_dedup_mode(cls, v: str) -> str:
        allowed = {"daily", "window"}
        if v not in allowed:
            raise ValueError(f"detection.dedup_mode '{v}' geçersiz; biri olmalı: {allowed}")
        return v

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
    # Shopify API Timeline'a comment yazamaz; paylaşılan order.note kutusunu
    # kirletmemek için varsayılan KAPALI. Yapısal kayıt metafield'de tutulur.
    write_to_order_note: bool = False
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
    # Kameralar artık SQLite'ta tutulur (panel CRUD). YAML'da bölüm olması
    # gerekmez; geriye dönük uyum için opsiyonel bırakıldı (varsa yoksayılır).
    cameras: list[CameraConfig] = Field(default_factory=list)
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


DEFAULT_CONFIG_PATH = "config/config.yaml"


def load_config(
    config_path: str = DEFAULT_CONFIG_PATH,
    settings: Settings | None = None,
) -> AppConfig:
    """config.yaml'i yükler, doğrular, RTSP placeholder'larını .env ile doldurur."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config bulunamadı: {config_path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Kameralar SQLite'tan gelir (panel CRUD); YAML'daki olası 'cameras' bölümü
    # yoksayılır. Yapısal config (detection/shopify/storage/...) YAML'da kalır.
    raw.pop("cameras", None)
    return AppConfig.model_validate(raw)


# --------------------------------------------------------------------------- #
#  Kameralar SQLite'ta tutulur. DB satırını çalıştırılabilir CameraConfig'e
#  çevirirken RTSP'deki {user}/{pass} placeholder'ları .env ile doldurulur
#  (sır DB'de değil .env'de). app.py worker'ları kurarken bunu kullanır.
# --------------------------------------------------------------------------- #
def resolve_camera(row: dict, settings: Settings | None = None) -> CameraConfig:
    """DB kamera satırını ({user}/{pass} ham) doldurulmuş CameraConfig'e çevirir."""
    settings = settings or get_settings()
    rtsp = (
        row["rtsp"]
        .replace("{user}", settings.camera_username)
        .replace("{pass}", settings.camera_password)
    )
    return CameraConfig(
        id=row["id"],
        name=row["name"],
        rtsp=rtsp,
        enabled=bool(row["enabled"]),
    )
