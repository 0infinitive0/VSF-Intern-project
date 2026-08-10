---
phase: 4
title: "Tools To ToolRuntime And Command"
status: completed
priority: P1
effort: "1-2d"
dependencies: [3]
---

# Phase 4: Tools To ToolRuntime And Command

## Overview

Convert the four agent tools from session-bound closures that mutate a dataclass
into plain tools that read `TripState` via `ToolRuntime` and write it by
returning `Command(update=...)`. This is the phase that makes checkpointing
meaningful — and the phase that can silently destroy the hotel-pick gate.

## Requirements

- Functional: Phase 2's gate invariant test passes unchanged.
- Functional: all four tools produce the same replies for the same inputs.
- Non-functional: no tool imports or references `TripSession`.
- Non-functional: the circular-import workaround in `recommend_hotels.py` is gone.

## Architecture

**Today.** `build_recommend_hotels_tool(session)` and its three siblings close
over a `TripSession` and mutate it. `recommend_hotels.py` even does
`from src.agents.session import _save_pending_hotel_selection` *inside* the
function body to dodge a circular import — direct evidence the dependency runs
the wrong way.

**Target** (verified against LangGraph 1.x docs):

```python
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command

@tool
def select_hotel(selection: str, runtime: ToolRuntime[None, TripState]) -> Command:
    """..."""
    pending = runtime.state["pending_hotel_selection"]
    ...
    return Command(update={
        "trip_data": new_trip_data,
        "pending_hotel_selection": None,
        "initial_plan_complete": True,
        "messages": [ToolMessage(reply, tool_call_id=runtime.tool_call_id)],
    })
```

Three contract rules from the docs, all mandatory:

1. A `Command` returned from a tool **must** include `messages` containing a
   `ToolMessage` carrying `runtime.tool_call_id`.
2. `Command` propagation requires the prebuilt `ToolNode`.
3. `runtime.state` is read-only; all writes go through the returned `Command`.

**The gate — read this before writing code.** Today `generate_full_itinerary` is
kept out of the model's reach by simply never being registered
(`src/agents/graph.py:30-32`). Tools are no longer a per-session closed closure
set, so that guarantee evaporates. Replace it with an explicit precondition
inside every tool that can produce or mutate an itinerary:

```python
if runtime.state.get("pending_hotel_selection") is not None:
    return Command(update={"messages": [ToolMessage(
        "Bạn cần chọn khách sạn trước.", tool_call_id=runtime.tool_call_id)]})
```

The gate moves from *structural* to *asserted*. Phase 2's invariant test is the
only thing that proves the move was faithful.

**Delete the two mechanism tests in this phase** (validation decision 1). They
assert `"generate_full_itinerary" not in tool_names` against a tool list that no
longer exists as a per-session bundle, so after this rewrite they pass while
checking nothing:

| Test | Action |
|---|---|
| `tests/test_agents/test_graph.py:19` `test_build_trip_agent_registers_exactly_the_four_agent_visible_tools` | delete the test |
| `tests/test_trip_reuse_flow.py:15` | delete the tool-name assertion block only — the surrounding `trip_planner` serialization assertions are unrelated and stay |

Do not "fix" them to assert the new tool list. A green test that checks nothing
is worse than no test during the riskiest phase of the migration.

`SessionTools` (the `NamedTuple` of bound closures) disappears — tools become
module-level and are registered once.

## Related Code Files

- Modify: `src/agents/tools/recommend_hotels.py`
- Modify: `src/agents/tools/select_hotel.py`
- Modify: `src/agents/tools/modify_itinerary.py`
- Modify: `src/agents/tools/finalize_itinerary.py`
- Modify: `src/agents/graph.py` — drop `SessionTools` and the four `build_*` factories; register module-level tools via `ToolNode`
- Modify: `src/agents/session.py` — stop constructing per-session tools
- Modify: `tests/test_trip_reuse_flow.py` — delete the tool-name assertion block (keep serialization checks)
- Modify: `tests/test_agents/test_graph.py` — delete `test_build_trip_agent_registers_exactly_the_four_agent_visible_tools`
- Modify: `tests/test_trip_cloning_and_recommendations.py`
- Modify: `tests/test_terminal_chat.py:21`, `tests/test_structural_regression_harness.py:235`, `tests/test_api/test_routes.py:18` — all stub `build_trip_agent`'s two-value return, which changes when `SessionTools` is deleted

<!-- Updated: Validation Session 1 - mechanism gate tests deleted here; build_trip_agent stub consumers enumerated -->


