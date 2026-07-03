# Backlog

Deferred ideas — not commitments, not scheduled. Add freely, prune freely. Keep
entries short; the "why" only where it's not obvious. See `~/notes/Chronicle.md`
for the underlying design philosophy these should stay consistent with.

## Web UI

- **Date/time entry, Apple Reminders–style.** A date alone implies local midnight;
  time is a separate, optional refinement on top. Also: default the date picker to
  today (or a "Now" quick-fill) instead of requiring it to be picked every time.
- Mobile performance/UX pass — re-check load time, tap targets, scroll feel on an
  actual phone now that the page has grown (add form, edit screen, login).
- Search across items (currently only exact tag filter; no free-text search).
- A "Today" / calendar-style view — grouping upcoming items by day. Chronicle.md's
  own vision calls this out explicitly as a first example of "views as
  configuration."
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
