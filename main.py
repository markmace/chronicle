"""Chronicle — a unified notes/reminders/events store, accessible to Claude via MCP."""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
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


@app.get("/view/{token}", response_class=HTMLResponse)
async def view_items(request: Request, token: str):
    """Read-only mobile-first view of all items. Same trust boundary as /mcp — the
    URL path token — so there's no separate credential to manage."""
    if not safe_equal(token, MCP_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

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
            "upcoming": [_for_display(i) for i in upcoming],
            "notes": [_for_display(i) for i in notes],
            "completed": [_for_display(i) for i in completed],
        },
    )
