"""Chronicle — a unified notes/reminders/events store, accessible to Claude via MCP."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import items_service
import models
from auth import safe_equal, session_token
from mcp_server import mcp

MCP_TOKEN = os.environ["MCP_TOKEN"]
VIEW_PASSWORD = os.environ["VIEW_PASSWORD"]
SESSION_COOKIE = "chronicle_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 400  # ~400 days — Chrome's cookie Max-Age cap

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class MCPTokenMiddleware:
    """
    Validates the token in the URL path, handles CORS, and forwards to FastMCP.
    Strips the Origin header so FastMCP's DNS-rebinding check doesn't fire.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")
        MCP_PREFIX = "/mcp/"
        token = path[len(MCP_PREFIX):].split("/")[0] if path.startswith(MCP_PREFIX) else ""

        origin: bytes | None = None
        clean_headers = []
        for k, v in scope.get("headers", []):
            if k.lower() == b"origin":
                origin = v
            else:
                clean_headers.append((k, v))

        if scope.get("method") == "OPTIONS":
            await send({"type": "http.response.start", "status": 204,
                        "headers": self._cors_headers(origin)})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        if not safe_equal(token, MCP_TOKEN):
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            await send({"type": "http.response.body", "body": b"Unauthorized", "more_body": False})
            return

        new_scope = {
            **scope,
            "path": "/mcp",
            "raw_path": b"/mcp",
            "root_path": "",
            "headers": clean_headers,
        }

        cors = self._cors_headers(origin)

        async def cors_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + cors}
            await send(message)

        await self.app(new_scope, receive, cors_send)

    @staticmethod
    def _cors_headers(origin: bytes | None) -> list:
        return [
            (b"access-control-allow-origin", origin or b"*"),
            (b"access-control-allow-methods", b"GET, POST, PATCH, DELETE, OPTIONS"),
            (b"access-control-allow-headers", b"content-type, mcp-session-id, accept"),
            (b"access-control-allow-credentials", b"true"),
        ]


