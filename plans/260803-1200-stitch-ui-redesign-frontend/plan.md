---
title: "Stitch UI Redesign Frontend"
description: "Rebuild the frontend to match the 4 V-OTA AI Google Stitch screens (full structural adoption) in TypeScript, keeping the interaction model chat-driven and the map panel non-functional."
status: completed
priority: P1
effort: "3.5-4.5d"
tags: [frontend, react, typescript, tailwind, ui-redesign, stitch]
blockedBy: []
blocks: []
created: 2026-08-03
updated: 2026-08-03
---

# Stitch UI Redesign Frontend

## Overview

Rebuild `frontend/src` to match the 4 Google Stitch screens for the `v-ota-chat-ui`
project (assets in `./assets/`): **Starting Chat State**, **Unified Itinerary View**,
**Unified Parameters & Hotel Selection**, **Unified Detailed Itinerary Chat**.

**Decisions locked in with the user before this plan was written:**

1. **Full structural rebuild** — adopt Stitch's regions (top nav, tabbed itinerary
   panel, restyled image-style hotel/day cards, map chrome), not just a color/typography
   reskin.
2. **Backend-gap handling: static chrome, same precedent as `MapPanel`** — any screen
   element with no backing data in the current contract
   (`{reply, suggestions, hotel_options, trip_plan, stage}`) is rendered as inert/static
   chrome, never fabricated data. Concretely:
   - Top-nav tabs **Explorer** / **Concierge** — visible, `disabled`, no click handler.
     Only **Trips** is active (it *is* the app).
   - The Stitch "DeepDive Thinking" reasoning-trace list (fake step-by-step checkmarks)
     is **not built**. The existing `ElapsedSpinner` (real elapsed time, no fabricated
     steps) is kept and restyled instead — it is already honest.
   - Hotel/activity photo thumbnails → a neutral Material Symbols placeholder icon in an
     image-shaped slot, never a fake/stock photo.
   - Itinerary panel's **Ideas** tab — visible, `disabled`.
   - Trip Parameters card shows only fields the backend already returns:
     `destination`, `start_date`, `end_date`, `number_of_adults`, `duration_days`
     (verified in `src/services/trip_formatter.py:291-297`). **Budget Style** and
     **preference chips** (Cultural/Foodie/Relax/Nature) from the Stitch mock have no
     backend field — omitted, not fabricated.
   - Per-activity "View Map" links — omitted (no per-activity coordinates; only
     `hotel.coordinates` exists, and the map itself is deferred — see Decision 3).
3. **Map panel stays a placeholder** — restyle its chrome (search bar, filter pills,
   zoom controls) to match the new design, but it remains non-interactive. No map
   library, no tiles, no pins. This is an explicit continuation of the current
   `MapPanel` docstring ("No map data source is wired up yet").
4. **No backend changes.** This is a `frontend/` only plan. Every field referenced above
   was verified against `src/services/trip_formatter.py` before writing this plan.
5. **TypeScript** — requested mid-plan by the user. The project currently has zero TS
   setup (no `tsconfig.json`, no `typescript` package; `@types/react`/`@types/react-dom`
   are present but unused). Since this plan touches every file under `frontend/src/`
   anyway, Phase 1 adds the TS toolchain and every file this plan creates or edits is
   `.tsx`/`.ts`, not `.jsx`/`.js`. Files this plan does not touch stay as-is (none — all
   9 components, the hook, `App.jsx`, `strings.js`, `chat-client.js`, and `main.jsx` are
   in scope across phases 1-6, converted to `.tsx`/`.ts` as each phase lands).

## Design Reference

- Screenshots + full Tailwind/HTML source for all 4 screens: `./assets/`
  (`01-starting-chat-state.*`, `02-unified-itinerary-view.*`,
  `03-parameters-hotel-selection.*`, `04-detailed-itinerary-chat.*`)
- Prior design source the *current* app was built from (for diffing):
  `docs/design/v-ota-chat-ui/DESIGN.md`, `docs/design/v-ota-chat-ui/design.html`
