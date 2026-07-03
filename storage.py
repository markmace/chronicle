"""items.json storage: read/write the whole file, plus a retry-once mutation helper."""

import json
from typing import Callable, TypeVar

import httpx

import github_store

ITEMS_PATH = "items.json"

T = TypeVar("T")


async def read_items() -> tuple[list[dict], str | None]:
    """Returns ([], None) if items.json doesn't exist yet (fresh repo)."""
    try:
        content, sha = await github_store.read_file(ITEMS_PATH)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return [], None
        raise
    return json.loads(content) if content.strip() else [], sha


async def write_items(items: list[dict], message: str, sha: str | None) -> str:
    content = json.dumps(items, indent=2, sort_keys=True) + "\n"
    return await github_store.write_file(ITEMS_PATH, content, message, sha)


async def mutate(mutator: Callable[[list[dict]], tuple[list[dict], T]], message: str) -> T:
    """Read-modify-write items.json with one retry on conflict.

    `mutator(items)` returns (new_items, result). It may raise a domain error
    (e.g. ItemNotFoundError) — that propagates immediately, no retry, since it's
    not a concurrency issue.
    """
    for attempt in range(2):
        items, sha = await read_items()
        new_items, result = mutator(items)
        try:
            await write_items(new_items, message, sha=sha)
            return result
        except github_store.ConflictError:
            if attempt == 1:
                raise