## Implementation Steps

1. Re-read Phase 2's gate invariant test. Do not start until it is understood —
   it is the acceptance criterion for this phase.
2. Run `impact` upstream on each of the four `build_*_tool` factories.
3. Convert `select_hotel` first — it is the tool the gate hinges on and the one
   with the most state writes. Get it green before touching the others.
4. Add the explicit `pending_hotel_selection` precondition to every tool that can
   create or modify an itinerary.
5. Convert `recommend_hotels`; delete the in-function
   `from src.agents.session import ...` workaround.
6. Convert `modify_itinerary` and `finalize_itinerary`.
7. Delete `SessionTools`, the four `build_*` factories, and their call sites in
   `build_trip_agent`. Register the module-level tools with `ToolNode`.
8. Verify `ruff` reports no import cycle and no unused import.
9. Full `pytest`, with the gate invariant test explicitly named in the run output.

## Success Criteria

- [ ] `grep -rn "TripSession\|session\." src/agents/tools/` returns 0
- [ ] `grep -rn "SessionTools\|build_recommend_hotels_tool" src/` returns 0
- [ ] Every tool that touches an itinerary asserts `pending_hotel_selection is None` first
- [ ] Every `Command` returned from a tool includes a `ToolMessage` with `tool_call_id`
- [ ] Tools are registered through the prebuilt `ToolNode`
- [ ] Phase 2 gate invariant test passes, unmodified
- [ ] `grep -rn "generate_full_itinerary" tests/` returns 0 — both mechanism tests removed, not repaired
- [ ] No import cycle between `src/agents/tools/*` and `src/agents/session.py`
- [ ] Full `pytest` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| **The hotel-pick gate is lost.** The structural guarantee is deleted in this phase; if the explicit check is missed on one tool, the model can build an itinerary with no hotel chosen | Phase 2's invariant test is written *before* this phase and is the sole acceptance criterion. Step 4 applies the check to every itinerary-touching tool, not just `select_hotel` |
| `Command` returned without a `ToolMessage` — silently drops the tool result from history | Explicit success criterion; enforce in code review of each converted tool |
| Tools not wired through `ToolNode`, so `Command` updates never reach state — appears to work in unit tests but state never changes | Assert observable state change after a tool call, not just the returned reply string |
| Converting all four at once makes a failure hard to localize | Step 3 converts `select_hotel` alone and gets it green first |
| Removing the circular-import workaround exposes a real cycle | The cycle only existed because tools reached back into `session`; after conversion the dependency is one-way. `ruff` check in step 8 confirms |

## Execution Notes (2026-08-02)

### Two deviations from the plan's literal design (both discussed with the user mid-implementation)

