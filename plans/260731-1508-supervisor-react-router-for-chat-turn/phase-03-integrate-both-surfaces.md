---
phase: 3
title: "Integrate both surfaces"
status: complete (steps 7-8 unverified — no live smoke test run, see note below)
priority: P1
effort: "0.5-1d"
dependencies: [2]
---

# Phase 3: Integrate both surfaces

## Overview

Wire the supervisor into `process_chat_turn` so it decides the route, with
validation and regex fallback behind it. Because CLI and web already share this
function (D5), both surfaces change in one edit — and both must be verified.

## Requirements

**Functional**
- `process_chat_turn` asks the supervisor first, validates, falls back on failure.
- All six routes dispatch to their existing, unmodified branch bodies.
- `derive_stage()` returns the same `stage` values for the same conversations.
- `suggestions_for()` behavior unchanged.

**Non-functional**
- One shared routing path; no CLI-only or web-only branch (D5).
- A feature flag allows disabling the supervisor without a revert.

## Architecture

`process_chat_turn` becomes:

```python
context = route_context_from_session(session)

route = None
if supervisor_enabled():
    proposed = decide_route_by_llm(session, user_input)
    if proposed is not None:
        route = validate_route(proposed, context)

if route is None:
    route = decide_route_by_rules(context, user_input)   # Phase 1, unchanged

# existing branch bodies, dispatched on `route`
```

**Feature flag.** `TRIP_SUPERVISOR_ROUTER=0` disables the LLM layer and restores
pure-regex routing. Read through `src/config.py` `get_settings()` like the
existing settings, not via a bare `os.environ` read. This is the operational
rollback for R1/R2/R3 and must ship in the same commit as the integration.

**Logging.** Log both the proposed and final route at INFO — including whether
the fallback fired, and why (`llm_failed` | `invalid_label` | `impossible_route`
| `flag_off`). Phase 4's measurements depend on these being present and
distinguishable; without them, disagreement rate is unmeasurable.

**Stage contract.** `_STAGE_MAP` (`session.py:71-76`) keys off `TurnResult.tool`,
not off the route. Do not switch it to route labels — the frontend consumes
`stage`, and the two vocabularies are not the same. Keep populating `.tool`
exactly as the branch bodies do today.

## Related Code Files

- Modify: `src/agents/session.py` (`process_chat_turn` dispatch head)
- Modify: `src/config.py` (add the flag)
- Read only, verify unchanged: `src/api/routes.py`, `src/cli/terminal_chat.py`
- Test: `tests/test_structural_regression_harness.py`,
  `tests/test_api/test_chat_flow.py`, `tests/test_api/test_chat_session.py`

## Implementation Steps

1. Add `TRIP_SUPERVISOR_ROUTER` (default on) to `src/config.py` settings.
2. Insert the supervisor → validate → fallback head into `process_chat_turn`,
   replacing the inline conditions with dispatch on `route`.
3. Add the route-decision logging described above.
4. Run the full regression harness with the flag **off** — must match Phase 1
   results exactly. This proves the fallback layer is intact.
5. Run it again with the flag **on** and a stubbed supervisor returning the
   route the regex layer would have chosen — must also match. This isolates
   wiring bugs from model-quality issues.
6. Run `tests/test_api/` to confirm `stage` and `suggestions` are unchanged.
7. Manual CLI smoke test via `scripts/poc_trip_planner.py` (needs Ollama +
   Supabase): full happy path — new trip → hotel list → pick → itinerary → edit
   → finalize.
8. Manual web smoke test against `POST /planner_chat` for the same path.

## Success Criteria

- [x] Flag off → regression harness identical to Phase 1 baseline (verified:
  `TRIP_SUPERVISOR_ROUTER=0 pytest tests/test_structural_regression_harness.py
  tests/test_chat_session.py` → 25 passed)
- [x] Flag on with stubbed supervisor → identical results (verified: supervisor
  stubbed to call `decide_route_by_rules` directly → harness still passes)
- [x] `tests/test_api/` passes; `stage` values unchanged (60 passed)
- [ ] CLI happy path completes end to end — **not run** (user chose to skip the
  live-Supabase smoke test this session; see note below)
- [ ] Web happy path completes end to end — **not run**, same reason
- [x] `src/api/routes.py` and `src/cli/terminal_chat.py` have zero diff
- [x] Route decisions and fallback reasons appear in logs (`_decide_route` in
  `session.py` logs `reason=llm_failed|invalid_label|impossible_route|flag_off|supervisor`)

**Note on unverified steps:** Ollama and Supabase were both reachable in this
session. The user was asked before writing throwaway data to live Supabase and
chose to skip it. Per this phase's own risk mitigation below, this is recorded
honestly rather than marking the phase complete on stubbed evidence alone. A
live end-to-end pass (CLI: `python scripts/poc_trip_planner.py`; web: `POST
/planner_chat`) is still needed before shipping with the flag on by default.

**Gap found and fixed during this phase (not in the original spec):** Phase 2's
supervisor prompt never received session state, so the LLM had no way to know
a hotel list was pending, a draft existed, etc. — confirmed live: bare input
`"1"` with a pending hotel list was misrouted to `intake` instead of
`select_hotel`. Fixed by adding `_state_summary(session)` in
`src/agents/supervisor.py`, sent alongside the user message (booleans/counts
only, never venue data or trip facts — same non-goal Phase 2 already commits
to). Phase 2's own doc did require this ("Supervisor prompt receives session
state... needed for D1"); it just wasn't implemented until this phase's live
testing caught it.

**Test-isolation fix:** `tests/test_chat_session.py` predates the supervisor
and is a unit-test suite for the deterministic cascade. With the flag on by
default and Ollama reachable in this dev environment, a live, unstubbed LLM
started deciding routes in these tests non-deterministically. Added an
autouse fixture stubbing `decide_route_by_llm` to return `None` for this file
only, so it exercises exactly what it always tested: `decide_route_by_rules`.

## Risk Assessment

**Risk:** The pending-hotel branch mutates session state *during* the decision
(calls `select_hotel`, inspects the clear). Moving it under a dispatch can
double-invoke the tool.
**Mitigation:** Phase 1 already fixed the shape. Assert `select_hotel` invocation
count is exactly one per turn in the harness.

**Risk:** Live Ollama is required for steps 7-8, and may be unavailable.
**Mitigation:** Steps 4-6 are the real gate and need no Ollama. If 7-8 cannot
run, record that the phase is unverified against a live model and say so — do
not mark the phase complete on stubbed evidence alone.

**Risk:** `planning_new_trip` / `initial_plan_complete` are mutated by branch
bodies, so a route chosen from a stale context can act on wrong state.
**Mitigation:** Build `RouteContext` once at the top of the turn and never reuse
it after a branch body runs. One turn, one context.

**Rollback:** Set `TRIP_SUPERVISOR_ROUTER=0` — no deploy needed. Full revert is
one commit.
