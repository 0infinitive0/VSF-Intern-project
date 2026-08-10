---
phase: 2
title: "Safety Net Characterization Tests"
status: completed
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Safety Net Characterization Tests

## Overview

Pin today's behavior in tests written against the **public** surface
(`process_chat_turn` → `TurnResult`), so phases 3-5 can rewrite the internals
without silently changing what users experience. Also record the latency
baseline Phase 6 compares against.

This phase writes tests only. No production code changes.

## Requirements

- Functional: every route in `Route`
  (`select_hotel | finalize | new_trip | edit_draft | intake | chat`) has at
  least one end-to-end characterization test asserting reply text shape and
  `TurnResult.tool`.
- Functional: the hotel-pick gate is pinned by a dedicated test that does not
  depend on *how* the gate is implemented.
- Non-functional: tests must not call live LLM or Supabase — stub at the same
  seams `tests/test_chat_session.py` already uses.

## Architecture

The critical asset is the **hotel-pick gate**. Today it is enforced
*structurally*: `generate_full_itinerary` is deliberately never registered with
`create_react_agent`, so the model cannot call it (`src/agents/graph.py:31-32`,
`SessionTools` docstring). Phase 4 dissolves that mechanism — tools stop being a
closed closure set. A test that asserts "the tool is not registered" would pin
the *mechanism* and pass vacuously after the rewrite.

**Two such tests already exist** and are the gate's only current coverage:

| Test | Assertion |
|---|---|
| `tests/test_agents/test_graph.py:19` `test_build_trip_agent_registers_exactly_the_four_agent_visible_tools` | `tool_names == {...}` and `"generate_full_itinerary" not in tool_names` |
| `tests/test_trip_reuse_flow.py:15` | same tool-name list assertion, plus unrelated `trip_planner` serialization checks |

Both are mechanism tests. Per validation decision 1, this phase writes the
replacement invariant test and **Phase 4 deletes both** — a green test that
checks nothing is worse than no test, because it suppresses suspicion during the
riskiest phase of the migration. Note the `trip_reuse_flow` file also contains
unrelated serialization assertions: delete the tool-name block, keep the rest.

Pin the **invariant** instead: *no sequence of turns produces `trip_data` with
itinerary items while `pending_hotel_selection` is set and no hotel has been
chosen.* That statement survives any implementation.

Latency baseline: median wall time per turn over the characterization suite,
written to `plans/reports/` so Phase 6 has a number to compare against rather
than a memory.

## Related Code Files

- Create: `tests/test_chat_turn_characterization.py` — route coverage + gate invariant
- Modify: `tests/conftest.py` — shared stub fixtures if the existing seams are insufficient
- Read (do not modify): `tests/test_chat_session.py` for the established stubbing pattern
- Read (do not modify, deleted in Phase 4): `tests/test_agents/test_graph.py:19`,
  `tests/test_trip_reuse_flow.py:15` — the mechanism tests being replaced
- Create: `plans/reports/baseline-260802-turn-latency.md` — p50/p95 per route

<!-- Updated: Validation Session 1 - existing mechanism gate tests documented as the coverage being replaced -->


## Implementation Steps

1. Read `tests/test_chat_session.py` and `tests/conftest.py`; reuse their stub
   seams rather than inventing new ones.
2. Write one characterization test per route. Assert `TurnResult.tool` and
   `derive_stage(result)`, plus a stable substring of the reply — not the whole
   string, which is model-dependent on the `chat` route.
3. Write the gate invariant test: drive intake → `recommend_hotels` → attempt to
   reach an itinerary *without* selecting a hotel (finalize request, edit
   request, free-form chat). Assert no itinerary appears.
4. Write the re-route test: with a pending hotel list, send a message that is
   clearly not a hotel pick ("chốt lịch trình"). Assert the list is dropped and
   the message is handled for what it is — this pins the `session.py:456-462`
   behavior Phase 5 turns into a graph edge.
5. Write a state round-trip test: `asdict` → JSON → reconstruct for
   `TripIntakeState` and `HotelPreferenceState`; assert equality. **Assert
   `preferences` comes back as a `tuple`, not a `list`** — this is the one known
   serialization wrinkle and Phase 3 depends on it being handled.
