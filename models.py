"""Item schema, validation, and derived properties.

An item is a plain dict. Temporal shape (event / reminder / note) is never stored —
it's derived from which of `start`/`end`/`completed_at` are set. See item_kind().
"""

import uuid
from datetime import datetime, timezone


class ValidationError(Exception):
    """Item fields failed validation — safe to surface to the caller as a message."""


class ItemNotFoundError(Exception):
    """No item with the given id."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return uuid.uuid4().hex


def parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 datetime, accepting a trailing 'Z'."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(
            f"'{value}' isn't a valid ISO 8601 datetime (e.g. '2026-07-05T15:00:00Z')."
        )


def normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    seen = []
    for t in tags:
        t = t.strip().lower()
        if t and t not in seen:
            seen.append(t)
    return seen


def validate_temporal(start: str | None, end: str | None) -> None:
    if end and not start:
        raise ValidationError("An item with an end time must also have a start time.")
    if start:
        parse_dt(start)
    if end:
        end_dt = parse_dt(end)
        start_dt = parse_dt(start)
        if end_dt < start_dt:
            raise ValidationError("end can't be before start.")


def new_item(
    title: str,
    content: str = "",
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    title = title.strip()
    if not title:
        raise ValidationError("title is required.")
    validate_temporal(start, end)

    ts = now_iso()
    return {
        "id": new_id(),
        "title": title,
        "content": content or "",
        "tags": normalize_tags(tags),
        "start": start,
        "end": end,
        "completed_at": None,
        "created_at": ts,
        "updated_at": ts,
    }


def apply_patch(
    item: dict,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    clear_start: bool = False,
    clear_end: bool = False,
) -> dict:
    """Return a new item dict with only the passed fields changed."""
    new = dict(item)

    if title is not None:
        title = title.strip()
        if not title:
            raise ValidationError("title can't be blank.")
        new["title"] = title
    if content is not None:
        new["content"] = content
    if tags is not None:
        new["tags"] = normalize_tags(tags)

    next_start = new["start"]
    next_end = new["end"]
    if clear_start:
        next_start = None
    if clear_end:
        next_end = None
    if start is not None:
        next_start = start
    if end is not None:
        next_end = end
    # clear_start with no explicit end wipes end too — an event/reminder can't keep
    # a dangling end once its start is gone.
    if clear_start and end is None and not clear_end:
        next_end = None

    validate_temporal(next_start, next_end)
    new["start"] = next_start
    new["end"] = next_end

    new["updated_at"] = now_iso()
    return new


def item_kind(item: dict) -> str:
    """Presentational only — never stored. See models.py module docstring."""
    if item.get("end"):
        return "event"
    if item.get("start"):
        return "reminder"
    if item.get("completed_at"):
        return "reminder"
    return "note"


def find(items: list[dict], item_id: str) -> dict:
    for item in items:
        if item["id"] == item_id:
            return item
    raise ItemNotFoundError(f"No item with id '{item_id}'.")
