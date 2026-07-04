# Backlog

Deferred ideas — not commitments, not scheduled. Add freely, prune freely. Keep
entries short; the "why" only where it's not obvious. See `~/notes/Chronicle.md`
for the underlying design philosophy these should stay consistent with.

## Composable views (2026-07-03)

The big one — this is Chronicle.md's own "views are configuration, not features"
principle, actually being asked for now rather than just theorized about. Mark's
framing: the front page should be assembled from configurable rules instead of the
current hardcoded Upcoming/Notes/Completed grouping — e.g. "notes tagged `important`
at the top, then reminders from the past few days." Needs a **canonical view**
(today's default grouping, or similar) always reachable via a simple switcher, so a
custom view can never hide something you need to see.

**Spike done 2026-07-03** (`views_service.py`, `templates/custom_view.html`,
`?mode=custom` on `/view/{token}`) — proved the mechanism works end to end, kept
deliberately narrow:

- A group is a name + one flat rule: `tag:x`, `kind:note|reminder|event`, joined
  by "and"/"or" (not both — no real precedence/nesting, so "X and (Y or Z)" isn't
  expressible). Typed as text, e.g. `tag:important or kind:reminder`.
- Stored in its own `views.json`, plain read-modify-write — no caching or
  conflict-retry like `storage.py` has for items, since groups change far less
  often. Would need that treatment if this graduates past spike status.
- Canonical view got a quiet `canonical · custom` switcher; custom mode renders
  each group as its own section (reusing the same collapsed title-only row style)
  plus an inline "manage groups" panel to add/delete. Items un-matched by any
  group just don't show in custom mode — canonical is the guaranteed "see
  everything" escape hatch, via the switcher.
- Real gaps if this becomes permanent, not just a spike: no in-place rule editing
  (delete + recreate only), no nested boolean logic, no drag-to-reorder groups or
  items within them (`items_service.move_note` is sitting right there if wanted),
  no way to control which canonical items appear in *neither* view, group rows
  don't have swipe-to-act (complete/delete) like the canonical view does.
- Verified: rule parsing + matching (unit-level), create/list/delete against the
  real repo, error handling for malformed rules, and that an already-running
  dev server needs a restart to pick up `main.py` changes (Jinja templates
  reload per-request; Python module code doesn't without `--reload` — cost me
  a confusing debugging detour before I remembered that).

## Web UI

- ~~**Reorder notes manually**~~ — done 2026-07-03, revised same day. First pass
  added always-visible drag handles to every note row; felt bolted-on and broke
  the list's quiet/restrained design (never showing controls you're not using).
  Reordering now lives on the note's edit screen (Move up/down, single-step,
  reusing `items_service.reorder_note`'s swap logic — also the MCP tool's model
  for "move this note up"). `items_service.move_note` (fractional-order,
  arbitrary position) and its JSON API endpoint were built for real drag-and-drop
  and still work, just unused by the UI now — worth revisiting once/if a
  composable view actually wants draggable ordering.
- ~~**Collapse/truncate long notes**~~ — done 2026-07-03. Notes over 200 chars
  show a truncated preview with a "more"/"less" toggle (pure `<details>`, no JS);
  full content always shown on the edit screen regardless of length.
- **Reorder events/reminders manually** — clarified: chronological order always
  wins whenever start times differ; manual order only breaks ties among
  undated reminders or items sharing the same start time. Not built yet — the
  current `reorder_note` swap logic is scoped to notes only.
- ~~**Sort/group by tag** as an alternate view mode~~ — subsumed by the
  composable-views spike above (`kind:x`/`tag:y` group rules).
- **"Move groups"** — needs clarifying: reordering the sections themselves
  (Upcoming/Notes/Completed), or moving an item between groups (e.g. note →
  reminder)? The latter already works today via the edit screen's start/end fields;
  worth confirming which one Mark means.
- **Date/time entry, Apple Reminders–style.** A date alone implies local midnight;
  time is a separate, optional refinement on top. Also: default the date picker to
  today (or a "Now" quick-fill) instead of requiring it to be picked every time.
- Mobile performance/UX pass — re-check load time, tap targets, scroll feel on an
  actual phone now that the page has grown (add form, edit screen, login). One
  real bug already fixed 2026-07-03: `storage.py` was sleeping up to 2s on
  *every* read within 2s of any write (the fix for GitHub's read-after-write
  lag), which penalized every action-then-reload regardless of whether that
  particular read needed it. Now caches the known-good post-write state instead
  of sleeping — still worth a real look at load time beyond that one fix.
- Search across items (currently only exact tag filter; no free-text search).
- A "Today" / calendar-style view — grouping upcoming items by day. Likely a
  special case of the composable-views work above rather than a separate feature.
- Explicit light/dark theme toggle (currently follows system preference only).
- PWA installability (manifest.json) for a real home-screen icon + offline shell,
  vs. today's iOS-only "Add to Home Screen" via meta tag.
- Keyboard shortcuts for desktop/web use (e.g. `n` for new item, `/` to search).

## Data model

- Recurring items (daily/weekly/etc.) — real design work: a recurrence rule needs
  to interact with `start`/`end`/`completed_at` in a way that doesn't break the
  "temporal shape is derived, not stored" principle.
- Bulk actions (multi-select complete/delete).

## Platforms

- iOS app.
- macOS app.
- Push notifications — depends on having a native app (or web push) as a delivery
  mechanism; blocked on the above.

## Open questions (carried over from Chronicle.md, still unresolved)

- Relationship to Apple's own Notes/Reminders/Calendar data — import/export, or
  stays fully independent?
- Storage model once `items.json` stops being "dozens to low hundreds" of items —
  single-file-in-GitHub was a deliberate skateboard simplification, not a
  permanent architecture decision.
- Where's the line between a "tag" and a saved/smart view?

## Housekeeping (flagged earlier, still open)

- GitHub Actions auto-deploy-on-push (`fly launch` added this automatically) —
  keep or remove?
- `GITHUB_TOKEN` is still Mark's personal `gh` CLI token, not a repo-scoped PAT.
