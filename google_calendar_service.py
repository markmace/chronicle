"""Read-only Google Calendar integration.

Events are shaped into item dicts (start+end set, so models.item_kind derives
"event" the same as any native item) and merged into items_service.list_items
at read time -- never persisted to items.json. That sidesteps the sync/
conflict/dedup machinery a real two-way integration would need; if that
happens later it's a different project built on top of this, not an
extension of it. See BACKLOG.md.

No-ops (returns []) whenever credentials aren't configured or a call fails,
so this is a pure overlay -- Chronicle works exactly as before without it.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import httpx

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_CALENDAR_REFRESH_TOKEN = os.environ.get("GOOGLE_CALENDAR_REFRESH_TOKEN")
GOOGLE_CALENDAR_IDS = [c.strip() for c in os.environ.get("GOOGLE_CALENDAR_IDS", "").split(",") if c.strip()]

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

WINDOW_PAST = timedelta(days=1)
WINDOW_FUTURE = timedelta(days=30)

_EVENTS_CACHE_TTL = 60.0
_events_cache: tuple[list[dict], float] | None = None
_access_token_cache: tuple[str, float] | None = None  # (token, monotonic expiry)


def configured() -> bool:
    return bool(
        GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET
        and GOOGLE_CALENDAR_REFRESH_TOKEN and GOOGLE_CALENDAR_IDS
    )


async def _access_token(client: httpx.AsyncClient) -> str:
    global _access_token_cache
    if _access_token_cache is not None:
        token, expires_at = _access_token_cache
        if time.monotonic() < expires_at:
            return token

    r = await client.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_CALENDAR_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=15)
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    _access_token_cache = (token, time.monotonic() + data.get("expires_in", 3600) - 60)
    return token


def _to_iso(when: dict) -> str | None:
    """A Calendar API start/end object has either 'dateTime' (timed) or
    'date' (all-day)."""
    if "dateTime" in when:
        return datetime.fromisoformat(when["dateTime"]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "date" in when:
        return f"{when['date']}T00:00:00Z"
    return None


def _event_to_item(event: dict, calendar_id: str, calendar_name: str) -> dict | None:
    if event.get("status") == "cancelled":
        return None
    start_iso = _to_iso(event.get("start", {}))
    if not start_iso:
        return None
    end_iso = _to_iso(event.get("end", {})) or start_iso

    return {
        "id": f"gcal:{calendar_id}:{event['id']}",
        "title": event.get("summary") or "(untitled)",
        "content": event.get("description") or "",
        "tags": [],
        "start": start_iso,
        "end": end_iso,
        "completed_at": None,
        "created_at": start_iso,
        "updated_at": event.get("updated", start_iso),
        "order": None,
        "source": "google_calendar",
        "calendar_id": calendar_id,
        "calendar_name": calendar_name,
    }


async def list_upcoming_events() -> list[dict]:
    """Events across all configured calendars, roughly "yesterday through
    next 30 days". Cached briefly to avoid hitting the API on every request."""
    global _events_cache
    if not configured():
        return []

    if _events_cache is not None:
        events, cached_at = _events_cache
        if time.monotonic() - cached_at < _EVENTS_CACHE_TTL:
            return events

    now = datetime.now(timezone.utc)
    params = {
        "timeMin": (now - WINDOW_PAST).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timeMax": (now + WINDOW_FUTURE).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }

    try:
        async with httpx.AsyncClient() as client:
            token = await _access_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            items: list[dict] = []
            for calendar_id in GOOGLE_CALENDAR_IDS:
                r = await client.get(
                    EVENTS_URL.format(calendar_id=calendar_id),
                    headers=headers, params=params, timeout=15,
                )
                r.raise_for_status()
                data = r.json()
                calendar_name = data.get("summary", calendar_id)
                for event in data.get("items", []):
                    item = _event_to_item(event, calendar_id, calendar_name)
                    if item:
                        items.append(item)
    except httpx.HTTPError:
        return _events_cache[0] if _events_cache else []

    _events_cache = (items, time.monotonic())
    return items


async def find(item_id: str) -> dict | None:
    for item in await list_upcoming_events():
        if item["id"] == item_id:
            return item
    return None
