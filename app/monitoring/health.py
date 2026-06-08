"""
Sağlık (health) registry — bellek içi, thread-safe.

Camera ve Shopify worker'ları durumlarını buraya yazar; Admin Panel ve /health
endpoint'i buradan okur. Böylece "kamera 3 saattir tespit yapmıyor" gibi sessiz
arızalar görünür olur.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


@dataclass
class CameraHealth:
    camera_id: int
    camera_name: str
    connected: bool = False
    last_frame_at: datetime | None = None
    last_detection_at: datetime | None = None
    frames_processed: int = 0
    detections: int = 0
    reconnects: int = 0
    last_error: str | None = None

    def is_stale(self, stale_seconds: int, now: datetime | None = None) -> bool:
        """Bağlı ama belirtilen süredir frame gelmiyorsa stale say."""
        if not self.connected:
            return True
        if self.last_frame_at is None:
            return True
        now = now or datetime.now()
        return (now - self.last_frame_at).total_seconds() > stale_seconds

    def to_dict(self, stale_seconds: int, now: datetime | None = None) -> dict:
        d = asdict(self)
        d["last_frame_at"] = _iso(self.last_frame_at)
        d["last_detection_at"] = _iso(self.last_detection_at)
        d["stale"] = self.is_stale(stale_seconds, now)
        d["status"] = (
            "ok" if (self.connected and not d["stale"]) else ("stale" if self.connected else "down")
        )
        return d


@dataclass
class ShopifyHealth:
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    success_total: int = 0
    failed_total: int = 0
    not_found_total: int = 0


@dataclass
class LicenseHealth:
    status: str = "unknown"
    customer: str | None = None
    plan: str | None = None
    expires_at: str | None = None
    days_remaining: int | None = None
    max_cameras: int | None = None


class HealthRegistry:
    """Tüm runtime sağlık durumunu toplayan tek nokta."""

    def __init__(self, stale_seconds: int = 60):
        self._lock = threading.Lock()
        self._cameras: dict[int, CameraHealth] = {}
        self._shopify = ShopifyHealth()
        self._license = LicenseHealth()
        self._stale_seconds = stale_seconds
        self.started_at = datetime.now()

    # ---- kamera tarafı ----
    def register_camera(self, camera_id: int, camera_name: str) -> None:
        with self._lock:
            self._cameras[camera_id] = CameraHealth(camera_id, camera_name)

    def camera_connected(self, camera_id: int) -> None:
        with self._lock:
            c = self._cameras.get(camera_id)
            if c:
                c.connected = True
                c.last_error = None

    def camera_disconnected(self, camera_id: int, error: str | None = None) -> None:
        with self._lock:
            c = self._cameras.get(camera_id)
            if c:
                c.connected = False
                if error:
                    c.last_error = error[:300]

    def record_reconnect(self, camera_id: int) -> None:
        with self._lock:
            c = self._cameras.get(camera_id)
            if c:
                c.reconnects += 1

    def record_frame(self, camera_id: int, ts: datetime | None = None) -> None:
        with self._lock:
            c = self._cameras.get(camera_id)
            if c:
                c.frames_processed += 1
                c.last_frame_at = ts or datetime.now()

    def record_detection(self, camera_id: int, ts: datetime | None = None) -> None:
        with self._lock:
            c = self._cameras.get(camera_id)
            if c:
                c.detections += 1
                c.last_detection_at = ts or datetime.now()

    # ---- shopify tarafı ----
    def shopify_success(self) -> None:
        with self._lock:
            self._shopify.success_total += 1
            self._shopify.last_success_at = datetime.now()

    def shopify_failed(self, error: str, not_found: bool = False) -> None:
        with self._lock:
            self._shopify.last_error = error[:300]
            self._shopify.last_error_at = datetime.now()
            if not_found:
                self._shopify.not_found_total += 1
            else:
                self._shopify.failed_total += 1

    # ---- lisans tarafı ----
    def set_license(self, health: LicenseHealth) -> None:
        with self._lock:
            self._license = health

    # ---- okuma ----
    def snapshot(self) -> dict:
        now = datetime.now()
        with self._lock:
            cameras = [c.to_dict(self._stale_seconds, now) for c in self._cameras.values()]
            shopify = asdict(self._shopify)
            shopify["last_success_at"] = _iso(self._shopify.last_success_at)
            shopify["last_error_at"] = _iso(self._shopify.last_error_at)
            license_ = asdict(self._license)
            uptime = int((now - self.started_at).total_seconds())

        cams_ok = sum(1 for c in cameras if c["status"] == "ok")
        overall = (
            "ok" if cameras and cams_ok == len(cameras) else ("degraded" if cams_ok > 0 else "down")
        )
        return {
            "status": overall,
            "uptime_seconds": uptime,
            "started_at": _iso(self.started_at),
            "cameras": cameras,
            "cameras_ok": cams_ok,
            "cameras_total": len(cameras),
            "shopify": shopify,
            "license": license_,
        }
