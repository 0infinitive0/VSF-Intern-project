---
phase: 4
title: "Frontend form component"
status: completed
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 4: Frontend form component

## Overview

Build a new `IntakeParametersForm` component — the interactive replacement for
sequential intake Q&A. Does not touch the existing read-only `TripParametersCard`
(kept as-is for the `hotel_options` stage, per the already-completed Stitch UI plan).

## Requirements

- Functional: new component `frontend/src/components/intake-parameters-form.tsx`,
  props: `{ intake: IntakeStatus | null, onSubmit: (message: string) => void,
  disabled: boolean }`.
- Functional: fields, all optional except destination/dates/guests (mirrors backend
  `is_complete`):
  - Destination — `<select>` populated from `intake.available_destinations` (real
    list from Phase 2, never hardcoded).
  - Dates — start date input + duration (days) number input (matches existing
    `TripIntakeState.duration`/`start_date` shape; do not build a date-range picker
    that implies a different backend contract).
  - Guests — number stepper (people count).
  - Budget & accommodation — single-select chips from `intake.budget_options` (real
    list from Phase 2 — the 4 existing tier labels, not a fabricated Standard/
    Premium/Luxury set).
  - Preferences (travel style) — multi-select chips, values = the 10-label
    `_PREFERENCE_LABELS` set (Phase 2) — hardcode this list in `strings.ts` as
    Vietnamese display text (not fetched — it's a fixed closed set, same treatment
    the backend gives it).
  - Travel companions — single-select chips, 5 fixed Vietnamese labels (Phase 2).
  - Pace — single-select chips, 3 fixed Vietnamese labels (Phase 2).
  - Day's rhythm — multi-select chips, 2 fixed Vietnamese labels (Phase 2).
  - Other needs — `<textarea>`, 1000-char hard limit with a live counter.
- Functional: pre-fill every field from `intake.*` when non-null/non-empty (a user
  who already answered some questions via plain chat before the form loads must not
  be asked to redo them).
- Functional: on submit, compose ONE Vietnamese sentence enumerating every filled
  field (template function in a new `frontend/src/lib/compose-intake-message.ts`,
  unit-testable in isolation) and call `onSubmit(message)`. Do not send structured
  JSON — the backend only accepts free text (Phase 2/3 decision).
- Functional: submit is disabled while `disabled` prop is true (mirrors existing
  `pending` semantics from `use-chat-session.ts`) and while destination/dates/guests
  are unset (required-field validation, client-side only — server-side grounding is
  still authoritative).
- Non-functional: visual style matches the existing `trip-parameters-card.tsx`
  surface treatment (`bg-surface-background border border-outline-variant rounded-xl
  p-4`) and the rest of `frontend/src/styles.css` tokens — this is an extension of
  the already-completed Stitch redesign, not a new visual language.
- Non-functional: all UI copy in Vietnamese, added to `strings.ts` alongside existing
  `tripParams*` keys.

## Architecture

```
IntakeParametersForm
├── DestinationSelect      (from intake.available_destinations)
├── DateAndGuestsFields    (start_date, duration, people)
├── BudgetChips            (from intake.budget_options)
├── PreferenceChips        (fixed 10-label set)
├── CompanionChips         (fixed 5-label set)
├── PaceChips              (fixed 3-label set)
├── DayRhythmChips         (fixed 2-label set)
├── NotesTextarea          (1000 char cap)
└── SubmitButton → composeIntakeMessage(formState) → onSubmit(message)
```

## Related Code Files

- Create: `frontend/src/components/intake-parameters-form.tsx`
- Create: `frontend/src/lib/compose-intake-message.ts`
- Modify: `frontend/src/types.ts` (extend `IntakeStatus`: `preferences`,
  `companions`, `pace`, `day_rhythm`, `notes`, `available_destinations`,
  `budget_options` — mirror Phase 2's Pydantic schema exactly)
- Modify: `frontend/src/strings.ts` (new Vietnamese labels for every fixed-set
  option + field labels + notes placeholder/counter text)

## Implementation Steps

1. Extend `IntakeStatus` in `types.ts` to match the Phase 2 schema exactly (field
   names 1:1, no renaming).
2. Add the fixed Vietnamese label constants to `strings.ts` (preferences/companions/
   pace/day_rhythm) — these mirror backend closed sets; if a backend label ever
   changes, this file is the one other place to update (call this out as a comment).
3. Write `composeIntakeMessage(formState)`: pure function, one Vietnamese sentence,
   omitting any field that's empty/unset. Unit test it directly (Phase 6 covers this,
   but write the function pure/testable now).
4. Build `intake-parameters-form.tsx` per Requirements, pre-filling from `intake`.
5. `npx tsc --noEmit` — component not wired into the app yet (Phase 5); confirm it
   compiles standalone.

## Success Criteria

- [ ] Component renders every field from Requirements, pre-filled from a sample
      `IntakeStatus` fixture with partial data.
- [ ] `composeIntakeMessage()` omits empty fields and never emits a malformed/
      truncated sentence for any combination of filled/unfilled fields.
- [ ] Notes textarea hard-stops at 1000 characters (matches server-side cap from
      Phase 2 — client cap is UX, not the security boundary).
- [ ] `npx tsc --noEmit` clean.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Fixed Vietnamese label lists in `strings.ts` drift from backend closed sets over time | Add a one-line comment at each list pointing at the backend source-of-truth file:line; Phase 6 can add a lightweight contract test if drift becomes a real problem (not required for this pass) |
| `composeIntakeMessage()` produces a sentence the extraction LLM (Phase 2/3) parses incorrectly | Phase 6 adds a backend test feeding a real composed-message sample through `_llm_extract_intake_facts()` |
| Pre-fill logic double-applies a stale `intake` snapshot after the user has already changed a field locally | Only pre-fill on initial mount / when `intake` reference changes from null → non-null the first time, not on every render |
