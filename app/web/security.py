"""
Admin Panel kimlik doğrulama — session cookie tabanlı (imzalı, HMAC).

ADMIN_PASSWORD tanımlıysa koruma devreye girer; boşsa panel açık kalır (yalnızca
güvenli LAN için). Kullanıcı /login formundan giriş yapar, başarılıysa imzalı bir
session cookie set edilir. /health ve /login bu korumadan muaftır.

Cookie içeriği: "<payload_b64>.<hmac_b64>" — payload imzalandığı için kullanıcı
değiştiremez (yeni bağımlılık yok, stdlib hmac yeterli). Lokal sistem + tek admin
senaryosuna uygun, hafif bir çözüm.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Request, status
from fastapi.responses import RedirectResponse

COOKIE_NAME = "packing_session"
# Oturum süresi (saniye). Bu süre sonunda cookie geçersiz sayılır → tekrar login.
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 gün

# Korumadan muaf yollar (auth gerektirmez).
_PUBLIC_PATHS = frozenset({"/login", "/health"})


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_session_cookie(username: str, secret: str) -> str:
    """username + issued-at içeren imzalı cookie değeri üretir."""
    payload = {"u": username, "iat": int(time.time())}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64e(sig)}"


def verify_session_cookie(cookie: str, secret: str) -> bool:
    """Cookie imzasını ve süresini doğrular. Geçerliyse True."""
    try:
        payload_b64, sig_b64 = cookie.split(".", 1)
    except ValueError:
        return False

    expected = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    try:
        given = _b64d(sig_b64)
    except (ValueError, base64.binascii.Error):
        return False
    if not hmac.compare_digest(expected, given):
        return False

    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, base64.binascii.Error):
        return False

    iat = payload.get("iat", 0)
    return (time.time() - iat) <= SESSION_TTL_SECONDS


def check_credentials(username: str, password: str, settings) -> bool:
    """Sabit zamanlı kullanıcı adı/şifre karşılaştırması."""
    user_ok = secrets.compare_digest(username, settings.admin_username)
    pass_ok = secrets.compare_digest(password, settings.admin_password)
    return user_ok and pass_ok


def is_authenticated(request: Request) -> bool:
    """İstek geçerli bir session cookie taşıyor mu?"""
    ctx = request.app.state.context
    if not ctx.settings.auth_enabled:
        return True  # parola tanımlı değil → koruma kapalı
    cookie = request.cookies.get(COOKIE_NAME)
    return bool(cookie) and verify_session_cookie(cookie, ctx.session_secret)


async def auth_middleware(request: Request, call_next):
    """
    Tüm istekleri korur: kimliksizse /login'e yönlendirir. Statik dosyalar ve
    public yollar (/login, /health) muaftır.
    """
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/static/") or is_authenticated(request):
        return await call_next(request)

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
