"""SPIKE: user-defined groups for a composable home screen.

Exploratory, not production-hardened -- see BACKLOG.md "Composable views" for
the full vision this is a step toward. Deliberately simple:

- A group is a name + a flat rule: match ("any"/"all" -- OR/AND) over a list
  of conditions, each either {"tag": "..."} or {"kind": "note"|"reminder"|
  "event"}. No nesting (can't express "X and (Y or Z)"), no editing a group's
  rule in place (delete and recreate instead).
- Stored in its own views.json, read-modify-write, no caching or conflict
  retry -- groups are edited far less often than items, so the extra
  machinery storage.py has for items.json didn't seem worth duplicating yet.
"""

import json
import re
import uuid

import httpx

import github_store
import models

VIEWS_PATH = "views.json"


class RuleError(Exception):
    """The typed rule text couldn't be parsed."""


async def _read() -> tuple[dict, str | None]:
    try:
        content, sha = await github_store.read_file(VIEWS_PATH)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"groups": []}, None
        raise
    data = json.loads(content) if content.strip() else {"groups": []}
    data.setdefault("groups", [])
    return data, sha


async def list_groups() -> list[dict]:
    data, _ = await _read()
    return data["groups"]


async def create_group(name: str, rule_text: str) -> dict:
    name = name.strip()
    if not name:
        raise RuleError("Give the group a name.")
    match, conditions = parse_rule(rule_text)

    data, sha = await _read()
    group = {"id": uuid.uuid4().hex, "name": name, "match": match, "conditions": conditions}
    data["groups"].append(group)
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    await github_store.write_file(VIEWS_PATH, content, f"Add group: {name}", sha)
    return group


async def delete_group(group_id: str) -> None:
    data, sha = await _read()
    data["groups"] = [g for g in data["groups"] if g["id"] != group_id]
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    await github_store.write_file(VIEWS_PATH, content, "Delete group", sha)


def parse_rule(text: str) -> tuple[str, list[dict]]:
    """Tiny DSL: "tag:x or kind:y" / "tag:x and tag:y" / "tag:x" alone.
    Mixing "and"/"or" in the same rule isn't supported -- pick one."""
    text = text.strip()
    if not text:
        raise RuleError("Rule can't be empty, e.g. 'tag:important' or 'kind:note or tag:idea'.")

    if re.search(r"\s+or\s+", text, re.IGNORECASE):
        match = "any"
        parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    elif re.search(r"\s+and\s+", text, re.IGNORECASE):
        match = "all"
        parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
    else:
        match = "any"
        parts = [text]

    conditions = []
    for part in parts:
        part = part.strip()
        if ":" not in part:
            raise RuleError(f"'{part}' isn't 'tag:value' or 'kind:value'.")
        key, _, value = part.partition(":")
        key = key.strip().lower()
        value = value.strip().lower()
        if key not in ("tag", "kind"):
            raise RuleError(f"'{key}' must be 'tag' or 'kind' (note/reminder/event).")
        if not value:
            raise RuleError(f"'{part}' is missing a value after the colon.")
        if key == "kind" and value not in ("note", "reminder", "event"):
            raise RuleError(f"kind must be note, reminder, or event -- got '{value}'.")
        conditions.append({key: value})
    return match, conditions


def rule_text(group: dict) -> str:
    """Inverse of parse_rule, for displaying a stored group's rule back."""
    joiner = " or " if group["match"] == "any" else " and "
    return joiner.join(f"{k}:{v}" for c in group["conditions"] for k, v in c.items())


def item_matches(item: dict, group: dict) -> bool:
    conditions = group.get("conditions", [])
    if not conditions:
        return False
    results = []
    for c in conditions:
        if "tag" in c:
            results.append(c["tag"] in item.get("tags", []))
        elif "kind" in c:
            results.append(models.item_kind(item) == c["kind"])
        else:
            results.append(False)
    return any(results) if group.get("match") == "any" else all(results)
