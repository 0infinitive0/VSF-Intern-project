---
phase: 2
title: "Backend intake state and schema"
status: completed
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Backend intake state and schema

## Overview

Extend `TripIntakeState` with the genuinely-new taxonomy fields, extend
`_PREFERENCE_LABELS` with 2 travel-style labels, and expose everything the frontend
form needs (current values, destination list, budget tier options) through
`IntakeStatus`/`PlannerChatResponse`. No generation-side wiring yet (Phase 3).

## Requirements

- Functional: add optional fields to `TripIntakeState`
  (`src/services/trip_intake.py:200-206`): `companions: str | None`,
  `pace: str | None`, `day_rhythm: tuple[str, ...] = ()`, `notes: str = ""`. None of
  these participate in `is_complete` (same pattern as existing `preferences`).
- Functional: extend `_PREFERENCE_LABELS` (line 30-39) with `"cổ điển"` and
  `"cảnh đô thị"` (covers Classic/Cityscape from the user's taxonomy; Cultural/
  Nature/Historical already map to `"văn hóa"`/`"thiên nhiên"`/`"lịch sử"`).
- Functional: closed sets for the new fields (define as module constants next to
  `_PREFERENCE_LABELS`, same style):
  - `_COMPANION_LABELS`: `"đi một mình"`, `"đi cùng gia đình"`,
    `"đi cùng người yêu hoặc vợ chồng"`, `"đi cùng bạn bè"`,
    `"có người lớn tuổi trong đoàn"` (Solo/Family/Couple/Friends/Elderly).
  - `_PACE_LABELS`: `"dày đặc"`, `"vừa phải"`, `"thư thái"` (Ambitious/Moderate/
    Relaxed).
  - `_DAY_RHYTHM_LABELS`: `"bắt đầu sớm"`, `"về khuya"` (Early starts/Late nights).
  - `notes`: free text, no closed set — sanitize by `.strip()[:1000]`.
- Functional: extend `_llm_extract_intake_facts()`'s prompt schema
  (trip_intake.py:354-362) with 4 new optional keys: `companions`, `pace`,
  `day_rhythm` (array), `notes` (string). List the closed-set choices in the prompt
  text exactly like `preference_labels` already does.
- Functional: extend `_ground_extracted_facts()` (line 390-405) to validate the 4 new
  keys against their closed sets (same `tuple(label for label in SET if label in
  label_set)` pattern for `day_rhythm`; single-value match-or-None for `companions`/
  `pace`); truncate/strip `notes`.
- Functional: extend `TripIntakeState.with_message()` (line 223-262) to merge the new
  fields the same way `preferences` is merged (companions/pace: first non-null wins;
  day_rhythm: union; notes: last non-empty wins — a later message's notes replace
  earlier notes rather than concatenating, since notes are meant to be one coherent
  block from one form submission).
- Functional: extend `to_dict()`/`from_dict()` (line 300-322) and `tool_arguments()`
  (line 288-298) with the new fields. `tool_arguments()` should NOT raise if optional
  fields are unset — only the 4 required facts gate `is_complete`.
- Functional: extend `IntakeStatus` (`src/models/schemas.py:127-138`) with:
  `preferences: list[str]`, `companions: str | None`, `pace: str | None`,
  `day_rhythm: list[str]`, `notes: str`, `available_destinations: list[str]`,
  `budget_options: list[str]`. Update `IntakeStatus.from_state()` (line 141+) to read
  these off `intake_state` plus a new `hotel_pref_state` argument (signature change —
  find and update every call site, expected: `src/api/routes.py`).
- Functional: `available_destinations` sourced from the same
  `_get_destination_names()` (`trip_planner.py`) already used server-side for
  grounding — a real, current list, not a fabricated/frozen one.
- Functional: `budget_options` sourced from `_BUDGET_QUESTION.options` labels
  (`hotel_selection.py:476-498`) — export a small helper (e.g.
  `budget_option_labels() -> tuple[str, ...]`) rather than reaching into the private
  constant from `schemas.py`.
- Non-functional: every new field name/label constant is grep-verified before use —
  do not introduce a name that collides with an existing one.

## Architecture

```
TripIntakeState (trip_intake.py)
  + companions, pace, day_rhythm, notes            [new optional fields]
  _PREFERENCE_LABELS + 2                            [extended closed set]
  _llm_extract_intake_facts()                       [extended JSON schema]
  _ground_extracted_facts()                         [extended validation]
  with_message() / to_dict() / from_dict() /
  tool_arguments()                                  [extended, same shape]

IntakeStatus.from_state(intake_state, hotel_pref_state)   [schemas.py — extended]
  + preferences, companions, pace, day_rhythm, notes
  + available_destinations   ← trip_planner._get_destination_names()
  + budget_options            ← hotel_selection.budget_option_labels()  [new helper]
```

## Related Code Files

- Modify: `src/services/trip_intake.py`
- Modify: `src/services/hotel_selection.py` (add `budget_option_labels()` helper)
- Modify: `src/models/schemas.py`
- Modify: `src/api/routes.py` (pass `hotel_pref_state` into `IntakeStatus.from_state()`)
- Modify: `tests/test_trip_intake.py` (extend fixtures/assertions for new fields —
  additive only, do not delete existing assertions)

## Implementation Steps

1. Add the 3 new closed-set constants + extend `_PREFERENCE_LABELS` in
   `trip_intake.py`.
2. Add the 4 new fields to `TripIntakeState`, plus `to_dict`/`from_dict`/
   `tool_arguments`.
3. Extend the extraction prompt (JSON schema block) and `_ground_extracted_facts()`.
4. Extend `with_message()` merge logic for the 4 new fields.
5. Add `budget_option_labels()` to `hotel_selection.py`, returning the exact option
   label strings from `_BUDGET_QUESTION.options` (no duplication of the tier
   thresholds — read them from the existing constant).
6. Extend `IntakeStatus` + `from_state()` in `schemas.py`; update the one call site in
   `routes.py` to pass `session.hotel_pref_state`.
7. Run `pytest tests/test_trip_intake.py -v` — fix any signature-change fallout.

## Success Criteria

- [ ] `TripIntakeState` round-trips all 8 fields through `to_dict()`/`from_dict()`.
- [ ] `_ground_extracted_facts()` rejects an out-of-set value for
      `companions`/`pace`/`day_rhythm` (mirrors existing preference-rejection test).
- [ ] `IntakeStatus.from_state()` returns real, current `available_destinations` and
      `budget_options` (no hardcoded copy of either list).
- [ ] All pre-existing `test_trip_intake.py` tests still pass.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| `IntakeStatus.from_state()` signature change breaks an untraced call site | Grep `from_state(` across the repo before editing, fix every call site in this phase |
| New Vietnamese labels collide with existing free-text parsing (e.g. "về khuya" also meaning something in date parsing) | Grep the exact string across `trip_intake.py`/`trip_planner.py` before adding; closed-set grounding already isolates these from destination/date parsing |
| `notes` free text leaking unsanitized into a downstream prompt (injection-style prompt manipulation) | Truncate to 1000 chars only in this phase; Phase 3 must treat it as untrusted context text, not as instructions |
