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

Deliberately not scoped or started yet — real design work before code: what a
"view definition" looks like (a saved filter/sort/grouping recipe?), where it's
stored (part of an item? a separate `views.json`?), how the switcher UI works, and
how this interacts with the tag-vs-saved-view open question below. Worth its own
planning pass rather than growing organically out of the current template.

## Web UI

- **Reorder notes manually** (drag, or move-up/down controls) — needs a persisted
  order field; notes currently just sort by `created_at`.
- **Collapse/truncate long notes** in the list view (show first N lines + "more"),
  full content still visible on the edit screen.
- **Reorder events/reminders manually** — needs clarifying: these currently sort by
  `start` time, which is the whole point for dated items. Probably means overriding
  order among *undated* reminders or same-day items, not fighting the calendar.
- **Sort/group by tag** as an alternate view mode — likely folds into the
  composable-views work above rather than being its own one-off toggle.
- **"Move groups"** — needs clarifying: reordering the sections themselves
  (Upcoming/Notes/Completed), or moving an item between groups (e.g. note →
  reminder)? The latter already works today via the edit screen's start/end fields;
  worth confirming which one Mark means.
- **Date/time entry, Apple Reminders–style.** A date alone implies local midnight;
  time is a separate, optional refinement on top. Also: default the date picker to
  today (or a "Now" quick-fill) instead of requiring it to be picked every time.
- Mobile performance/UX pass — re-check load time, tap targets, scroll feel on an
  actual phone now that the page has grown (add form, edit screen, login).
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
