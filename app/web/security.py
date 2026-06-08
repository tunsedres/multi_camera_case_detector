"""
Admin Panel kimlik doğrulama (HTTP Basic).

ADMIN_PASSWORD tanımlıysa devreye girer; boşsa panel açık kalır (sadece güvenli
LAN için önerilir). /health endpoint'i bu korumadan muaftır (Docker healthcheck).
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic(auto_error=False)


def require_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    settings = request.app.state.context.settings
    if not settings.auth_enabled:
        return  # parola tanımlı değil → koruma kapalı

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Yetkisiz",
        headers={"WWW-Authenticate": "Basic"},
    )
    if credentials is None:
        raise unauthorized

    user_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    pass_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (user_ok and pass_ok):
        raise unauthorized
