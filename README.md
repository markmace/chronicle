# Chronicle

Notes, reminders, and calendar events as one thing: an *item*, distinguished only by
its temporal shape. Built for Claude to work on directly, not bolted onto afterward.

## Why

Reminders, calendar events, and notes are the same underlying object — an item with
content — differentiated only by time:

- **Event** — fixed start, fixed end
- **Reminder** — fixed start (or none, for "anytime"), open end until completed
- **Note** — no temporal constraint at all

Apple's Notes/Reminders/Calendar are three siloed apps with weak API access, which
makes it hard for an agent to reason across "what's on my plate" the way you can by
glancing at all three. Chronicle models time as a property of one item type instead —
one coherent surface for Claude to read, write, and reason over.

This is the *skateboard*: the smallest end-to-end version that proves the loop of
Claude and me working on the same items together. Single-user, MCP as the primary
interface, plus a mobile-first page for add/edit/complete/delete. No calendar view,
no native app yet — those are car parts for later, though the JSON API underneath
is built with them in mind.

## Screenshots

|  |  |
|---|---|
| ![List view](docs/screenshots/list-view.png) | ![List view, dark](docs/screenshots/list-view-dark.png) |
| ![Edit screen](docs/screenshots/edit-screen.png) | ![Login](docs/screenshots/login.png) |

Regenerate these against your own dev server after UI changes with:

```bash
./scripts/screenshot.sh
```

(Requires `.dev.env` set up per **Local development** below, and Google Chrome
installed at the standard macOS path.)

## How it works

```mermaid
flowchart LR
    G["GitHub — chronicle-data<br/>items.json"]
    M["Chronicle server<br/>on Fly.io"]
    C["claude.ai"]
    V["/view — mobile-first page"]

    M <-->|REST API| G
    M <-->|MCP| C
    M <--> V
```

All items live as one JSON array (`items.json`) in a private GitHub repo — free
version history, zero database to run, $0/month on Fly's free tier. Every write is a
git commit.

### MCP tools

| Tool | What it does |
|---|---|
| `create_item(title, content?, tags?, start?, end?)` | Create a note/reminder/event — the shape follows from which time fields you set |
| `list_items(tag?, start_after?, start_before?, include_completed?)` | List item summaries, filtered |
| `get_item(id)` | Full item including content |
| `update_item(id, ...)` | Partial patch; `clear_start`/`clear_end` to remove time fields |
| `complete_item(id)` / `uncomplete_item(id)` | Toggle done state, idempotent |
| `delete_item(id)` | Destructive — Claude always confirms first |

### The `/view` page

`GET /view/<MCP_TOKEN>` — a mobile-first page grouping items into Upcoming / Notes /
Completed. Add is collapsed behind a small "+" bar by default; tapping an item's
title opens a dedicated edit screen (title/content/tags/start/end, plus delete).
No build tooling, no JS framework — plain forms POSTing back to the same server,
with a little inline JS just for timezone conversion on datetime fields. Add it to
your iPhone home screen (Share → Add to Home Screen) for an app-like, chrome-free
view.

### JSON REST API

`/api/<MCP_TOKEN>/items` (GET/POST), `/api/<MCP_TOKEN>/items/<id>` (GET/PATCH/DELETE),
plus `/complete` and `/uncomplete` POST endpoints — the same operations as the MCP
tools and the HTML forms, as JSON. Not consumed by the current page (which still
uses plain form POSTs), but there so a future richer web app or native app has a
stable contract to build on without another rewrite of the business logic — which
all three surfaces (MCP, HTML forms, JSON API) share via `items_service.py`.

---

## Setup

You'll need a GitHub account and [flyctl](https://fly.io/docs/hands-on/install-flyctl/).

### 1. Make a data repo

```bash
gh repo create youruser/chronicle-data --private --add-readme
```

### 2. Make a GitHub PAT

github.com/settings/tokens → a fine-grained token scoped to `chronicle-data` with
Contents read/write is enough (a classic token with `repo` scope also works).

### 3. Deploy the server

```bash
git clone https://github.com/youruser/chronicle
cd chronicle
fly launch          # accept defaults, decline deploy-now
# If fly launch regenerates fly.toml, keep internal_port = 8080 — the Dockerfile hardcodes 8080

fly secrets set \
  MCP_TOKEN=$(openssl rand -hex 32) \
  VIEW_PASSWORD=some-password-you-choose \
  GITHUB_TOKEN=ghp_your_pat_here \
  GITHUB_REPO=youruser/chronicle-data

fly deploy
```

Note the `MCP_TOKEN` — you'll need it for the connector URL.

### 4. Connect Claude

claude.ai → **Settings → Connectors → Add custom connector**

URL: `https://<your-app>.fly.dev/mcp/<your-MCP_TOKEN>`

**Security note:** the token is in the URL path, so it can appear in server/proxy
access logs. Deliberate simplicity tradeoff for a personal tool. Rotate with
`fly secrets set MCP_TOKEN=$(openssl rand -hex 32)` if it leaks.

Ask Claude "list my Chronicle items" — should come back empty on a fresh repo.

### 5. Log in to the web page

Visit `https://<your-app>.fly.dev/` and enter `VIEW_PASSWORD`. A cookie remembers
you for ~400 days (Chrome's max), so this is normally a one-time thing per device
— log out via the link in the page footer if you ever need to re-auth. The old
`/view/<MCP_TOKEN>` URL still works directly too, session or not.

Bookmark the bare domain (`https://<your-app>.fly.dev/`) — that's the friendly
entry point now.

## Local development

```bash
uv sync
cp .dev.env.example .dev.env   # fill in MCP_TOKEN, GITHUB_TOKEN, GITHUB_REPO
set -a && source .dev.env && set +a
uv run uvicorn main:app --reload --port 8080
```

`uv run python scripts/smoke_test.py` exercises the storage layer directly against
the real data repo (creates a note/reminder/event tagged `smoke-test`, checks
filtering, completes one, then deletes everything it created).

## File layout

```
main.py          — FastAPI app: MCP mount, /healthz, /view + /view/.../edit pages, JSON API
mcp_server.py    — the 7 MCP tools (thin wrappers over items_service)
items_service.py — shared create/list/get/update/complete/delete logic
models.py        — item schema, validation, derived kind
storage.py       — items.json read/write, retry-once-on-conflict mutation helper
github_store.py  — thin GitHub Contents API client (generic file read/write)
auth.py          — constant-time token comparison
templates/items.html     — the list view
templates/edit_item.html — the single-item edit screen
templates/login.html     — password login screen
templates/_mark.html     — the ensō ink-mark, included wherever the logo appears
static/style.css  — shared styling for all pages
static/favicon.svg — browser tab icon (same mark)
scripts/smoke_test.py  — dev-only, exercises storage/models against the real repo
scripts/screenshot.sh  — regenerates docs/screenshots/ from a local dev server
Dockerfile
fly.toml
```

## Cost

Fly.io's free tier covers this — 256MB RAM, shared CPU, auto-stops when idle. GitHub
API calls are well under the 5000/hour limit. $0/month for personal use.

## License

MIT — do whatever you want with it.
