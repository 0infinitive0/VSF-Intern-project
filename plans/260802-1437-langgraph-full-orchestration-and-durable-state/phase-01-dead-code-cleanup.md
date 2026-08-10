---
phase: 1
title: "Dead Code Cleanup"
status: completed
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Dead Code Cleanup

## Overview

Delete the template graph and the orphaned `src/cli` fork (~2485 lines) before
migrating anything. Migrating while carrying a dead parallel implementation
doubles the work.

## Requirements

- Functional: no user-visible behavior change; `POST /planner_chat`, the three
  `/chat/*` endpoints, and `scripts/poc_trip_planner.py` behave identically.
- Non-functional: `src/` shrinks by ≥2400 lines; the repo contains exactly two
  `create_react_agent` call sites afterwards.

## Architecture

Two independent deletions.

**A — template graph.** `src/api/routes.py` no longer imports `agent`; the only
remaining reference is `tests/test_agents/test_graph.py`. The `graph.py:5-7`
docstring claiming the endpoint still serves it is stale and must be corrected,
not preserved.

**B — CLI fork.** `src/cli/planner_tools.py` builds its *own*
`create_react_agent` + `MemorySaver` (`planner_tools.py:678`), duplicating
`src/agents/graph.py`. It imports `src/cli/trip_builder_svc.py` (1802 L), a
near-duplicate of `src/services/trip_planner.py` (52 vs 48 defs). Nothing in
production imports either — `src/cli/terminal_chat.py` goes straight to
`src.agents.session`.

`trip_planner` is the surviving fork: `tests/test_trip_modification.py:3` writes
`import src.services.trip_planner as trip_builder_svc`.

## Related Code Files

- Modify: `src/agents/graph.py` — drop `_analyze_node`, `_respond_node`,
  `_should_continue`, `_build_template_graph`, module-level `agent`; fix the
  stale docstring; drop now-unused `END` / `StateGraph` / `AgentState` imports
- Modify: `src/agents/state.py` — drop `AgentState`, keep `TripAgentState`
- Modify: `tests/test_agents/test_graph.py` — drop the `agent` import and its tests
- Delete: `src/cli/planner_tools.py`
- Delete: `src/cli/trip_builder_svc.py`
- Delete: `tests/test_planner_tools_hotel_flow.py`
- Modify: `tests/test_structural_regression_harness.py` — add the two-agent assertion
- Keep: `src/cli/terminal_chat.py`, `src/cli/__init__.py`

## Implementation Steps

1. Commit or stash the 21 dirty files currently on `dev`; branch `chore/dead-code-cleanup`.
2. Run `impact({target: "agent", direction: "upstream"})` and
   `impact({target: "_build_template_graph", direction: "upstream"})`; confirm
   no production caller.
3. Delete deletion-set A. Fix the `graph.py` docstring to describe only
   `build_trip_agent`. Run `ruff` to catch orphaned imports.
4. `pytest tests/test_agents/` — green.
5. Commit A separately.
6. Diff `src/cli/trip_builder_svc.py` against `src/services/trip_planner.py`.
   Produce an explicit list of functions that exist **only** in the CLI copy.
7. For each: decide port-to-`services` or drop. Record the decision inline in the
   commit message. Do not port speculatively.
8. Delete deletion-set B.
9. Verify `scripts/poc_trip_planner.py` still runs (it imports
   `src.cli.terminal_chat`, which is retained).
10. Add to `tests/test_structural_regression_harness.py`: assert exactly two
    `create_react_agent` occurrences across `src/`, naming the two owners.
11. Full `pytest`; `detect_changes({scope: "compare", base_ref: "main"})`; merge to `dev`.

## Success Criteria

- [ ] `grep -rn "_build_template_graph\|^agent = " src/` returns 0
- [ ] `grep -rn "AgentState" src/` returns 0 (`TripAgentState` still present)
- [ ] `src/cli/planner_tools.py` and `src/cli/trip_builder_svc.py` do not exist
- [ ] `create_react_agent` appears exactly twice in `src/`
- [ ] Structural regression harness asserts that count and fails if a third appears
- [ ] `ruff check` clean
- [ ] Full `pytest` green
- [ ] `scripts/poc_trip_planner.py` starts and accepts one turn
- [ ] `src/` line count down ≥2400

## Risk Assessment

| Risk | Mitigation |
|---|---|
| A function exists only in the CLI fork and is silently lost | Step 6 produces an explicit diff list; nothing is deleted before that list is reviewed |
| The `agent` symbol is imported somewhere not caught by grep (dynamic import, string ref) | Step 2 runs GitNexus `impact` upstream in addition to grep |
| Deleting `tests/test_planner_tools_hotel_flow.py` drops real coverage of hotel-flow behavior | That behavior is covered again — and against the *live* path — by Phase 2's characterization tests. If Phase 2 slips, keep the file until it lands |
| The 21 dirty files on `dev` are lost during branching | Step 1 commits or stashes them first, before any deletion |

## Execution Notes (2026-08-02)

- `dev` was already clean at execution time — the "21 dirty files" premise was
  stale; no stash needed.
- GitNexus MCP tools (`impact`, `detect_changes`) were not connected in this
  session even after building the index with `npx gitnexus analyze`
  (`claude mcp list` shows no gitnexus server registered). Substituted
  grep + LSP for blast-radius checks and full-suite pytest diffing for
  `detect_changes`. Flagged to the user before proceeding.
- `tests/test_planner_tools_hotel_flow.py` actually tested **production**
  `recommend_hotels`/`select_hotel` tools, not the CLI fork it was named
  after — the plan's premise for deleting it (row above) was incorrect.
  Flagged to the user; user chose to delete per the plan as written. 2 of
  its 14 tests were already failing pre-deletion (pre-existing, unrelated).
  Phase 2 should explicitly re-cover the `recommend_hotels`/`select_hotel`
  ground this file held, not just the six `Route` cases.
- All 7 function names unique to `trip_builder_svc.py` were verified already
  duplicated in `src/services/trip_formatter.py` / `src/agents/session.py` —
  nothing ported.
- Full `pytest` after merge: 396 passed, 12 failed (all pre-existing on
  `dev` prior to this phase — airflow pipeline mocks, migration SQL path,
  trip_intake/trip_reuse contract tests), 1 skipped. Zero regressions.
- `src/` line count: -2547 (target ≥2400 ✓).
- Repo-wide `ruff check` error count went from 1217 → 1067 (net improvement;
  full-repo zero-errors was never true before this phase and remains a
  separate, out-of-scope backlog item).
- Merged to `dev` locally via `git merge --no-ff`; not pushed to remote.
