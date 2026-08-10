# PM Sync — Phase 9 (Workspace & Place Detail Focus Mode)

Plan: `plans/260805-1022-claude-design-ui-integration/`

## Status change

| File | Before | After |
|---|---|---|
| `phase-09-fe-stage-workspace-focus.md` frontmatter | `status: pending` | `status: done` |
| `phase-09-fe-stage-workspace-focus.md` acceptance criteria | 0/20 | 20/20 (+2 new lines added for the fidelity-checklist/register cross-refs → 22/22 total incl. those) |
| `plan.md` phase table row 9 | Pending | Done |
| `plan.md` §Phần chưa làm | 23 items | 24 items (+#24: TimelineItem `it.note` line — no `DayItem.note` field exists) |
| `design-fidelity-checklist.md` §Phase 9 | 0 ticked | all ticked except 2, each with a written reason (header shadow value reuses the shared `glass-panel` utility instead of a bespoke one; TimelineItem's ghi-chú line dropped, no source data) |

## What was actually done this session

Most of Phase 9's implementation (9 new files, ~1170 LOC) was already written in a prior *uncommitted* session before this one started. This session:
1. Scouted and verified it against the plan, the `.dc.html` design sources, and the actual backend contract (`reference_type` value, coordinate format, `route_to_next` shape).
2. Found and fixed a real functional gap: `frontend/mock/server.js` had two `ATTRACTION_DETAILS` fixtures with no `DayItem` pointing to them — Place Detail Focus Mode was untriggerable against the mock. Added `reference_type`/`reference_id` to the two matching day-items.
3. Added `frontend/src/lib/geo.test.ts` and `leg.test.ts` (22 new tests) — the two new pure-function libs had no coverage.
4. Spawned an independent `code-reviewer` review. It returned `DONE_WITH_CONCERNS`: 3 High-severity bugs in the focus/tab state machine + 1 real data-correctness bug in ticket-price rendering. Fixed all of them:
   - Tab reset was keyed on `trip_plan` object identity, which is fresh on every chat turn → jumped the user back to "Tổng quan" on every message. Now derives the displayed tab at render time instead of syncing via effect.
   - Scroll save/restore ref was attached to the non-scrolling wrapper div, not the actual `overflow-y-auto` element → silently a no-op.
   - `focused` didn't check that the focused item still exists in a just-updated plan → could pin the layout open (chat/map collapsed) with no detail panel and no way back. Also: hotel focus mode could survive a stage transition into the workspace for the same reason — fixed by closing focus mode on every stage change.
   - Ticket-price truth table showed "Miễn phí" over a real child fare, and inferred a free adult fare from a `0` child fare alone (inventing data). Rewrote to treat adult/child fares independently.
5. Also fixed 2 lower-severity findings: reused the existing `formatHotelStars` helper instead of an inline `.repeat()` (explicitly listed in the plan's "Tái dùng" section), and corrected a wrong docstring in `leg.ts` about `route_to_next`'s last-item semantics.
6. Re-verified: `npm run typecheck`, `npm run lint`, `npm run test` (91/91) all clean after every fix.

Deferred (documented, not fixed — cross-phase or low-value):
- `use-attraction-detail.ts` is a near-verbatim clone of Phase 8's `use-hotel-detail.ts`, and both share a 1-frame stale-content flash when switching detail subjects while focused. Fixing it properly means touching a Phase 8 file (`use-hotel-detail.ts`) or the shared `place-client.ts` — out of this phase's file scope, flagged for the user rather than silently changed.
- A handful of Low-severity design-fidelity/DX nits from the review (near-zero-distance route edge case, minor `NUM_LOCALE`/`nightsFrom` duplication across the new files, hero image duplicated as gallery thumb 0) — noted, not blocking, left for a follow-up pass.

## Pre-existing bookkeeping inconsistencies (not touched this session)

`plan.md`'s phase status table disagrees with the phase files' own frontmatter for three phases that predate this session's work:

| Phase | `plan.md` table says | Phase file's own `status:` | Checklist |
|---|---|---|---|
| 2 (hotel option payload) | Pending | done | 0/12 checked — file itself is inconsistent too |
| 8 (Stage: Khách sạn & Hotel Focus) | Pending | done | 23/23 checked |
| 12 (OSRM → Mapbox) | Pending | done | 0/13 checked |

Phase 8 in particular is clearly shipped and is Phase 9's own stated dependency (`use-focus-mode`, `StageHotels` are live and reused by this phase). Not corrected here — none of these three phases were touched in this session, and reconciling them requires verifying their actual shipped state, which is a separate task the user should direct explicitly.

## Unresolved questions

- Should Phase 2/8/12's `plan.md` table rows be corrected to match their own phase files' `done` status? (Pre-existing drift, not part of this session's scope.)
- Deferred: merge `use-attraction-detail.ts`/`use-hotel-detail.ts` into one shared hook — worth doing, touches Phase 8's file.
