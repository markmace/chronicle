"""MCP tools for creating, listing, and mutating Chronicle items."""

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

import items_service
import models

mcp = FastMCP(
    "Chronicle",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def create_item(
    title: str,
    content: str = "",
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> str:
    """
    Create a note, reminder, or event — which one it becomes is purely a function of
    which time fields you set:
    - note: neither start nor end
    - reminder: start set (or unset, for an "anytime" todo), end unset
    - event: both start and end set

    Dates are ISO 8601, e.g. "2026-07-05T15:00:00Z". Returns {"ok": true, "item": {...}}
    or {"ok": false, "error": ...} on invalid input.
    """
    try:
        item = await items_service.create(title, content, tags, start, end)
    except models.ValidationError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": item})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def list_items(
    tag: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_completed: bool = False,
) -> str:
    """
    List item SUMMARIES (id, title, tags, start, end, completed_at, derived kind —
    no content; use get_item for the full item). Sorted by start ascending, undated
    items last.

    - tag: case-insensitive exact tag match.
    - start_after / start_before: ISO 8601 bounds on `start`. Giving either excludes
      undated items.
    - include_completed: False (default) hides items with completed_at set.
    """
    try:
        items = await items_service.list_items(tag, start_after, start_before, include_completed)
    except models.ValidationError as e:
        return json.dumps({"ok": False, "error": str(e)})
    summaries = [items_service.summary(i) for i in items]
    return json.dumps({"items": summaries, "count": len(summaries)})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_item(id: str) -> str:
    """Full item including content, plus derived `kind`. Error if no item has this id."""
    try:
        item = await items_service.get(id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": {**item, "kind": models.item_kind(item)}})


@mcp.tool()
async def update_item(
    id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    clear_start: bool = False,
    clear_end: bool = False,
) -> str:
    """
    Partial patch — only the fields you pass change. tags=[] clears all tags
    (tags=None leaves them unchanged). To REMOVE start/end entirely (e.g. turning an
    event into an undated reminder), use clear_start/clear_end — passing nothing
    leaves them as-is. Call get_item() first if you're unsure what's currently set.
    """
    try:
        result = await items_service.update(
            id, title=title, content=content, tags=tags,
            start=start, end=end, clear_start=clear_start, clear_end=clear_end,
        )
    except (models.ItemNotFoundError, models.ValidationError) as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": result})


@mcp.tool()
async def complete_item(id: str) -> str:
    """Sets completed_at=now. Idempotent — safe to call on an already-completed item."""
    try:
        item, already = await items_service.complete(id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": item, "already_completed": already})


@mcp.tool()
async def uncomplete_item(id: str) -> str:
    """Clears completed_at. Idempotent, symmetric to complete_item."""
    try:
        item, already = await items_service.uncomplete(id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": item, "already_uncompleted": already})


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def delete_item(id: str) -> str:
    """
    DESTRUCTIVE: permanently deletes an item.

    ALWAYS confirm with the user in plain language before calling this tool — show
    them the title and wait for explicit confirmation ("yes", "delete it", etc.).
    Never delete based on inference alone.

    Recoverable via the chronicle-data repo's git history, but don't rely on that.
    """
    try:
        deleted = await items_service.delete(id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "id": id, "title": deleted["title"]})
