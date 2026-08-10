---
title: "Trip Parameters Intake Form"
description: "Replace the sequential chat-driven intake Q&A with a single always-shown Trip Parameters form (dates, guests, destination, budget/accommodation tier, travel-style taxonomy, free-text notes) submitted as one composed message through the existing chat endpoint."
status: pending
priority: P1
effort: "4-5d"
tags: [frontend, backend, react, typescript, python, langgraph, intake, ux]
blockedBy: []
blocks: []
created: 2026-08-03
updated: 2026-08-03
---

# Trip Parameters Intake Form

## Overview

Today, `intake` stage collects trip facts one question at a time via free-text chat
(`TripIntakeState.next_question()` in `src/services/trip_intake.py`), then — once those
4 facts are complete — asks one more sequential question for a hotel budget tier
(`HotelPreferenceState.next_question()` in `src/services/hotel_selection.py`), before
finally calling `recommend_hotels` and moving to `hotel_options` stage. The frontend's
current `TripParametersCard` (`frontend/src/components/trip-parameters-card.tsx`) is a
**read-only** summary shown only once these facts already exist.

This plan replaces that sequential Q&A with a single interactive form, shown
immediately when `stage === 'intake'`, collecting all trip-planning facts in one
submission. The form composes one natural-language Vietnamese message from the
selected fields and sends it through the existing chat endpoint exactly like a typed
message — no new API/endpoint.

## Decisions locked in with the user before this plan was written

1. **Trigger:** always show the form at the start of `intake` — not gated on any
   keyword detection.
