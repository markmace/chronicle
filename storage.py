"""items.json storage: read/write the whole file, plus a retry mutation helper."""

import asyncio
import json
import time
from typing import Callable, TypeVar

import httpx

import github_store

ITEMS_PATH = "items.json"

T = TypeVar("T")

# GitHub's Contents API has a brief read-after-write lag on a given path — not just
# on the read, but on the conditional-write's own sha check, which can itself be
# served from a stale replica and let a conditional write based on a stale sha
# through. Back-to-back writes to items.json (e.g. deleting 3 items in a row) can
# then silently "resurrect" a just-deleted item. Enforcing a minimum spacing since
# our own last write, before issuing the next read, keeps every read/write cycle
# past that lag window. Single-process only — fine for a single-user tool.
_MIN_WRITE_SPACING = 2.0
_last_write_at: float | None = None


async def read_items() -> tuple[list[dict], str | None]:
    """Returns ([], None) if items.json doesn't exist yet (fresh repo)."""
    if _last_write_at is not None:
        elapsed = time.monotonic() - _last_write_at
        if elapsed < _MIN_WRITE_SPACING:
            await asyncio.sleep(_MIN_WRITE_SPACING - elapsed)
    try:
        content, sha = await github_store.read_file(ITEMS_PATH)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return [], None
        raise
    return json.loads(content) if content.strip() else [], sha


async def write_items(items: list[dict], message: str, sha: str | None) -> str:
    global _last_write_at
    content = json.dumps(items, indent=2, sort_keys=True) + "\n"
    result = await github_store.write_file(ITEMS_PATH, content, message, sha)
    _last_write_at = time.monotonic()
    return result


_RETRY_DELAYS = [0.0, 0.7, 1.5]  # seconds to wait before each attempt


async def mutate(mutator: Callable[[list[dict]], tuple[list[dict], T]], message: str) -> T:
    """Read-modify-write items.json, retrying on conflict with a short backoff.

    `mutator(items)` returns (new_items, result). It may raise a domain error
    (e.g. ItemNotFoundError) — that propagates immediately, no retry, since it's
    not a concurrency issue.

    The backoff matters even for single-user, sequential writes: GitHub's Contents
    API has a brief read-after-write lag, so a read immediately following our own
    write can still return a stale sha. A bare instant retry can hit that same
    stale response; waiting a beat before re-reading gives it time to catch up.
    """
    for i, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        items, sha = await read_items()
        new_items, result = mutator(items)
        try:
            await write_items(new_items, message, sha=sha)
            return result
        except github_store.ConflictError:
            if i == len(_RETRY_DELAYS) - 1:
                raise
