---
phase: 6
title: "extract_patch node"
status: pending
priority: P1
effort: "2d"
dependencies: [5]
---

# Phase 6: extract_patch node

## Overview

Replace three separate LLM extraction calls with one node that emits **intent *and* a validated
state patch in a single call**. Makes the Phase 3 patch layer the authoritative writer.

This node is doc §36's `understand_request.py` — *"Intent/extraction + deterministic
validation"*. The name `extract_patch` is kept because it is already wired through Phases 5-14;
the substance that matters is **one LLM call, not two**.

**Why intent and extraction share one call.** They read the same message and the same state.
Splitting them costs a second round-trip on a local model to re-derive what the first call
already knew, and creates two places where the turn can be misread. Doc §36 merges them for the
same reason; §10 and §35 still show them split, but those sections predate §36 and were not
updated with it.

Note what intent is **not** used for: it never selects a worker. Worker selection is
`detect_impact(changes)` → `WORKFLOW_TO_WORKER` (Phase 5), a table lookup on the validated
patch. `intent` only distinguishes read-only Q&A from state-changing turns, and feeds the audit
trail.

## Problem

Three LLM calls extract overlapping facts with different schemas, different failure modes,
and no shared validation:

| Call | Location | Fails to |
|---|---|---|
| `_llm_extract_intake_facts` | `trip_intake.py:427` | `{}` — caller silently re-asks the same question |
| `TripPreferenceUpdate.from_message` | `trip_intake.py:159` | raises `TripPreferenceUpdateError` |
| `plan_trip_edit` | `trip_edit_planner.py:452` | raises `TripEditPlanError` after one retry |

They can also be invoked twice in one turn (`session.py:1188` carries an explicit comment
about avoiding exactly that). And the edit-planner prompt has a **rule collision**:
`trip_edit_planner.py:442` routes a day theme to `replan_day`, while `:445` routes
"vibe/preferences" to `update_trip_preferences` — and "thiên nhiên" is listed verbatim in
the `:445` vibe list. A model that picks `:445` returns
*"Mình đã cập nhật sở thích chuyến đi..."* and never touches the itinerary. That is an
independent second path to the day-1-theme symptom.

## Requirements

- Functional: one LLM call per turn produces `{intent, changes[]}`; changes validate through
  `apply_patch`.
- Functional: an already-`SET` slot can be corrected — the first-non-null-wins trap
  (`trip_intake.py:296`) is gone. Fixes the "01/07 is permanently wrong" half of that bug.
- Functional: a day-scoped phrase ("ngày 1", "hôm đầu", "ngày cuối") always resolves to a
  `daily_preferences.N.theme` path, never to trip-level `preferences.themes`.
- Functional: invalid or unparseable model output falls back to `decide_route_by_rules`
  and the turn still completes.
- Non-functional: no more than one extraction call per turn.
- Non-functional: destination grounding stays deterministic — `_match_known_destination`
  remains authoritative; the model never invents a supported city.

## Architecture

New node `backend/src/agents/nodes/extract_patch.py`.

Output contract:

```json
{
  "intent": "hotel_search | update_itinerary | update_trip | select_hotel | finalize | general_question",
  "changes": [
    {"path": "daily_preferences.1.theme", "operation": "set", "value": "thiên nhiên"},
    {"path": "budget.max", "operation": "set", "value": 8000000}
  ]
}
```

Defensive parsing reuses the shape `plan_trip_edit` already proves in production: strict
JSON parse → schema validate → retry once with the rejection reason → fall back. Not a new
pattern; the same one, applied in one place instead of three.

**Day-scope resolution is deterministic, not model-decided.** A regex pass extracts the day
scope (`parse_day_scope` already exists in `trip_scheduler.py`) and rewrites the path before
validation. This removes the `:442`/`:445` prompt collision by construction rather than by
prompt wording — the model no longer chooses between the two.

Grounding stays layered exactly as today: model proposes → pure function validates
(`_ground_extracted_facts`'s established contract) → `apply_patch` enforces the allow-list.

## Related Code Files

- Create: `backend/src/agents/nodes/extract_patch.py`
- Create: `backend/tests/test_extract_patch.py`
- Modify: `backend/src/services/trip_intake.py` — `_llm_extract_intake_facts` becomes internal to the node
- Modify: `backend/src/services/trip_edit_planner.py` — drop the `:442`/`:445` collision; keep operation planning for post-plan edits
- Modify: `backend/src/agents/session.py` — `direct_preference_update` block (`:713-753`) consumes patches

## Implementation Steps

1. Write the patch-extraction prompt and JSON schema; keep the closed label sets from
   `trip_intake.py:32-66` as the grounding vocabulary.
2. Implement deterministic day-scope rewriting using `parse_day_scope` before validation.
3. Implement strict parse + retry-once + fallback-to-rules.
4. Route `_llm_extract_intake_facts` callers through the node; delete the double-call hazard.
5. Remove the day-theme branch from the edit-planner prompt (day scope no longer reaches it).
6. Table-test extraction against the doc §34 case list: `01/07`, `01/07/2027`, `Ngày đầu`,
   `Ngày 1`, `Cái thứ 2`, `Budget 10 triệu`, `Budget còn 8 triệu`, `Dưới 2 triệu/đêm`,
   `Trong vòng 3km`, `Có gym`, `Ngày 1 nature`, `Giữ nguyên ngày 2`.
7. Verify one extraction call per turn by counting LLM invocations in a test double.

## Success Criteria

- [ ] "ngày 1 thiên nhiên" always yields `daily_preferences.1.theme`, never `preferences.themes`
- [ ] A previously-set `dates.start` can be corrected by a later message
- [ ] Malformed model output completes the turn via rules fallback, no exception surfaces
- [ ] Exactly one extraction LLM call per turn, asserted by test
- [ ] All doc §34 phrases produce the expected patch (table test)
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| llama3.1 emits invalid JSON patches | Strict parse + retry-once + rules fallback — the exact shape `plan_trip_edit` already runs in production. Measured in Phase 10 as State Patch Accuracy |
| One prompt covering all intents degrades vs three specialized ones | Table test is the gate. If accuracy drops, split extraction from intent classification — two calls is still fewer than three |
| Removing edit-planner day-theme branch breaks post-plan replan | Day scope is rewritten to a path *before* the planner runs; `replan_day` still executes, it is just no longer the model's choice to make |
| Correctable slots let a stray extraction clobber a confirmed fact | `operation: set` on an already-`SET` slot is logged to the Phase 10 audit trail; Phase 7 adds confirmation for high-cost fields (dates, destination) |
