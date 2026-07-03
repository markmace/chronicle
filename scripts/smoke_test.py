"""Dev-only smoke test — exercises storage.py/models.py directly against the real
GITHUB_REPO (no HTTP/MCP involved). Creates one of each item shape tagged
'smoke-test', checks filtering, completes a reminder, then deletes everything it
created so the repo stays clean.

Usage: set MCP_TOKEN/GITHUB_TOKEN/GITHUB_REPO (e.g. `source .dev.env`), then
`uv run python scripts/smoke_test.py`.
"""

import asyncio
import sys

import models
import storage

TAG = "smoke-test"


def check(label: str, cond: bool):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        FAILURES.append(label)


FAILURES: list[str] = []


async def main():
    print(f"Using repo: {storage.github_store.GITHUB_REPO}\n")

    note = models.new_item("Smoke test note", content="hello from smoke_test.py", tags=[TAG])
    reminder = models.new_item("Smoke test reminder", tags=[TAG], start="2099-01-01T09:00:00Z")
    event = models.new_item(
        "Smoke test event", tags=[TAG],
        start="2099-01-02T15:00:00Z", end="2099-01-02T15:30:00Z",
    )

    async def add(item):
        def m(items):
            return items + [item], item
        return await storage.mutate(m, message=f"[smoke test] create {item['title']}")

    await add(note)
    await add(reminder)
    await add(event)
    print("Created note, reminder, event.\n")

    items, _ = await storage.read_items()
    tagged = [i for i in items if TAG in i["tags"]]
    check("all 3 items present after create", len(tagged) == 3)

    check("note kind", models.item_kind(note) == "note")
    check("reminder kind", models.item_kind(reminder) == "reminder")
    check("event kind", models.item_kind(event) == "event")

    dated = [i for i in tagged if i.get("start") and i["start"] >= "2099-01-01" and i["start"] < "2099-01-03"]
    check("time-range filter excludes undated note", note["id"] not in [i["id"] for i in dated])
    check("time-range filter includes reminder + event", len(dated) == 2)

    async def complete(item_id):
        def m(items):
            item = models.find(items, item_id)
            idx = items.index(item)
            completed = dict(item)
            completed["completed_at"] = models.now_iso()
            new_items = list(items)
            new_items[idx] = completed
            return new_items, completed
        return await storage.mutate(m, message="[smoke test] complete reminder")

    completed_reminder = await complete(reminder["id"])
    check("reminder completed_at set", completed_reminder["completed_at"] is not None)

    items, _ = await storage.read_items()
    visible_default = [i for i in items if TAG in i["tags"] and not i.get("completed_at")]
    check("completed reminder hidden by default filter", reminder["id"] not in [i["id"] for i in visible_default])

    # Cleanup — delete everything this script created.
    async def delete(item_id):
        def m(items):
            item = models.find(items, item_id)
            return [i for i in items if i["id"] != item_id], item
        return await storage.mutate(m, message="[smoke test] cleanup")

    for item in (note, reminder, event):
        await delete(item["id"])

    items, _ = await storage.read_items()
    check("cleanup removed all smoke-test items", not any(TAG in i["tags"] for i in items))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
