---
title: "Phase 9 workspace: fixed focus/tab state machine + ticket-price bugs"
date: 2026-08-07
summary: "Finished and hardened prior session's Phase 9 workspace implementation: fixed mock data gap, added tests, and resolved 3 High-severity state bugs + 1 data-correctness bug found by independent review"
---

# Phase 9 workspace: fixed focus/tab state machine + ticket-price bugs

## What happened

Phase 9 ([FE] Stage: Workspace & Place Detail Focus Mode) of
`plans/260805-1022-claude-design-ui-integration/` arrived at this session already
~95% implemented but entirely uncommitted from a prior session: 9 new files
(~1170 LOC) — `stage-workspace.tsx`, `trip-overview-tab.tsx`, `day-timeline.tsx`,
`timeline-item.tsx`, `place-detail-panel.tsx`, `use-attraction-detail.ts`,
`lib/geo.ts`, `lib/leg.ts`, `lib/map-colors.ts` — plus `day-card.tsx` and
`itinerary-panel.tsx` already deleted in favor of them.

Scouted and verified the implementation against the plan, the actual `.dc.html`
design sources, and the real backend contract (`reference_type` is confirmed
`"Attraction"` per `trip_scheduler.py:93`; coordinates are confirmed
`"lat,lng"` strings per `trip_formatter.py`).

## Root causes found

1. **Mock data gap.** `frontend/mock/server.js` had two `ATTRACTION_DETAILS`
   fixtures (`attraction-my-khe`, `attraction-ba-na`) but zero `DayItem`s in
   `TRIP_PLAN` pointed to them via `reference_type`/`reference_id` — Place
   Detail Focus Mode was structurally untriggerable against the mock. Fixed by
   wiring the two matching day-items to their fixtures.

2. **No test coverage** on the two new pure-function libs (`geo.ts`, `leg.ts`)
   despite the codebase's own convention of colocated tests for every other
   `lib/*.ts` file. Added `geo.test.ts` + `leg.test.ts` (22 tests), covering the
   four-state leg model explicitly (route / same-place / crow-fly / none).

3. **State-machine bugs**, caught by an independent `code-reviewer` subagent
   review (`DONE_WITH_CONCERNS`):
   - Tab reset was keyed on `trip_plan` object identity, which is a fresh
     object on every chat turn (backend re-serializes it every reply) — so the
     active day tab silently jumped back to "Tổng quan" on every message.
     Fixed by deriving the displayed tab at render time instead of syncing
     state via an effect.
   - Scroll save/restore's `ref` was attached to the `overflow-hidden` wrapper
     div, not the actual `overflow-y-auto` scrolling child — save/restore was
     a complete no-op, just accidentally invisible because the scroller never
     unmounted. Moved the ref to the correct element.
   - `focused` was derived from `focusedId != null` alone, not from whether
     the focused item still exists in a (possibly just-updated) plan — a chat
     turn replacing the plan while a place was focused could pin chat/map
     collapsed with no detail panel and no way back. Also: hotel focus mode
     (Phase 8) could survive a stage transition into the workspace for the
     identical reason. Fixed by gating `focused` on real context AND closing
     focus mode on every stage change.

4. **Data-correctness bug**: `ticketValue()`'s truth table showed "Miễn phí"
   over a real child fare when the adult fare was 0, and inferred a free adult
   fare from a `0` child fare alone with no adult data — inventing a number
   the backend never sent, which directly violates this whole plan's core
   principle. Rewrote to treat adult/child fares independently, with a per-fare
   label when both are shown.

## Decision

Fixed all High-severity + the data-correctness finding in-session (not deferred
to the user) — they're clear defects in Phase 9's own deliverable, not scope
questions. Deferred two Medium findings that touch Phase 8's shared files
(`use-hotel-detail.ts` clone duplication, `place-client.ts`'s error-vs-404
caching) since fixing them means editing files outside this phase's ownership —
flagged for the user instead of silently changed. A handful of Low-severity
nits (near-zero-distance route edge case, minor cross-file duplication) noted
but not fixed — low value relative to scope.

Discovered mid-session that a second, unrelated agent/session was concurrently
editing files in the same working tree (`chat-panel.tsx`/`intake-parameters-form.tsx`
IntakeFormState refactor, `backend/src/services/hotel_selection.py`). Had to
verify — via `git diff` on the specific files I touched — that 3 residual
`tsc` errors belonged entirely to their in-flight work, not mine, before
concluding my own changes were clean. Did not touch their files.

## Next steps

- Ask the user before any git add/commit — must scope to Phase 9's own files
  only, since the other session's changes are mid-flight and currently
  typecheck-broken.
- Pre-existing `plan.md` phase-status-table drift (phases 2, 8, 12 all show
  "Pending" despite their own phase files saying `status: done`) flagged but
  not corrected — out of this session's scope.
- Phase 10 (map) is next per plan dependency order; it explicitly reuses
  `lib/map-colors.ts` and `lib/leg.ts`'s `legBetween` — the corrected `leg.ts`
  docstring about `route_to_next`'s last-item (hotel-return) semantics matters
  there.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
