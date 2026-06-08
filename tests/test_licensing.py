"""Lisans doğrulama testleri."""

from datetime import date, timedelta

import pytest

from app.licensing import LicenseError, LicenseManager, LicenseStatus


def test_valid_license(keypair):
    pub_hex, issue = keypair
    key = issue(
        {
            "customer": "ACME",
            "max_cameras": 8,
            "expires_at": (date.today() + timedelta(days=30)).isoformat(),
            "features": ["admin_panel"],
        }
    )
    mgr = LicenseManager(public_key_hex=pub_hex)
    status, lic = mgr.evaluate(key, active_cameras=4)
    assert status == LicenseStatus.VALID
    assert lic.customer == "ACME"
    assert lic.has_feature("admin_panel")
    assert lic.days_remaining() == 30


def test_expired_license(keypair):
    pub_hex, issue = keypair
    key = issue({"customer": "X", "expires_at": (date.today() - timedelta(days=1)).isoformat()})
    status, lic = LicenseManager(pub_hex).evaluate(key, active_cameras=1)
    assert status == LicenseStatus.EXPIRED
    assert lic is not None  # imza geçerli, sadece süresi dolmuş


def test_over_camera_limit(keypair):
    pub_hex, issue = keypair
    key = issue({"customer": "X", "max_cameras": 2})
    status, _ = LicenseManager(pub_hex).evaluate(key, active_cameras=8)
    assert status == LicenseStatus.OVER_LIMIT


def test_tampered_key_is_invalid(keypair):
    pub_hex, issue = keypair
    key = issue({"customer": "X", "max_cameras": 2})
    tampered = key[:-4] + ("AAAA" if not key.endswith("AAAA") else "BBBB")
    status, _ = LicenseManager(pub_hex).evaluate(tampered, active_cameras=1)
    assert status == LicenseStatus.INVALID


def test_wrong_public_key_rejects(keypair):
    _pub_hex, issue = keypair
    key = issue({"customer": "X"})
    other = LicenseManager()  # gömülü farklı public key
    status, _ = other.evaluate(key, active_cameras=1)
    assert status == LicenseStatus.INVALID


def test_missing_key():
    status, lic = LicenseManager().evaluate("", active_cameras=1)
    assert status == LicenseStatus.MISSING
    assert lic is None


def test_verify_raises_on_garbage():
    with pytest.raises(LicenseError):
        LicenseManager().verify("not-a-valid-key")


def test_unlimited_license_never_expires(keypair):
    pub_hex, issue = keypair
    key = issue({"customer": "X", "expires_at": None, "max_cameras": None})
    status, lic = LicenseManager(pub_hex).evaluate(key, active_cameras=999)
    assert status == LicenseStatus.VALID
    assert lic.days_remaining() is None
