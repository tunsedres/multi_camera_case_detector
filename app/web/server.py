"""
FastAPI uygulama fabrikası.

create_app(context) → orchestrator tarafından çağrılır, uvicorn ile servis edilir.
Şablonlar Jinja2, statik dosyalar lokal (CDN yok → internetsiz depoda da çalışır).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.web.context import AppContext
from app.web.routes import public_router, ui_router
from app.web.security import auth_middleware

_DIR = Path(__file__).resolve().parent
_TEMPLATES = _DIR / "templates"
_STATIC = _DIR / "static"

_STATUS_TR = {
    "pending": "Bekliyor",
    "success": "Yazıldı",
    "failed": "Hata",
    "not_found": "Sipariş yok",
}
_STATUS_CSS = {
    "pending": "badge-pending",
    "success": "badge-success",
    "failed": "badge-failed",
    "not_found": "badge-notfound",
    "ok": "badge-success",
    "stale": "badge-pending",
    "down": "badge-failed",
    "degraded": "badge-pending",
}


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y %H:%M:%S")


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="Packing Detector — Admin Panel", docs_url=None, redoc_url=None)
    app.state.context = context

    templates = Jinja2Templates(directory=str(_TEMPLATES))
    templates.env.filters["dt"] = _fmt_dt
    templates.env.filters["status_tr"] = lambda s: _STATUS_TR.get(s, s)
    templates.env.filters["status_css"] = lambda s: _STATUS_CSS.get(s, "badge-pending")
    app.state.templates = templates

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    # Kimlik doğrulama: /login + /health + /static hariç tüm istekleri korur.
    app.add_middleware(BaseHTTPMiddleware, dispatch=auth_middleware)

    app.include_router(public_router)
    app.include_router(ui_router)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ANN001
        return HTMLResponse(
            templates.get_template("404.html").render(request=request),
            status_code=404,
        )

    return app