6. Measure per-turn wall time across the suite; write p50/p95 per route to the
   baseline report.
7. Run the full suite twice to confirm the new tests are not flaky.

## Success Criteria

- [ ] All six routes covered by at least one characterization test
- [ ] Gate invariant test present and asserting state, not tool registration
- [ ] The invariant test fails if the gate is removed — verify by temporarily deleting the guard, not by assuming
- [ ] Re-route/drop-pending-list behavior pinned
- [ ] `TripIntakeState` / `HotelPreferenceState` JSON round-trip test passes, including `tuple` coercion
- [ ] New tests pass twice consecutively (no flake)
- [ ] No live LLM or Supabase calls (verified by running with credentials unset)
- [ ] Latency baseline written to `plans/reports/baseline-260802-turn-latency.md`

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Tests pin implementation instead of behavior, then pass vacuously after the rewrite | Assert only on `TurnResult`, `derive_stage`, and observable state; never on tool registration, call counts, or private helpers |
| Reply-text assertions break on model wording | Assert stable substrings; on the `chat` route assert `tool` and stage only |
| The gate test is written to the wrong invariant and gives false confidence | Have the invariant statement reviewed before the test is written — this test is the plan's single most important artifact |
| Baseline latency is measured on a warm cache and is unrepresentative | Record the measurement conditions in the report; Phase 6 must re-measure the same way |

## Execution Notes (2026-08-02)

- Created `tests/test_chat_turn_characterization.py`: one test per Route
  (select_hotel/finalize/new_trip/edit_draft/intake/chat) plus the intake
  route's recommend_hotels tail (distinct `hotel_options` stage), the
  hotel-pick gate invariant (3 scenarios: finalize attempt, edit attempt,
  neutral chat, all without a resolved hotel pick), the re-route/
  drop-pending-list test, and the TripIntakeState/HotelPreferenceState JSON
  round-trip test (confirms `preferences` needs explicit `tuple()`
  coercion — the wrinkle flagged in the plan).
- **Gate invariant test verified to have teeth**, not assumed: temporarily
  replaced `_run_select_hotel` in `session.py` with a version that fabricates
  an itinerary regardless of resolution, ran the 3 gate tests, confirmed all
  3 went red, then restored the original file (`git diff` empty afterward —
  no net change committed).
- **Caught and fixed a live-LLM-call leak during test authoring**: an early
  draft of `test_route_new_trip` and the latency helper's `_run_intake`
  didn't stub `_llm_extract_intake_facts`, so `TripIntakeState.with_message`
  made a real (slow, ~550ms, presumably failing-soft-after-timeout) network
  attempt. Fixed by stubbing it the same way `_mock_intake_extraction` does
  elsewhere. Re-verified with credentials unset
  (`env -u OPENAI_API_KEY -u SUPABASE_URL ...`) — all 27 new tests run in
  <0.1s combined, confirming no live calls remain.
- Restored production coverage of `recommend_hotels`/`select_hotel` that
  Phase 1 dropped along with the misleadingly-named
  `tests/test_planner_tools_hotel_flow.py`, as a correctly-named
  `tests/test_hotel_flow_tools.py` (12 tests, ported verbatim except for 2
  tests that referenced the deleted CLI fork and an unimplemented
  radius-filter feature — both already failing before Phase 1's deletion).
- Ran the full suite twice consecutively: 27/27 new tests pass both times,
  no flake. Full repo suite: 423 passed (was 396 after Phase 1), same 12
  pre-existing failures, 1 skipped. Zero regressions.
- Latency baseline written to `plans/reports/baseline-260802-turn-latency.md`
  (gitignored — `plans/` is not tracked in this repo). Sub-millisecond p50/p95
  per route, since the LLM/Supabase boundary is fully stubbed; this measures
  `process_chat_turn`'s own Python overhead, not end-to-end latency. Phase 6
  must re-measure the same way for a like-for-like comparison.
- Did not modify `tests/conftest.py` — the existing stubbing seams
  (`_FakeTool`/`_FakeTools`/`_session()` pattern from `test_chat_session.py`)
  were sufficient; duplicated locally per that file's own convention rather
  than centralizing prematurely.