2. **Budget:** the user asked for "a budget range," not a Standard/Premium/Luxury
   label. Codebase research found this **already exists as a real backend feature**
   post-Stitch-UI-plan: `HotelPreferenceState` (`hotel_selection.py:503-585`) is a
   3-tier + skip guided budget question with real VND thresholds (`Tiết kiệm` /
   `Tầm trung` / `Cao cấp` / `Bỏ qua`), already deterministically wired into
   `recommend_hotels`'s `target_price`/`min_price`/`max_price` args
   (`session.py:758-763`). **This supersedes the prior Stitch-UI-plan decision** ("no
   backend field for Budget Style") — that was true when written, the codebase has
   since grown this feature. Reused as-is, not rebuilt.
3. **Preferences taxonomy** — the user pasted a 6-category taxonomy (companions,
   travel style, pace, accommodation, day's rhythm, free-text notes). Resolution per
   category, evidence-based:
   - **Accommodation (Comfort/Premium/Luxury) merges into Budget** (decision 2) — it's
     the same axis as the existing 3 price tiers. One selector, not two.
   - **Travel style (Cultural/Classic/Nature/Cityscape/Historical)** merges into the
     **existing** `preferences` field (`_PREFERENCE_LABELS`,
     `trip_intake.py:30-39`) — 3 of 5 requested options are already in that closed
     set (`văn hóa`, `thiên nhiên`, `lịch sử`). Add 2 new labels (`cổ điển`,
     `cảnh đô thị`) to cover Classic/Cityscape rather than fork a parallel field.
     `preferences` already flows into itinerary theme generation
     (`trip_planner.py:172`) and itinerary-reuse fingerprinting
     (`itinerary_reuse.py:114-129`) — reused, not rebuilt.
   - **Companions, pace, day's rhythm, notes** are genuinely new — no existing field.
     Added as new optional `TripIntakeState` fields (Phase 2).
   - Effect: per the user's answer, the new taxonomy must have a **real** effect —
     injected into the itinerary day-theme generation prompt
     (`trip_planner.py:_generate_day_themes`) as additional context, and `companions`
     additionally feeds the dormant `hotel_preferences` argument on `recommend_hotels`
     (never populated by any deterministic caller today — grep-verified), which the
     existing amenity-tag reranker already matches against (`family` tag matches
     "gia dinh"/"tre em" — `hotel_selection.py:592`). No new hard filter logic.
4. **Submission mechanism:** no new endpoint. The form composes one Vietnamese
   sentence from every filled field and calls the existing `sendMessage()`
   (`chat-client.ts:60`) exactly like a typed message. Backend extraction
   (`_llm_extract_intake_facts`) is extended to parse the new fields out of that
   sentence.
5. **UI copy stays Vietnamese**, matching every existing string in `strings.ts` and
   every backend-facing label. The user's pasted taxonomy used English category names
   as the *concept* source (Solo/Family/Couple/Friends/Elderly, etc.) — the shipped UI
   text is Vietnamese, mapped 1:1 (mapping table in Phase 2).
6. **Destination becomes a form field**, not a separate first chat question. The
   Stitch mockup omitted it, but `next_question()` requires destination first and it's
   a required fact — dropping it from the form would silently break intake. Rendered
   as a picker backed by the real `_get_destination_names()` list (already used
   server-side for grounding), newly exposed to the frontend — a real list, not
   free-typed guesswork.
7. **Scope: HOLD** (scope-challenge outcome) — implement exactly what's above,
   execute it solidly with tests, no further expansion, no reduction.

## Architecture

```
Frontend form (one submit)
  → composes 1 Vietnamese sentence from: destination, dates, guests, budget tier,
    preferences (existing + 2 new labels), companions, pace, day_rhythm, notes
  → sendMessage() [UNCHANGED endpoint] → POST /api/v1/planner_chat {session_id, message}
    → process_chat_turn() → _run_intake()  [session.py:736]
       1. session.intake_state.with_message(...)   — destination/duration/start_date/
          people/preferences(+2 labels)/companions/pace/day_rhythm/notes
       2. NEW: same-turn carry-through into session.hotel_pref_state.with_message(...)
          instead of deferring to next turn (Phase 3 fix)
       3. recommend_hotels.invoke({**intake_state.tool_arguments(),
                                    **hotel_pref_state.tool_arguments()})
          — tool_arguments() extended to also emit hotel_preferences (companions+notes)
    → response: stage, hotel_options, intake (extended: preferences, companions, pace,
      day_rhythm, notes, available_destinations, budget_options)
  → frontend renders hotel_options (existing, unchanged component)
```

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Extend `TripIntakeState`/`IntakeStatus` with companions/pace/day_rhythm/notes + 2 new preference labels; expose destination list + budget tier options to the frontend | P1 |
| 2 | Fix `_run_intake()` to resolve intake facts + hotel budget in one turn when one message answers both; wire companions/notes into `hotel_preferences`; inject new taxonomy into itinerary theme generation | P1 |
| 3 | Build an interactive `IntakeParametersForm` component (destination, dates, guests, budget/accommodation, preferences, companions, pace, day's rhythm, notes) | P1 |
| 4 | Always render the form during `intake` stage (replacing free-text sequential Q&A), pre-filled from already-known facts, submitting via the existing send path | P1 |
| 5 | Regression-safe: existing `next_question()`/chip/test contracts keep working for any message that doesn't come through the form | P1 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Safety-net characterization tests](./phase-01-start.md) | Pending |
| 2 | [Phase 2: Backend intake state and schema](./phase-02-backend-intake-state-and-schema.md) | Pending |
| 3 | [Phase 3: Backend generation wiring](./phase-03-backend-generation-wiring.md) | Pending |
| 4 | [Phase 4: Frontend form component](./phase-04-frontend-form-component.md) | Pending |
| 5 | [Phase 5: Frontend intake-stage wiring](./phase-05-frontend-intake-stage-wiring.md) | Pending |
| 6 | [Phase 6: Tests and verification](./phase-06-tests-and-verification.md) | Pending |

## Success Criteria

- [ ] One form submission with destination + dates + guests + budget tier +
      preferences + companions + pace + day's rhythm + notes reaches `hotel_options`
      stage in a single turn (no follow-up budget question needed).
- [ ] A form submission that omits an optional field (companions/pace/day_rhythm/notes)
      still completes normally — nothing new is required.
- [ ] The new taxonomy demonstrably changes output: a day-theme generation call made
      with `notes`/`pace`/`companions` set produces a prompt that includes them
      (asserted in tests), and `companions="đi cùng gia đình"` demonstrably sets
      `hotel_preferences` to include "gia đình" on the `recommend_hotels` call.
- [ ] Existing `tests/test_trip_intake.py` assertions (next_question ordering,
      preference validation/rejection, `is_complete` excludes optional fields) still
      pass unmodified in intent (label set changes are additive).
- [ ] `npx tsc --noEmit`, `oxlint`, `vite build` clean in `frontend/`.
- [ ] Full `pytest` clean.
- [ ] Manual smoke: fresh session → form appears immediately at `intake` →
      fill everything → submit → hotel_options renders with hotels plausibly filtered
      by the chosen budget tier.

## Open Questions

None blocking — the destination-field addition (item 6 above) and the budget/
accommodation merge (item 3) are locked decisions made from source evidence during
research, per project convention (Scout First / Verified Decisions). Flag during
`/ak:plan validate` if either needs revisiting.

<!-- slug: trip-parameters-intake-form -->
