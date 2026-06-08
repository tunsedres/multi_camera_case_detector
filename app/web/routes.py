"""
Admin Panel route'ları.

  ui_router      → HTML sayfalar + yönetim (kimlik doğrulamalı)
  public_router  → /health (kimlik doğrulamasız; Docker healthcheck/izleme)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.config import CameraConfig
from app.web.context import AppContext
from app.web.security import (
    COOKIE_NAME,
    SESSION_TTL_SECONDS,
    check_credentials,
    make_session_cookie,
)

# Auth, app seviyesindeki middleware ile yapılır (bkz. security.auth_middleware).
# ui_router HTML sayfalar; public_router /health (+ /login burada, muaf yol).
ui_router = APIRouter()
public_router = APIRouter()

PAGE_SIZE = 50
STATUS_OPTIONS = ["pending", "success", "failed", "not_found"]


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


def _templates(request: Request):
    return request.app.state.templates


# --------------------------------------------------------------------------- #
#  Dashboard
# --------------------------------------------------------------------------- #
@ui_router.get("/")
def dashboard(request: Request):
    ctx = _ctx(request)
    return _templates(request).TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": ctx.db.stats(),
            "health": ctx.health.snapshot(),
            "recent": ctx.db.search_events(limit=10),
            "version": ctx.version,
        },
    )


# --------------------------------------------------------------------------- #
#  Event listesi (arama + filtre + sayfalama)
# --------------------------------------------------------------------------- #
@ui_router.get("/events")
def events(
    request: Request,
    order_no: str | None = Query(default=None),
    camera_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
):
    ctx = _ctx(request)
    status = status or None
    filters = {
        "order_no": order_no or None,
        "camera_id": camera_id,
        "status": status,
        "date_from": date_from or None,
        "date_to": date_to or None,
    }
    total = ctx.db.count_events(**filters)
    rows = ctx.db.search_events(**filters, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)

    return _templates(request).TemplateResponse(
        "events.html",
        {
            "request": request,
            "events": rows,
            "total": total,
            "page": page,
            "pages": pages,
            "filters": filters,
            "cameras": ctx.db.list_cameras(),
            "status_options": STATUS_OPTIONS,
            "version": ctx.version,
        },
    )


@ui_router.get("/events/{event_id}")
def event_detail(request: Request, event_id: int):
    ctx = _ctx(request)
    event = ctx.db.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    return _templates(request).TemplateResponse(
        "event_detail.html",
        {"request": request, "event": event, "version": ctx.version},
    )


@ui_router.get("/events/{event_id}/snapshot")
def event_snapshot(request: Request, event_id: int):
    ctx = _ctx(request)
    event = ctx.db.get_event(event_id)
    if not event or not event.get("snapshot_path"):
        raise HTTPException(status_code=404, detail="Snapshot yok")

    path = Path(event["snapshot_path"]).resolve()
    base = ctx.snapshots.base_dir.resolve()
    # Path traversal koruması: dosya snapshot dizininin altında olmalı
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot bulunamadı")
    return FileResponse(path, media_type="image/jpeg")


@ui_router.post("/events/{event_id}/retry")
def event_retry(request: Request, event_id: int):
    ctx = _ctx(request)
    if not ctx.db.requeue_event(event_id):
        raise HTTPException(status_code=404, detail="Event bulunamadı")
    return RedirectResponse(url=f"/events/{event_id}", status_code=303)


@ui_router.get("/api/stats")
def api_stats(request: Request):
    return JSONResponse(_ctx(request).db.stats())


# --------------------------------------------------------------------------- #
#  Kamera ayarları (panelden SQLite yönetimi)
#
#  Kameralar DB'de tutulur. Worker'lar boot'ta kurulduğu için değişiklikler
#  yeniden başlatmada etkin olur; kaydedince mark_restart_needed() banner gösterir.
#  RTSP {user}/{pass} ham şablon saklanır; sır DB'ye yazılmaz (.env'den doldurulur).
# --------------------------------------------------------------------------- #
def _render_cameras(request: Request, *, error: str | None = None, form: dict | None = None):
    ctx = _ctx(request)
    return _templates(request).TemplateResponse(
        "cameras.html",
        {
            "request": request,
            "cameras": ctx.db.list_cameras(),
            "restart_needed": ctx.restart_needed,
            "error": error,
            "form": form or {},
            "next_id": ctx.db.next_camera_id(),
            "version": ctx.version,
        },
    )


@ui_router.get("/settings/cameras")
def cameras_page(request: Request):
    return _render_cameras(request)


@ui_router.post("/settings/cameras/save")
def cameras_save(
    request: Request,
    camera_id: int = Form(...),
    name: str = Form(...),
    rtsp: str = Form(...),
    enabled: str | None = Form(default=None),
    original_id: str = Form(default=""),
):
    """Kamera ekle (original_id boş) veya güncelle (original_id mevcut kamerayı işaret eder)."""
    ctx = _ctx(request)
    is_enabled = bool(enabled)
    form = {"camera_id": camera_id, "name": name, "rtsp": rtsp, "enabled": is_enabled}
    # Boş string = yeni kayıt; dolu = düzenlenen kameranın eski id'si.
    orig_id = int(original_id) if original_id.strip() else None

    # Alan doğrulaması (id>=1, boş isim vb.) için CameraConfig'i kullan.
    try:
        cam = CameraConfig(id=camera_id, name=name.strip(), rtsp=rtsp.strip(), enabled=is_enabled)
    except ValidationError as e:
        return _render_cameras(request, error=_first_error(e), form=form)

    try:
        if orig_id is None:
            ctx.db.add_camera(cam.id, cam.name, cam.rtsp, cam.enabled)
        else:
            found = ctx.db.update_camera(orig_id, cam.id, cam.name, cam.rtsp, cam.enabled)
            if not found:
                raise HTTPException(status_code=404, detail="Kamera bulunamadı")
    except sqlite3.IntegrityError:
        return _render_cameras(request, error=f"Kamera id {cam.id} zaten kullanımda.", form=form)

    ctx.mark_restart_needed()
    return RedirectResponse(url="/settings/cameras", status_code=303)


@ui_router.post("/settings/cameras/{cam_id}/delete")
def cameras_delete(request: Request, cam_id: int):
    ctx = _ctx(request)
    if not ctx.db.delete_camera(cam_id):
        raise HTTPException(status_code=404, detail="Kamera bulunamadı")
    ctx.mark_restart_needed()
    return RedirectResponse(url="/settings/cameras", status_code=303)


@ui_router.post("/settings/cameras/{cam_id}/toggle")
def cameras_toggle(request: Request, cam_id: int):
    """enabled bayrağını çevir (hızlı aç/kapat)."""
    ctx = _ctx(request)
    if not ctx.db.toggle_camera(cam_id):
        raise HTTPException(status_code=404, detail="Kamera bulunamadı")
    ctx.mark_restart_needed()
    return RedirectResponse(url="/settings/cameras", status_code=303)


@ui_router.post("/settings/restart")
def restart_system(request: Request):
    """
    Sistemi yeniden başlatır: süreç SIGTERM ile çıkar, Docker
    (restart: unless-stopped) ~2-3 sn içinde tekrar başlatır. Önce 'yeniden
    başlatılıyor' bilgi sayfası gösterilir (sayfa kendini birkaç sn sonra
    /settings/cameras'a yönlendirir).
    """
    ctx = _ctx(request)
    ctx.request_restart()
    return _templates(request).TemplateResponse(
        "restarting.html",
        {"request": request, "version": ctx.version},
    )


def _first_error(exc: Exception) -> str:
    """ValidationError'dan kullanıcıya gösterilecek ilk mesajı çıkar."""
    if isinstance(exc, ValidationError):
        errs = exc.errors()
        if errs:
            loc = ".".join(str(p) for p in errs[0].get("loc", ()))
            return f"{loc}: {errs[0].get('msg', 'geçersiz değer')}"
    return str(exc)


# --------------------------------------------------------------------------- #
#  Giriş / çıkış (session tabanlı)
# --------------------------------------------------------------------------- #
@public_router.get("/login")
def login_page(request: Request):
    ctx = _ctx(request)
    # Auth kapalıysa ya da zaten girişliyse panele gönder.
    if not ctx.settings.auth_enabled:
        return RedirectResponse(url="/", status_code=303)
    return _templates(request).TemplateResponse(
        "login.html", {"request": request, "version": ctx.version, "error": None}
    )


@public_router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    ctx = _ctx(request)
    if not check_credentials(username, password, ctx.settings):
        return _templates(request).TemplateResponse(
            "login.html",
            {
                "request": request,
                "version": ctx.version,
                "error": "Kullanıcı adı veya şifre hatalı.",
            },
            status_code=401,
        )
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        make_session_cookie(username, ctx.session_secret),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return resp


@ui_router.post("/logout")
def logout(request: Request):
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# --------------------------------------------------------------------------- #
#  Public health (kimlik doğrulamasız)
# --------------------------------------------------------------------------- #
@public_router.get("/health")
def health(request: Request):
    snap = _ctx(request).health.snapshot()
    code = 200 if snap["status"] != "down" else 503
    return JSONResponse(snap, status_code=code)
