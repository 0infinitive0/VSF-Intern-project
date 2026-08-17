---
phase: 11
title: "CUTOVER — flip default, delete the old plane"
status: completed
priority: P1
effort: "2d"
dependencies: [8, 9, 10]
---

# Phase 11: CUTOVER — flip default, delete the old plane

## Overview

Make `orchestrator=graph` the default, then **delete** the legacy plane. This is the phase where
"one control plane" becomes true rather than intended. Point of no return.

## Gate — do not start until all four hold

| Gate | Evidence |
|---|---|
| Phase 10 State Patch Accuracy recorded under `orchestrator=graph` | baseline committed |
| `eval/` end-to-end ≥ committed `eval/results/baseline.json` under `graph` | timestamped report |
| Full suite green under `orchestrator=graph` | CI run |
| Every guard listed below has a behavior test **before** deletion | test file merged |

If any gate fails, this phase does not start. The flag stays on `legacy` and the failing flow
goes back to its phase.

## The knowledge-preservation rule

The regex guards being deleted are **hard-won knowledge**, not clutter. Each encodes a real
model failure someone paid to discover. Deleting the code is correct; losing the knowledge is not.

**Every guard gets a test asserting its behavior before its code is removed.** The test survives
the deletion and now asserts the graph produces the same outcome by a different mechanism.

| Guard | Knowledge it encodes | Test must assert |
|---|---|---|
| `_new_trip_signal` day-scope regex | "3 ngày 2 người" was read as "edit day 2" | that phrase starts a trip, never edits day 2 |
| `recommend_hotels` anti-loop (`:121`) | model re-called the tool with identical args | a repeated identical search does not loop |
| `_looks_like_textual_tool_call` | model emitted tool-call JSON as prose | JSON-looking prose is never shown to the user |
| `_looks_like_budget_change` / `_looks_like_hotel_change` | edit planner failed to classify budget changes | "ngân sách tối đa 300k" reaches the hotel flow |
| `_is_hotel_choice_attempt` | a bare out-of-range number is still a pick attempt | "9" against a 5-item list re-asks, not topic-changes |
| `_is_generic_trip_information_change` | frontend's generic edit button label | that exact label asks which field |
| `_unsupported_destination_reply` | naming an unsupported city fell into the edit planner | "đi Hội An" names supported destinations |
| **`validate_route` / `_IMPOSSIBLE`** (`routing_decision.py:174-189`) | a *valid* route label can still be an *impossible* action — editing with no trip, finalizing a finalized trip | the supervisor's `_IMPOSSIBLE` guard (Phase 5) rejects the same two cases plus `booking_node`, and re-routes instead of executing |

`MIN_PLAUSIBLE_PRICE_VND` and `_sanitize_price` are **not** deleted — they live in the tool and
domain layer, which survives.

## Deletion inventory

| Target | Size |
|---|---|
| `src/agents/routing_decision.py` | 189 |
| `src/agents/supervisor.py` | 108 |
| `session.py`: `_process_chat_turn`, `_decide_route`, `_run_intake`, `_run_edit_draft`, `_run_chat_agent`, `_run_finalize`, `_run_recommend_hotels`, `_begin_new_trip_if_requested`, `_looks_like_trip_preference_change`, `_looks_like_budget_change`, `_looks_like_hotel_change`, `_is_generic_trip_information_change`, `_looks_like_textual_tool_call`, `_unsupported_destination_reply`, `_recommend_preference_replacement`, `_start_trip_preference_update`, `execute_trip_edit_request` | ~900 |
| `trip_intake.py`: `TripPreferenceUpdate`, `TripIntakeState.with_message` | ~200 |
| `hotel_selection.py`: `HotelPreferenceState.with_message` | ~50 |
| `graph.py`: `_ToolAdapter`, `SessionTools`, whole file | ~100 |

≈ **1,400 LOC**. `session.py` 1656 → ~400: `TripSession`, `SessionRegistry`, persist hooks only.

`src/agents/graph_v2/` is renamed to `src/agents/graph/` in the same phase — the `_v2` suffix is
scaffolding and must not outlive it.

## Requirements

- Functional: `orchestrator` default becomes `graph`; `legacy` remains selectable for one
  release, then the flag itself is removed.
- Functional: after deletion, no code path invokes a tool outside the graph.
- Functional: all behavior tests from the guard table pass against the graph.
- Non-functional: deletion happens in one commit per target group, so a bisect can isolate any
  regression to a specific removal.
- Non-functional: `PlannerChatResponse` shape unchanged — the frontend still needs no change.

## Implementation Steps

1. Verify all four gates; stop if any fails.
2. Write the guard behavior tests (table above) against `orchestrator=graph`. Merge them **first**.
3. Flip the default to `graph`. Ship. Watch one release with `legacy` still available.
4. Delete `routing_decision.py` and `supervisor.py`.
5. Delete the 17 `session.py` functions, one commit per group.
6. Delete `TripPreferenceUpdate`, the two `with_message` methods, `_ToolAdapter`, `SessionTools`.
7. Rename `graph_v2/` → `graph/`; drop the `orchestrator` flag.
8. Re-run `eval/` and compare against the Phase 10 report; record both in the PR.
9. Grep-assert the plane is gone.

## Success Criteria

- [ ] `grep -rE "_run_intake|_run_edit_draft|_run_chat_agent|decide_route_by_rules|_ToolAdapter|SessionTools" backend/src/` returns nothing
- [ ] `routing_decision.py` and `supervisor.py` do not exist
- [ ] `session.py` under 500 LOC
- [ ] No `graph_v2` identifier remains
- [ ] Every guard-table test passes against the graph
- [ ] `eval/` end-to-end ≥ the Phase 10 report and ≥ committed baseline
- [ ] `PlannerChatResponse` shape unchanged; frontend untouched across the whole plan
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| **Cutover breaks production** | Four hard gates; one release with `legacy` still selectable; per-group commits so bisect isolates the cause |
| A deleted guard was load-bearing in a way nobody documented | The guard-table tests are written and merged **before** any deletion. A failing test blocks that specific removal, not the whole phase |
| Eval regression appears only after the flag flips | Steps 3 and 8 both measure; the flag is revertible until step 7 |
| Deleting `TripIntakeState.with_message` breaks callers not yet migrated | Phase 6 already routed every writer through the patch layer; `impact` on the symbol is a required pre-step |
| Partial deletion leaves a half-plane | Grep assertions in Success Criteria are the completion test, not a code review opinion |
| `legacy` lingers indefinitely because deleting feels risky | Flag removal is step 7 of this phase, not a follow-up ticket. If it does not happen here, the plan has not delivered its stated goal |
