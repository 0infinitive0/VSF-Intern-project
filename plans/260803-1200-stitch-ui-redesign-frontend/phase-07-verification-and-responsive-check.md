---
phase: 7
title: "Verification and responsive check"
status: completed
priority: P1
effort: "0.5d"
dependencies: [2, 3, 4, 5, 6]
---

# Phase 7: Verification and responsive check

## Overview

Final full-app pass: type-check, lint, build, then a manual walk-through against all 4
Stitch reference screenshots at both desktop and 360px mobile widths. This phase does
not add features — it verifies phases 1-6 landed coherently and nothing regressed.

## Requirements

- Functional: `frontend/mock/server.js`'s `TRIP_PLAN` fixture is updated (confirmed
  stale during plan validation): add `start_date`/`end_date` ISO strings, and correct
  `kind` values — `beach` and `shopping` (currently in the fixture,
  `mock/server.js:47-72`) are **not** in the backend's real `ItemKind` enum
  (`breakfast`/`attraction`/`lunch`/`rest`/`coffee`/`dinner`/`evening`, verified against
  `src/services/trip_edit_planner.py:31`) — remap both `beach` and `shopping` to
  `attraction` (see Implementation Steps for why) so `npm run mock` exercises the same
  badge/date code paths Phases 4-5 built.
  <!-- Updated: Validation Session 1 - user chose to fix the mock fixture too -->
- Functional: `npx tsc --noEmit`, `npm run lint` (oxlint), and `npm run build` (vite
  build) all pass with zero errors in `frontend/`.
- Functional: every `.jsx`/`.js` file under `frontend/src/{components,hooks,api}/` has
  been converted — confirm with a glob, not by memory.
- Functional: no remaining console errors/warnings introduced by this plan.
- Functional: full chat flow works end-to-end against the real backend (or the mock
  server, `frontend/mock/server.js`, if the backend isn't running locally): send a
  message → hotel_options stage → pick a hotel → itinerary renders → adjustments
  (if any) render → reset works.
- Non-functional: app renders with no horizontal scroll at 360px width and at a
  standard desktop width (e.g. 1440px), matching the plan's existing non-functional
  requirement (`plan.md` Success Criteria).
- Non-functional: side-by-side visual comparison against each of the 4
  `assets/*.png` screenshots — not pixel-perfect (Stitch mocks include fabricated
  content this plan deliberately excludes, per Decision 2), but structurally and
  tonally matching: same regions, same token palette, same card/typography language.

## Architecture

No new code. This phase is verification-only — the "Architecture" section is the
verification matrix:

| Stitch screen | Real-app equivalent state | What to check |
|---|---|---|
| `01-starting-chat-state` | Fresh session, empty chat | Top nav, empty chat panel, empty itinerary panel, map chrome all render |
| `02-unified-itinerary-view` | After a trip_plan exists | Itinerary panel tabs/pills, day cards with kind badges, dates in header |
| `03-parameters-hotel-selection` | `stage === 'hotel_options'` | TripParametersCard (dates/guests only), restyled hotel cards, optimistic selection |
| `04-detailed-itinerary-chat` | Mid-conversation with a plan | Chat bubbles/avatar chip, ElapsedSpinner (not DeepDive Thinking), full itinerary panel |

## Related Code Files

- Modify: `frontend/mock/server.js` (fixture fix per Requirements)
- Read-only verification across the rest of `frontend/src/`
- Modify (if issues found): whichever files phases 1-6 touched, to fix regressions —
  not to add new scope

## Implementation Steps

1. Fix `frontend/mock/server.js`'s `TRIP_PLAN` fixture (`mock/server.js:28-72`): add
   `start_date`/`end_date` ISO datetime strings alongside the existing `duration_days`/
   `number_of_adults`; replace every `kind: 'beach'` and `kind: 'shopping'` with the
   nearest real `ItemKind` value (`attraction` for both, per Requirements — a beach or
   shopping stop is still an `attraction`-kind item in the real enum, it's the label
   text that would say "Beach"/"Shopping" if the backend ever added a `title`/category
   field, which it doesn't; the badge in Phase 5 reads `kind`, not free text).
2. `cd frontend && npx tsc --noEmit` — must be clean.
3. `npm run lint` — fix any oxlint findings introduced by this plan's changes (do not
   silence unrelated pre-existing lint debt outside this plan's scope).
4. `npm run build` — must succeed; check the build output size didn't balloon
   unexpectedly (sanity check, not a hard budget).
5. Follow the project's `run` capability (or `npm run dev` directly + `npm run mock`) to
   launch the app in a browser against the now-fixed mock fixture.
6. Walk the verification matrix above at desktop width, screenshotting each state and
   comparing against the matching `assets/*.png`.
7. Resize to 360px (or use browser device emulation) and repeat — confirm no horizontal
   scroll, no clipped text, composer and buttons remain usable.
8. Confirm via `grep -rL "disabled" ...` sanity checks (or manual click-through) that
   every chrome-only control added in phases 2, 5, 6 (Explorer/Concierge tabs, Ideas
   tab, `+` day pill, map filter pills/tools/search, header edit/share icons,
   notification/help icons) is genuinely non-interactive, not just styled to look
   disabled.
9. File a short punch-list of any deviations found (visual or behavioral) and fix them
   in the owning phase's files before marking this phase — and the plan — complete.

## Success Criteria

- [x] `frontend/mock/server.js`'s fixture has real dates and only real `ItemKind` values.
- [x] `npx tsc --noEmit`, `npm run lint`, `npm run build` all pass.
- [x] Zero `.jsx`/`.js` files remain in `components/`, `hooks/`, `api/`.
- [x] Full chat → hotel selection → itinerary → reset flow verified working end-to-end (real backend + mock).
- [x] No horizontal scroll at desktop widths.
      **Deviation logged, accepted by user as out of scope:** at 360px, `ItineraryPanel`
      (`w-[420px]`) and `MapPanel` render fully off-screen (only `ChatPanel` is usable) —
      verified via an in-page iframe workaround since the browser tool's resize did not
      constrain the actual viewport. Confirmed via `git show HEAD` this fixed-width
      layout predates this plan (Phases 1-6 did not change these widths); no Stitch
      reference shows a mobile layout either. User decision: accept as a pre-existing
      limitation, file as a follow-up rather than expand this plan's scope.
- [x] All 4 screens visually compared against `assets/*.png`; deviations logged and resolved
      (deliberate Decision-2 omissions: DeepDive Thinking, photo thumbnails, View Map,
      fake skeleton states — confirmed absent).
- [x] Every chrome-only/decorative control confirmed non-interactive by testing (programmatic
      DOM audit: 12 candidate controls, all `disabled: true`, `hasOnClick: false`).

## Risk Assessment

- **Risk:** "looks right" visual review misses a control that's styled `disabled` but
  still has a working `onClick` left over from copy-pasting a functional component
  (e.g. copying `HotelOptionCard`'s button and forgetting to strip its handler for a
  chrome-only twin). **Mitigation:** Step 8 explicitly requires testing interactivity,
  not just appearance.
- **Risk:** hand-fixing the mock fixture's `kind` values could itself drift from the
  real enum again later. **Mitigation:** out of scope to prevent structurally (e.g. a
  shared fixture-validation script) — this phase's fix is a point-in-time correction,
  not a guarantee against future drift; acceptable for a dev-only mock.
