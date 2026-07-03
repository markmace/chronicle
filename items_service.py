"""Shared item business logic — the one place create/list/update/complete/delete
live, so the MCP tools, the HTML view routes, and the JSON API all do the same
thing instead of each re-implementing their own mutator closures."""

import models
import storage


def summary(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "tags": item["tags"],
        "start": item["start"],
        "end": item["end"],
        "completed_at": item["completed_at"],
        "kind": models.item_kind(item),
    }


async def create(
    title: str,
    content: str = "",
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """May raise models.ValidationError."""
    item = models.new_item(title, content, tags, start, end)

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        return items + [item], item

    return await storage.mutate(_mutator, message=f"Create item: {item['title']}")


async def list_items(
    tag: str | None = None,
    start_after: str | None = None,
    start_before: str | None = None,
    include_completed: bool = False,
) -> list[dict]:
    """May raise models.ValidationError (bad start_after/start_before)."""
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
    return items


async def get(item_id: str) -> dict:
    """May raise models.ItemNotFoundError."""
    items, _ = await storage.read_items()
    return models.find(items, item_id)


async def update(
    item_id: str,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    clear_start: bool = False,
    clear_end: bool = False,
) -> dict:
    """May raise models.ItemNotFoundError or models.ValidationError."""

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, item_id)
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

    return await storage.mutate(_mutator, message=f"Update item {item_id}")


async def _set_completed(item_id: str, completed_at: str | None) -> tuple[dict, bool]:
    """Returns (item, already_in_that_state). May raise models.ItemNotFoundError."""
    items, _ = await storage.read_items()
    item = models.find(items, item_id)
    already = bool(item.get("completed_at")) == bool(completed_at)
    if already:
        return item, True

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, item_id)
        idx = items.index(item)
        updated = dict(item)
        updated["completed_at"] = completed_at
        updated["updated_at"] = models.now_iso()
        new_items = list(items)
        new_items[idx] = updated
        return new_items, updated

    message = f"Complete item {item_id}" if completed_at else f"Uncomplete item {item_id}"
    result = await storage.mutate(_mutator, message=message)
    return result, False


async def complete(item_id: str) -> tuple[dict, bool]:
    """Returns (item, already_completed). May raise models.ItemNotFoundError."""
    return await _set_completed(item_id, models.now_iso())


async def uncomplete(item_id: str) -> tuple[dict, bool]:
    """Returns (item, already_uncompleted). May raise models.ItemNotFoundError."""
    return await _set_completed(item_id, None)


async def delete(item_id: str) -> dict:
    """Returns the deleted item. May raise models.ItemNotFoundError."""

    def _mutator(items: list[dict]) -> tuple[list[dict], dict]:
        item = models.find(items, item_id)
        return [i for i in items if i["id"] != item_id], item

    return await storage.mutate(_mutator, message=f"Delete item {item_id}")


async def reorder_note(item_id: str, direction: str) -> None:
    """Move a note up or down among other active notes by swapping `order` with
    its neighbor in that direction. A no-op at either end of the list rather than
    an error. May raise models.ItemNotFoundError."""

    def _mutator(items: list[dict]) -> tuple[list[dict], None]:
        item = models.find(items, item_id)
        notes = [
            i for i in items
            if not i.get("completed_at") and models.item_kind(i) == "note"
        ]
        notes.sort(key=models.sort_order, reverse=True)
        idx = next(i for i, n in enumerate(notes) if n["id"] == item_id)
        neighbor_idx = idx - 1 if direction == "up" else idx + 1
        if neighbor_idx < 0 or neighbor_idx >= len(notes):
            return items, None

        neighbor = notes[neighbor_idx]
        item_order = models.sort_order(item)
        neighbor_order = models.sort_order(neighbor)
        new_items = []
        for i in items:
            if i["id"] == item["id"]:
                new_items.append({**i, "order": neighbor_order})
            elif i["id"] == neighbor["id"]:
                new_items.append({**i, "order": item_order})
            else:
                new_items.append(i)
        return new_items, None

    await storage.mutate(_mutator, message=f"Reorder note {item_id} ({direction})")