- Current design tokens: `frontend/src/styles.css`
- New Stitch token palette (extracted and cross-checked across all 4
  `./assets/*.html` `<script id="tailwind-config">` blocks — screens 01/02/03 agree,
  screen 04 is an outlier generation): `primary` (`#0047dd`) and `primary-container`
  (`#2c61fe`) are **unchanged** — already correct in `styles.css` today; screen 04's
  divergent `primary: #2c61fe` is a one-off generation artifact and is **not** adopted.
  Net-new tokens (consistent across all 4 screens): `secondary` (`#585e6d`) /
  `secondary-container` (`#dadff0`), `outline` (`#737687`) / `outline-variant`
  (`#c3c5d8`), and a `surface-container` scale (`low` `#f1f3ff` / base `#e9edff`
  already present / `high` `#e2e8fc` / `highest` `#dde2f6`). Fonts unchanged: Hanken
  Grotesk (display) + Inter (body) + Material Symbols Outlined.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Set up TypeScript (tsconfig, toolchain) and extend design tokens to the new Stitch palette without breaking existing components | P1 |
| 2 | Add a top navigation bar (V·OTA AI branding, Trips/Explorer/Concierge tabs, reset action) in TSX | P1 |
| 3 | Restyle the chat ("AI Assistant") panel to the new visual language, converted to TSX | P1 |
| 4 | Restyle hotel option cards and add a real-data Trip Parameters summary, converted to TSX | P1 |
| 5 | Restyle the itinerary panel with tabs (Itinerary active, Ideas disabled) and new day/activity card style, converted to TSX | P1 |
| 6 | Restyle the map panel's chrome while keeping it non-functional, converted to TSX | P2 |
| 7 | Verify visually against the Stitch screenshots, at 360px and desktop, `tsc --noEmit` clean, no regressions | P1 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Design tokens and shared primitives](./phase-01-start.md) | Completed |
| 2 | [Phase 2: Top navigation bar](./phase-02-top-navigation-bar.md) | Completed |
| 3 | [Phase 3: Chat panel restyle](./phase-03-chat-panel-restyle.md) | Completed |
| 4 | [Phase 4: Hotel cards and trip parameters](./phase-04-hotel-cards-and-trip-parameters.md) | Completed |
| 5 | [Phase 5: Itinerary panel restyle](./phase-05-itinerary-panel-restyle.md) | Completed |
| 6 | [Phase 6: Map panel chrome (deferred functionality)](./phase-06-map-panel-chrome-deferred-functionality.md) | Completed |
| 7 | [Phase 7: Verification and responsive check](./phase-07-verification-and-responsive-check.md) | Completed |

## Success Criteria

- [x] All 9 existing `frontend/src/components/*.tsx` files (converted from `.jsx`)
      visually match the Stitch screens' layout, spacing, and card treatments, using
      only real backend data.
- [x] No new fabricated/mock data anywhere (hotel photos, reasoning-trace steps, budget
      preferences) — gaps render as static/disabled chrome per Decision 2.
- [x] Map panel remains functionally identical to today (static placeholder), visually
      restyled.
- [x] App works at desktop widths, no horizontal scroll. At 360px, `ChatPanel` is fully
      usable but `ItineraryPanel`/`MapPanel` render off-screen due to pre-existing fixed
      widths (`w-[420px]` etc.) that predate this plan — accepted by user as an
      out-of-scope, pre-existing limitation (see Phase 7).
- [x] `npx tsc --noEmit`, `npm run lint` (oxlint), and `npm run build` (vite build) all
      pass clean in `frontend/`.
- [x] Manually verified in a running dev server against each of the 4 Stitch screenshots.

## Open Questions

None — scope was resolved via 2 clarifying questions with the user before this plan was
written (see "Decisions locked in" above), plus 1 more during validation (see
`## Validation Log`).

## Validation Log

### Verification Results
- **Tier:** Full (7 phases) — scaled down to a targeted pass on claims flagged
  `[UNVERIFIED]`/risk-noted during authoring, since most file/symbol/field claims were
  already grep/read-verified live while writing each phase (not re-sampled here).
- **Claims checked:** 6 | **Verified:** 5 | **Failed:** 0 | **Confirmed-with-correction:** 1

1. **[Fact Checker]** `oxlint` (v1.76.0) TypeScript support — VERIFIED. `npx oxlint --help`
   confirms a TS plugin enabled by default plus `--tsconfig`/`--type-check` flags.
   Phase 7's `npm run lint` assumption holds.
2. **[Fact Checker]** `@types/react@^19.2.17` vs `react@^19.2.8` — VERIFIED compatible
   (same major, types package ahead is normal/safe).