mcp_asgi = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp_asgi.router.lifespan_context(mcp_asgi):
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/mcp", MCPTokenMiddleware(mcp_asgi))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")))


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def _require_token(token: str) -> None:
    """Pure token auth, no cookie shortcut — used by the JSON API and MCP, which
    are meant for programmatic clients, not a browser session."""
    if not safe_equal(token, MCP_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _has_valid_session(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    return safe_equal(cookie, session_token(VIEW_PASSWORD))


def _require_view_access(request: Request, token: str) -> None:
    """Valid via either the URL path token (old bookmarks, MCP-adjacent links) or
    a logged-in session cookie (the friendly bare-domain + password flow)."""
    if safe_equal(token, MCP_TOKEN) or _has_valid_session(request):
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/")
async def root(request: Request):
    if _has_valid_session(request):
        return RedirectResponse(f"/view/{MCP_TOKEN}", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str | None = None):
    if _has_valid_session(request):
        return RedirectResponse(f"/view/{MCP_TOKEN}", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if not safe_equal(password, VIEW_PASSWORD):
        return RedirectResponse("/login?error=Wrong+password", status_code=303)
    response = RedirectResponse(f"/view/{MCP_TOKEN}", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, session_token(VIEW_PASSWORD),
        max_age=SESSION_MAX_AGE, httponly=True, secure=True, samesite="lax",
    )
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Mobile-first HTML view: quick-add, complete/uncomplete, delete, and edit.
# ---------------------------------------------------------------------------

def _fmt(iso: str | None) -> str | None:
    if not iso:
        return None
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%b %-d, %-I:%M %p")


def _for_display(item: dict) -> dict:
    return {
        **item,
        "kind": models.item_kind(item),
        "display_start": _fmt(item.get("start")),
        "display_end": _fmt(item.get("end")),
        "display_completed": _fmt(item.get("completed_at")),
    }


def _local_to_utc_iso(value: str, tz_offset_minutes: int) -> str | None:
    """Convert a <input type=datetime-local> value (naive, in the browser's local
    time) to a UTC ISO string. tz_offset_minutes is JS's Date.getTimezoneOffset()
    — minutes to ADD to local time to reach UTC."""
    if not value:
        return None
    naive = datetime.fromisoformat(value)
    utc = naive + timedelta(minutes=tz_offset_minutes)
    return utc.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/view/{token}", response_class=HTMLResponse)
async def view_items(request: Request, token: str, error: str | None = None):
    """Mobile-first view of all items, with a quick-add form and per-item
    complete/uncomplete/delete/edit actions. Reachable either via the URL path
    token or a logged-in session cookie (see /login)."""
    _require_view_access(request, token)

    items = await items_service.list_items(include_completed=True)

    active = [i for i in items if not i.get("completed_at")]
    completed = [i for i in items if i.get("completed_at")]

    upcoming = [i for i in active if models.item_kind(i) in ("event", "reminder")]
    upcoming.sort(key=lambda i: (i["start"] is None, i["start"] or ""))

    notes = [i for i in active if models.item_kind(i) == "note"]
    notes.sort(key=lambda i: i["created_at"], reverse=True)

    completed.sort(key=lambda i: i["completed_at"], reverse=True)

    return templates.TemplateResponse(
        request,
        "items.html",
        {
            "token": token,
            "error": error,
            "upcoming": [_for_display(i) for i in upcoming],
            "notes": [_for_display(i) for i in notes],
            "completed": [_for_display(i) for i in completed],
        },
    )


@app.post("/view/{token}/create")
async def create_item_form(
    request: Request,
    token: str,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    tz_offset_minutes: int = Form(0),
):
    _require_view_access(request, token)
    try:
        await items_service.create(
            title,
            content=content,
            tags=[t for t in tags.split(",")],
            start=_local_to_utc_iso(start, tz_offset_minutes),
            end=_local_to_utc_iso(end, tz_offset_minutes),
        )
    except models.ValidationError as e:
        return RedirectResponse(f"/view/{token}?error={quote(str(e))}", status_code=303)
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.get("/view/{token}/{item_id}/edit", response_class=HTMLResponse)
async def edit_item_form(request: Request, token: str, item_id: str):
    _require_view_access(request, token)
    try:
        item = await items_service.get(item_id)
    except models.ItemNotFoundError as e:
        return RedirectResponse(f"/view/{token}?error={quote(str(e))}", status_code=303)
    return templates.TemplateResponse(
        request, "edit_item.html", {"token": token, "item": item, "error": None},
    )


@app.post("/view/{token}/{item_id}/edit")
async def update_item_form(
    request: Request,
    token: str,
    item_id: str,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    tz_offset_minutes: int = Form(0),
):
    _require_view_access(request, token)
    new_start = _local_to_utc_iso(start, tz_offset_minutes)
    new_end = _local_to_utc_iso(end, tz_offset_minutes)
    try:
        await items_service.update(
            item_id,
            title=title,
            content=content,
            tags=[t for t in tags.split(",")],
            start=new_start,
            end=new_end,
            clear_start=new_start is None,
            clear_end=new_end is None,
        )
    except models.ItemNotFoundError as e:
        return RedirectResponse(f"/view/{token}?error={quote(str(e))}", status_code=303)
    except models.ValidationError as e:
        return RedirectResponse(
            f"/view/{token}/{item_id}/edit?error={quote(str(e))}", status_code=303
        )
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/complete")
async def complete_item_form(request: Request, token: str, item_id: str):
    _require_view_access(request, token)
    try:
        await items_service.complete(item_id)
    except models.ItemNotFoundError:
        pass
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/uncomplete")
async def uncomplete_item_form(request: Request, token: str, item_id: str):
    _require_view_access(request, token)
    try:
        await items_service.uncomplete(item_id)
    except models.ItemNotFoundError:
        pass
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/delete")
async def delete_item_form(request: Request, token: str, item_id: str):
    _require_view_access(request, token)
    try:
        await items_service.delete(item_id)
    except models.ItemNotFoundError:
        pass
    return RedirectResponse(f"/view/{token}", status_code=303)


# ---------------------------------------------------------------------------
# JSON REST API — same operations as the MCP tools, for future clients (a
# richer web app, an iOS/Mac app) that want JSON instead of form-encoded POSTs.
# ---------------------------------------------------------------------------

class CreateItemBody(BaseModel):
    title: str
    content: str = ""
    tags: list[str] = []
    start: str | None = None
    end: str | None = None


class UpdateItemBody(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    start: str | None = None
    end: str | None = None
    clear_start: bool = False
    clear_end: bool = False


@app.get("/api/{token}/items")
async def api_list_items(
    token: str,
    tag: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_completed: bool = False,
):
    _require_token(token)
    try:
        items = await items_service.list_items(tag, start_after, start_before, include_completed)
    except models.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"items": [items_service.summary(i) for i in items], "count": len(items)}


@app.post("/api/{token}/items", status_code=201)
async def api_create_item(token: str, body: CreateItemBody):
    _require_token(token)
    try:
        item = await items_service.create(body.title, body.content, body.tags, body.start, body.end)
    except models.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return item


@app.get("/api/{token}/items/{item_id}")
async def api_get_item(token: str, item_id: str):
    _require_token(token)
    try:
        item = await items_service.get(item_id)
    except models.ItemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {**item, "kind": models.item_kind(item)}


@app.patch("/api/{token}/items/{item_id}")
async def api_update_item(token: str, item_id: str, body: UpdateItemBody):
    _require_token(token)
    try:
        return await items_service.update(
            item_id,
            title=body.title, content=body.content, tags=body.tags,
            start=body.start, end=body.end,
            clear_start=body.clear_start, clear_end=body.clear_end,
        )
    except models.ItemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except models.ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/api/{token}/items/{item_id}/complete")
async def api_complete_item(token: str, item_id: str):
    _require_token(token)
    try:
        item, already = await items_service.complete(item_id)
    except models.ItemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"item": item, "already_completed": already}


@app.post("/api/{token}/items/{item_id}/uncomplete")
async def api_uncomplete_item(token: str, item_id: str):
    _require_token(token)
    try:
        item, already = await items_service.uncomplete(item_id)
    except models.ItemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"item": item, "already_uncompleted": already}


@app.delete("/api/{token}/items/{item_id}")
async def api_delete_item(token: str, item_id: str):
    _require_token(token)
    try:
        deleted = await items_service.delete(item_id)
    except models.ItemNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "id": item_id, "title": deleted["title"]}
