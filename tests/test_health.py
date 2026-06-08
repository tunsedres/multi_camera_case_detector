"""HealthRegistry testleri."""

from datetime import datetime, timedelta

from app.monitoring.health import HealthRegistry, LicenseHealth


def test_camera_lifecycle():
    h = HealthRegistry(stale_seconds=60)
    h.register_camera(1, "Masa 1")
    h.camera_connected(1)
    h.record_frame(1)
    h.record_detection(1)
    snap = h.snapshot()
    cam = snap["cameras"][0]
    assert cam["status"] == "ok"
    assert cam["frames_processed"] == 1
    assert cam["detections"] == 1
    assert snap["cameras_ok"] == 1


def test_stale_camera():
    h = HealthRegistry(stale_seconds=30)
    h.register_camera(1, "Masa 1")
    h.camera_connected(1)
    # son frame 60 sn önce → stale
    h._cameras[1].last_frame_at = datetime.now() - timedelta(seconds=60)
    snap = h.snapshot()
    assert snap["cameras"][0]["status"] == "stale"
    assert snap["status"] in ("down", "degraded")


def test_disconnected_camera_is_down():
    h = HealthRegistry()
    h.register_camera(1, "Masa 1")
    h.camera_disconnected(1, "kablo çekildi")
    snap = h.snapshot()
    assert snap["cameras"][0]["status"] == "down"
    assert snap["cameras"][0]["last_error"] == "kablo çekildi"


def test_shopify_counters():
    h = HealthRegistry()
    h.shopify_success()
    h.shopify_failed("hata")
    h.shopify_failed("yok", not_found=True)
    snap = h.snapshot()
    assert snap["shopify"]["success_total"] == 1
    assert snap["shopify"]["failed_total"] == 1
    assert snap["shopify"]["not_found_total"] == 1


def test_license_health():
    h = HealthRegistry()
    h.set_license(LicenseHealth(status="valid", customer="ACME", days_remaining=10))
    snap = h.snapshot()
    assert snap["license"]["status"] == "valid"
    assert snap["license"]["customer"] == "ACME"


def test_overall_degraded_with_mixed_cameras():
    h = HealthRegistry()
    h.register_camera(1, "A")
    h.register_camera(2, "B")
    h.camera_connected(1)
    h.record_frame(1)
    h.camera_disconnected(2)
    snap = h.snapshot()
    assert snap["status"] == "degraded"
