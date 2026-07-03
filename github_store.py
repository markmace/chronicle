"""Thin wrapper around the GitHub Contents API — generic file read/write primitives."""

import base64
import os

import httpx

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "markmace/chronicle-data")

_BASE = "https://api.github.com"
_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class ConflictError(Exception):
    """The file changed since it was read; a conditional write was rejected (HTTP 409)."""


async def read_file(path: str) -> tuple[str, str]:
    """Return (content, sha). Raises httpx.HTTPStatusError(404) if missing."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_BASE}/repos/{GITHUB_REPO}/contents/{path}",
            headers=_HEADERS,
            timeout=15,
        )
        r.raise_for_status()

    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


async def write_file(path: str, content: str, message: str, sha: str | None) -> str:
    """Create (sha=None) or conditionally update (sha=current sha) a file.

    Raises ConflictError on HTTP 409 — the file changed since sha was read.
    """
    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        body["sha"] = sha

    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{_BASE}/repos/{GITHUB_REPO}/contents/{path}",
            headers=_HEADERS,
            json=body,
            timeout=15,
        )
    if r.status_code == 409:
        raise ConflictError(path)
    r.raise_for_status()

    return r.json()["commit"]["sha"]
