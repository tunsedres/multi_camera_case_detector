"""
Admin Panel route'ları.

  ui_router      → HTML sayfalar + yönetim (kimlik doğrulamalı)
  public_router  → /health (kimlik doğrulamasız; Docker healthcheck/izleme)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.web.context import AppContext
from app.web.security import require_auth

ui_router = APIRouter(dependencies=[Depends(require_auth)])
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
            "cameras": ctx.config.cameras,
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
#  Public health (kimlik doğrulamasız)
# --------------------------------------------------------------------------- #
@public_router.get("/health")
def health(request: Request):
    snap = _ctx(request).health.snapshot()
    code = 200 if snap["status"] != "down" else 503
    return JSONResponse(snap, status_code=code)