3. **[Fact Checker]** `S.appTitle` usage sites — VERIFIED, but surfaced a gap: it's used
   in **3** places (`App.jsx:31`, `chat-panel.jsx:16` as an `aria-label`,
   `chat-panel.jsx:21` as visible text), not just the chat panel Phase 3 assumed.
   Phases 2 and 3 both replace its call sites with new copy, which orphans the string
   entirely — propagated to Phase 3 (see below): remove `appTitle` from `strings.ts`
   once both replacements land, and give `chat-panel.jsx`'s `<section aria-label>` an
   explicit new label instead of leaving it silently unset.
4. **[Fact Checker]** Activity `kind` vocabulary (Phase 5's badge mapping) —
   CONFIRMED-WITH-CORRECTION. The authoritative source is
   `src/services/trip_edit_planner.py:31`: `ItemKind = Literal["breakfast", "attraction",
   "lunch", "rest", "coffee", "dinner", "evening"]` (7 values). `reference_type` is a
   separate axis: `Literal["Hotel", "Attraction", "Event"]`
   (`src/services/trip_scheduler.py:88`). Phase 5's draft badge mapping guessed at
   `sight`/`food` labels not in this enum — propagated below.
5. **[Fact Checker]** `frontend/mock/server.js` fixture vs. what Phases 4-5 now depend
   on — FAILED as originally written, now a confirmed, scoped fix (user decision below).
   The fixture has no `start_date`/`end_date` at all, and its `kind` values
   (`beach`, `shopping`) are **not** in the real `ItemKind` enum — it predates both the
   date fields and the real kind vocabulary.
6. **[Fact Checker]** `hotel.coordinates` wire shape — VERIFIED as a `"lat,lng"` string
   (`mock/server.js:37`: `coordinates: '16.0544,108.2022'`), matching `types.ts`'s
   `coordinates?: string | null` from Phase 1 exactly. No change needed.

### Interview
1 question asked (below min-3, per "fewer than min questions is okay" for a plan this
scoped — the rest of the verification findings were direct fixes, not judgment calls).

**Q: Should this plan also fix `frontend/mock/server.js`'s stale fixture (finding #5),
or stay strictly scoped to `frontend/src/`?**
**A: Fix the mock too.** Add start_date/end_date and correct `kind` values to the real
enum, so `npm run mock` stays usable for manually verifying Phases 4, 5, and 7 without
requiring the Python backend running locally.

### Whole-Plan Consistency Sweep
- Files reread: `plan.md`, all 7 `phase-*.md` files.
- Decision deltas checked: 4 (`S.appTitle` orphaning, real `ItemKind` enum, mock fixture
  fix now in scope, `reference_type` enum available as a secondary field).
- Reconciled stale references: 2 (Phase 3's `S.appTitle` handling, Phase 5's guessed
  kind→label mapping — both rewritten below with the verified enum/usage sites).
- Files touched by propagation: `phase-03-chat-panel-restyle.md`,
  `phase-05-itinerary-panel-restyle.md`, `phase-07-verification-and-responsive-check.md`.
- Unresolved contradictions: 0.

### Post-Completion Fidelity Pass (Stitch MCP re-verification)
After all 7 phases landed, re-fetched all 4 screens directly via the Stitch MCP
(`get_screen`) and diffed the returned HTML/screenshots byte-for-byte against the
cached `./assets/*` copies — identical, confirming the plan was built from current
source. Cross-referencing the live HTML against the implementation surfaced 2 real,
low-risk additive gaps (present consistently across multiple screen generations, not
fabricated data, following the established disabled-chrome pattern):
- Chat panel header was missing `more_horiz` + `open_in_full` icon buttons — present in
  all 3 of screens 02/03/04's chat headers. Added as `disabled` chrome in
  `chat-panel.tsx`.
- Itinerary panel tabs were missing a third "Bookings" tab — present in screen 04.
  Added as `disabled` chrome in `itinerary-panel.tsx`, alongside the existing
  disabled "Ideas" tab.

Everything else cross-checked as either already matching or a deliberate,
already-documented Decision-2 omission (DeepDive Thinking, hotel/activity photos, fake
map screenshot, decimal ratings, Budget Style/Preferences chips, "V-OTA Assistant"
caption). Re-ran `tsc --noEmit` / `oxlint` / `vite build` clean after the fixes.

<!-- slug: stitch-ui-redesign-frontend -->
