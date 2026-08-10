---
phase: 6
title: "Tests and verification"
status: completed
priority: P1
effort: "0.75d"
dependencies: [3, 5]
---

# Phase 6: Tests and verification

## Overview

Close the loop: automated coverage for everything Phases 2-5 added, full regression
run, and a manual end-to-end smoke through the running app.

## Requirements

- Functional: backend unit tests for the 4 new `TripIntakeState` fields
  (extraction, grounding rejection of out-of-set values, `to_dict`/`from_dict`
  round-trip, `with_message()` merge semantics) — extend
  `tests/test_trip_intake.py`.
- Functional: backend test asserting `_generate_day_themes()`'s constructed prompt
  contains the new context line when `pace`/`day_rhythm`/`notes` are set (Phase 3
  requirement) and cleanly omits it when unset.
- Functional: backend test asserting `hotel_preferences` on the `recommend_hotels`
  call is populated when `companions`/`notes` are set (Phase 3).
- Functional: session-level test replacing the Phase 1 characterization assertion —
  a single message carrying both complete trip facts and a budget-tier phrase
  reaches `hotel_options` stage in one turn.
- Functional: a backend test feeding a realistic `composeIntakeMessage()`-shaped
  Vietnamese sentence (copy Phase 4's actual template output for a filled-out form)
  through `_llm_extract_intake_facts()` + `_ground_extracted_facts()`, asserting
  every field round-trips correctly — this is the one test that would catch a
  frontend/backend sentence-format mismatch before it reaches production.
- Functional: frontend unit test for `composeIntakeMessage()` covering: all fields
  filled, only required fields filled, one optional field filled at a time.
- Non-functional: full `pytest` clean, `npx tsc --noEmit` / `oxlint` / `vite build`
  clean.
- Non-functional: manual smoke through `npm run dev` (or `npm run mock` if backend
  isn't running locally) — fresh session → form appears → fill every field → submit
  → confirm `hotel_options` renders with hotels plausibly matching the chosen
  budget tier (spot-check price against the tier's real VND threshold from
  `hotel_selection.py`, not just "some hotels appeared").

## Architecture

None — verification phase, no new production code.

## Related Code Files

- Modify: `tests/test_trip_intake.py`
- Modify: `tests/test_agents/test_supervisor.py` or a new
  `tests/test_api/test_chat_flow.py` addition, whichever already covers full-turn
  flows (confirm which, in Implementation Steps)
- Create: `frontend/src/lib/compose-intake-message.test.ts` (match whatever test
  runner `frontend/package.json` already uses — confirm before creating; do not
  introduce a new test framework)

## Implementation Steps

1. Check `frontend/package.json` for the existing test runner (Vitest/Jest/none) —
   if none exists, flag this as a decision point rather than silently adding a new
   toolchain (this repo's plans avoid unscoped tooling additions).
2. Add the backend unit tests listed in Requirements to
   `tests/test_trip_intake.py`.
3. Add the session-level one-turn-resolution test — reuse the Phase 1
   characterization test's session-setup helper if one exists.
4. Add the `_generate_day_themes()` prompt-content test and the `hotel_preferences`
   test to whichever file already covers `trip_planner.py`/`recommend_hotels.py`
   (confirm exact file via grep, don't create a new one if one already fits).
5. Add the composed-message round-trip test.
6. Run full `pytest`; run `npx tsc --noEmit && npx oxlint && npm run build` in
   `frontend/`.
7. Manual smoke per Non-functional requirement above; capture the exact hotel
   price(s) returned and the tier threshold used, note both in the plan's
   Validation Log for a real (not asserted-blind) confirmation.

## Success Criteria

- [ ] All new tests pass; all pre-existing tests still pass (`pytest` exit 0).
- [ ] `npx tsc --noEmit`, `oxlint`, `vite build` all exit 0.
- [ ] Manual smoke completed with the actual returned hotel price(s) recorded
      against the chosen tier's real threshold (not assumed).
- [ ] If no frontend test runner exists, this is called out explicitly rather than
      silently skipped or silently adding new tooling.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| No frontend test runner exists yet, quietly inflating this plan's scope with a new toolchain decision | Step 1 surfaces this early; if true, `composeIntakeMessage()` still ships (it's pure and small — Phase 4 already wrote it defensively) but its test is deferred to a follow-up, noted in this phase's Success Criteria as a known gap rather than silently dropped |
| Manual smoke passes locally but the real Supabase-backed price data differs enough from `hotel_selection.py`'s hardcoded tier thresholds to make the "plausibly matching" check meaningless | Record the actual numbers seen (step 7) so a reviewer can judge fit rather than trusting an unverified pass/fail |
