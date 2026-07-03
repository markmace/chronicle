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
# then silently "resurrect" a just-deleted item.
#
# Rather than sleep past that lag window on every read (which made every page
# view up to _CACHE_TTL seconds slower, even ones with no write involved), cache
# the state our own last write produced — we know it's correct, no need to ask
# GitHub again. A read within the window is served from that cache; a write
# failure (a genuine external conflict, e.g. someone editing items.json by hand
# on GitHub) invalidates it so the retry re-reads for real. Single-process only —
# fine for a single-user tool, and we're pinned to exactly one Fly machine.
_CACHE_TTL = 2.0
_cache: tuple[list[dict], str | None, float] | None = None


async def read_items() -> tuple[list[dict], str | None]:
    """Returns ([], None) if items.json doesn't exist yet (fresh repo)."""
    global _cache
    if _cache is not None:
        items, sha, cached_at = _cache
        if time.monotonic() - cached_at < _CACHE_TTL:
            return items, sha

    try:
        content, sha = await github_store.read_file(ITEMS_PATH)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            _cache = None
            return [], None
        raise

    items = json.loads(content) if content.strip() else []
    _cache = (items, sha, time.monotonic())
    return items, sha


async def write_items(items: list[dict], message: str, sha: str | None) -> str:
    global _cache
    content = json.dumps(items, indent=2, sort_keys=True) + "\n"
    commit_sha, new_content_sha = await github_store.write_file(ITEMS_PATH, content, message, sha)
    _cache = (items, new_content_sha, time.monotonic())
    return commit_sha


_RETRY_DELAYS = [0.0, 0.7, 1.5]  # seconds to wait before each attempt


async def mutate(mutator: Callable[[list[dict]], tuple[list[dict], T]], message: str) -> T:
    """Read-modify-write items.json, retrying on conflict with a short backoff.

    `mutator(items)` returns (new_items, result). It may raise a domain error
    (e.g. ItemNotFoundError) — that propagates immediately, no retry, since it's
    not a concurrency issue.
    """
    global _cache
    for i, delay in enumerate(_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        items, sha = await read_items()
        new_items, result = mutator(items)
        try:
            await write_items(new_items, message, sha=sha)
            return result
        except github_store.ConflictError:
            _cache = None  # our assumed state was wrong; force a real re-read
            if i == len(_RETRY_DELAYS) - 1:
                raise
