"""MCP tools for creating, listing, and mutating Chronicle items."""

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

import models
import storage

mcp = FastMCP(
    "Chronicle",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _summary(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "tags": item["tags"],
        "start": item["start"],
        "end": item["end"],
        "completed_at": item["completed_at"],
        "kind": models.item_kind(item),
    }


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
        item = models.new_item(title, content, tags, start, end)
    except models.ValidationError as e:
        return json.dumps({"ok": False, "error": str(e)})

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        return items + [item], item

    result = await storage.mutate(_mutator, message=f"Create item: {item['title']}")
    return json.dumps({"ok": True, "item": result})


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
    items, _ = await storage.read_items()

    if tag:
        tag = tag.strip().lower()
        items = [i for i in items if tag in i["tags"]]

    if not include_completed:
        items = [i for i in items if not i.get("completed_at")]

    if start_after or start_before:
        after_dt = models.parse_dt(start_after) if start_after else None
        before_dt = models.parse_dt(start_before) if start_before else None
        filtered = []
        for i in items:
            if not i.get("start"):
                continue
            start_dt = models.parse_dt(i["start"])
            if after_dt and start_dt < after_dt:
                continue
            if before_dt and start_dt > before_dt:
                continue
            filtered.append(i)
        items = filtered

    items.sort(key=lambda i: (i["start"] is None, i["start"] or ""))

    summaries = [_summary(i) for i in items]
    return json.dumps({"items": summaries, "count": len(summaries)})


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def get_item(id: str) -> str:
    """Full item including content, plus derived `kind`. Error if no item has this id."""
    items, _ = await storage.read_items()
    try:
        item = models.find(items, id)
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
        def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
            item = models.find(items, id)
            idx = items.index(item)
            patched = models.apply_patch(
                item,
                title=title,
                content=content,
                tags=tags,
                start=start,
                end=end,
                clear_start=clear_start,
                clear_end=clear_end,
            )
            new_items = list(items)
            new_items[idx] = patched
            return new_items, patched

        result = await storage.mutate(_mutator, message=f"Update item {id}")
    except (models.ItemNotFoundError, models.ValidationError) as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "item": result})


@mcp.tool()
async def complete_item(id: str) -> str:
    """Sets completed_at=now. Idempotent — safe to call on an already-completed item."""
    items, _ = await storage.read_items()
    try:
        item = models.find(items, id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if item.get("completed_at"):
        return json.dumps({"ok": True, "item": item, "already_completed": True})

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, id)
        idx = items.index(item)
        completed = dict(item)
        completed["completed_at"] = models.now_iso()
        completed["updated_at"] = completed["completed_at"]
        new_items = list(items)
        new_items[idx] = completed
        return new_items, completed

    result = await storage.mutate(_mutator, message=f"Complete item {id}")
    return json.dumps({"ok": True, "item": result, "already_completed": False})


@mcp.tool()
async def uncomplete_item(id: str) -> str:
    """Clears completed_at. Idempotent, symmetric to complete_item."""
    items, _ = await storage.read_items()
    try:
        item = models.find(items, id)
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    if not item.get("completed_at"):
        return json.dumps({"ok": True, "item": item, "already_uncompleted": True})

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, id)
        idx = items.index(item)
        uncompleted = dict(item)
        uncompleted["completed_at"] = None
        uncompleted["updated_at"] = models.now_iso()
        new_items = list(items)
        new_items[idx] = uncompleted
        return new_items, uncompleted

    result = await storage.mutate(_mutator, message=f"Uncomplete item {id}")
    return json.dumps({"ok": True, "item": result, "already_uncompleted": False})


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
        def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
            item = models.find(items, id)
            return [i for i in items if i["id"] != id], item

        deleted = await storage.mutate(_mutator, message=f"Delete item {id}")
    except models.ItemNotFoundError as e:
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "id": id, "title": deleted["title"]})
