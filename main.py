"""Chronicle — a unified notes/reminders/events store, accessible to Claude via MCP."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import models
import storage
from auth import safe_equal
from mcp_server import mcp

MCP_TOKEN = os.environ["MCP_TOKEN"]

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
            (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
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


@app.get("/healthz")
async def healthz():
    return {"ok": True}


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


def _require_token(token: str) -> None:
    if not safe_equal(token, MCP_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


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
    complete/uncomplete/delete actions. Same trust boundary as /mcp — the URL path
    token — so there's no separate credential to manage."""
    _require_token(token)

    items, _ = await storage.read_items()

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
    token: str,
    title: str = Form(...),
    content: str = Form(""),
    tags: str = Form(""),
    start: str = Form(""),
    end: str = Form(""),
    tz_offset_minutes: int = Form(0),
):
    _require_token(token)

    try:
        item = models.new_item(
            title,
            content=content,
            tags=[t for t in tags.split(",")],
            start=_local_to_utc_iso(start, tz_offset_minutes),
            end=_local_to_utc_iso(end, tz_offset_minutes),
        )
    except models.ValidationError as e:
        return RedirectResponse(f"/view/{token}?error={quote(str(e))}", status_code=303)

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        return items + [item], item

    await storage.mutate(_mutator, message=f"Create item: {item['title']}")
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/complete")
async def complete_item_form(token: str, item_id: str):
    _require_token(token)

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, item_id)
        idx = items.index(item)
        completed = dict(item)
        completed["completed_at"] = models.now_iso()
        new_items = list(items)
        new_items[idx] = completed
        return new_items, completed

    try:
        await storage.mutate(_mutator, message=f"Complete item {item_id}")
    except models.ItemNotFoundError:
        pass
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/uncomplete")
async def uncomplete_item_form(token: str, item_id: str):
    _require_token(token)

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, item_id)
        idx = items.index(item)
        uncompleted = dict(item)
        uncompleted["completed_at"] = None
        new_items = list(items)
        new_items[idx] = uncompleted
        return new_items, uncompleted

    try:
        await storage.mutate(_mutator, message=f"Uncomplete item {item_id}")
    except models.ItemNotFoundError:
        pass
    return RedirectResponse(f"/view/{token}", status_code=303)


@app.post("/view/{token}/{item_id}/delete")
async def delete_item_form(token: str, item_id: str):
    _require_token(token)

    def _mutator(items: list[dict]) -> tuple[list[dict], dict | None]:
        remaining = [i for i in items if i["id"] != item_id]
        return remaining, None

    await storage.mutate(_mutator, message=f"Delete item {item_id}")
    return RedirectResponse(f"/view/{token}", status_code=303)
