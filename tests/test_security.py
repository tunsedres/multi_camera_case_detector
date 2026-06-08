"""Session cookie imzalama/doğrulama (HMAC) birim testleri."""

from __future__ import annotations

import time

from app.web import security as sec
from app.web.security import (
    check_credentials,
    make_session_cookie,
    verify_session_cookie,
)


class _S:
    admin_username = "admin"
    admin_password = "secret"


def test_valid_cookie_roundtrip():
    cookie = make_session_cookie("admin", "topsecret")
    assert verify_session_cookie(cookie, "topsecret") is True


def test_wrong_secret_fails():
    cookie = make_session_cookie("admin", "topsecret")
    assert verify_session_cookie(cookie, "baska") is False


def test_tampered_payload_fails():
    cookie = make_session_cookie("admin", "topsecret")
    payload, sig = cookie.split(".", 1)
    forged = sec._b64e(b'{"u":"hacker","iat":9999999999}')
    assert verify_session_cookie(f"{forged}.{sig}", "topsecret") is False


def test_malformed_cookie_fails():
    assert verify_session_cookie("garbage", "topsecret") is False
    assert verify_session_cookie("a.b.c", "topsecret") is False
    assert verify_session_cookie("", "topsecret") is False


def test_expired_cookie_fails(monkeypatch):
    cookie = make_session_cookie("admin", "topsecret")
    # TTL'den ileri sar (gerçek zamanı önce yakala ki patch'li time.time özyinelemesin)
    future = time.time() + sec.SESSION_TTL_SECONDS + 10
    monkeypatch.setattr(sec.time, "time", lambda: future)
    assert verify_session_cookie(cookie, "topsecret") is False


def test_check_credentials():
    assert check_credentials("admin", "secret", _S) is True
    assert check_credentials("admin", "wrong", _S) is False
    assert check_credentials("root", "secret", _S) is False