1. **`SessionTools` does not disappear.** Verified empirically before writing
   any tool code: a `ToolRuntime`-typed tool cannot be invoked via a bare
   `.invoke({...})` call — it raises a pydantic `ValidationError` for the
   missing `runtime` field, since that injection only happens inside a
   `ToolNode`'s own execution machinery. But `process_chat_turn`'s
   deterministic cascade (`_run_select_hotel`, `_run_finalize`, the intake
   tail) calls `session.tools.X.invoke({...})` directly, outside any graph —
   and dozens of tests across `test_chat_session.py`,
   `test_chat_turn_characterization.py` (Phase 2's own file),
   `test_structural_regression_harness.py`, `test_api/test_chat_flow.py`,
   `test_api/test_chat_session.py` stub exactly that attribute with a
   `_FakeTool(...)`. Deleting `SessionTools` per the plan's literal text
   would have broken that stubbing pattern everywhere, including in the file
   the plan explicitly says must stay unmodified.

   Resolution (user-approved): `SessionTools` (in `graph.py`) now holds
   `_ToolAdapter` instances instead of closures — same `.invoke(args) -> str`
   interface, internally driving the real module-level tool through a
   cached single-node `StateGraph` (`src/agents/tools/direct_invoke.py`) and
   merging the `Command`'s update onto `session.state`. Zero changes needed
   to any of the 5 test files' stubbing patterns. `_run_select_hotel`,
   `_run_finalize`, and the intake tail did not need to change at all.

2. **`execute_trip_edit_request` stays in `session.py` at its exact name and
   signature**, as a thin wrapper. The real logic moved to
   `trip_planner.py` as `resolve_trip_edit_request(trip_data, request,
   plan) -> (reply, updates)` — pure, no `TripSession`. `modify_trip_plan`
   calls this directly; `session.py`'s wrapper calls it too and applies the
   updates onto `session.state`. Needed because (a) the tool cannot take a
   `TripSession` at all, and (b) importing the old session.py function from
   the tool would recreate the exact `session.py -> graph.py -> tools ->
   session.py` cycle this phase removes from the other three tools — but
   also because many existing tests monkeypatch
   `session_module.execute_trip_edit_request` directly at that exact name,
   expecting the original `(session, request, plan) -> str | None` shape.

### Three bugs found only by testing, not assumed from docs

- `create_react_agent`'s custom `state_schema` must declare `remaining_steps`
  (`NotRequired[Annotated[int, RemainingStepsManager]]`) — a managed field it
  injects itself — or it raises `ValueError: Missing required key(s)
  {'remaining_steps'}` at compile time. Not documented anywhere the plan's
  cited docs page covers (that page only shows `ToolRuntime` with a plain
  `StateGraph`, never `create_react_agent`); found via a throwaway script,
  fixed, then verified end-to-end with a real `create_react_agent` +
  `ToolRuntime` tool + fake chat model.
- `TripState`'s `TypedDict` must come from `typing_extensions`, not `typing`,
  on Python <3.12 — pydantic (used internally by `ToolRuntime`'s schema
  generation) raises `PydanticUserError` otherwise. Found when
  `test_trip_reuse_flow.py`'s rewritten test crashed on collection.
- `_run_chat_agent` was calling `session.agent.stream({"messages": [...]},
  ...)` without seeding the graph's own checkpointed state with
  `session.state`. Since tools now write `TripState` via `Command` into
  `create_react_agent`'s own checkpointer (keyed by `thread_id`) — a
  SEPARATE store from `session.state` — a tool call made through the LLM
  agent path would either `KeyError` on a fresh thread (verified: reproduced
  this exact crash before fixing it) or silently diverge from
  `session.state` on a warm one. Fixed by seeding the input with
  `**session.state` and syncing the final `stream_mode="values"` event back
  onto `session.state` after the loop.

### Cleanup beyond the plan's file list

- `_save_trip_data` and `_save_pending_hotel_selection` in `session.py`
  became genuinely dead code once the tools stopped calling them (confirmed
  via grep before deleting — no remaining call sites, no test references).
- `tests/test_agents/test_graph.py` deleted in full, not just the one
  mechanism test — Phase 1 had already removed its other two tests, so
  nothing else remained.
- `tests/test_trip_reuse_flow.py`'s second test
  (`test_finalized_itinerary_is_not_mutated_by_the_edit_tool`) also used the
  now-deleted `build_select_hotel_tool` factory with a bare `.invoke()` call
  — not on the plan's list (it predates the mechanism-test cleanup and
  wasn't flagged as one of the "two mechanism tests"), but broken by the
  same `ToolRuntime` constraint. Rewritten to use `invoke_tool_directly`
  against a plain `TripState` dict.
- Two other tests in the same file used `build_trip_agent` with a
  `_FakeSession` lacking `.state` — same class of issue as Phase 3's
  `test_supervisor*.py` fix. The tool-name assertion block containing them
  was deleted per validation decision 1 anyway, so no adapter was needed
  there — just removal.

### Verification beyond "tests pass"

- Manually drove `finalize_trip_plan` and `modify_trip_plan` directly via
  `invoke_tool_directly` with `pending_hotel_selection` set, confirmed both
  refuse with the expected message and leave `trip_data` untouched — the
  actual gate behavior, not inferred from code review.
- Smoke-tested `build_trip_agent` end-to-end with a fake chat model
  supporting `bind_tools`, confirming it compiles and exposes all four
  tools.
- The `grep -rn "generate_full_itinerary" tests/` success criterion (expect
  0) is not literally met: the string still appears in
  `test_hotel_flow_tools.py` (legitimate direct tests of the plain
  `generate_full_itinerary` function in `trip_planner.py`, unrelated to the
  tool-registration mechanism) and in explanatory comments/docstrings in two
  other files. The actual intent — delete the two vacuous
  `"generate_full_itinerary" not in tool_names` assertions — is satisfied;
  the literal grep is a blunt proxy for that intent, not a hard requirement.
- Full suite: 425 passed (was 426 after Phase 3; -1 for the fully-emptied
  `test_graph.py`), same 12 pre-existing failures (unrelated: airflow
  pipeline mocks, migration SQL path, trip_intake/trip_reuse contract
  tests), run three times with no flake.
