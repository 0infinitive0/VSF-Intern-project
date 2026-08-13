---
phase: 5
plan: 260812-0927-langgraph-orchestration-state-patch-and-interrupts
title: "Graph skeleton + supervisor behind a flag"
status: done
---

# Phase 5 completion report

## What shipped

New package `backend/src/agents/graph_v2/` — a real `StateGraph` (13 nodes, every edge from
the plan's topology) running behind a new `orchestrator: "graph" | "legacy"` config flag,
default `"legacy"`. `orchestrator=legacy` is byte-identical to before (diff of `routes.py` is
an early-return branch above the untouched legacy cascade).

- `state.py` — `TravelGraphState`, `SessionManifest`/`build_manifest`
- `contracts.py` — `NodeContract`, `enforce_contract` (wraps `hotel_node`/`itinerary_node`/`booking_node`)
- `routing.py` — `WORKFLOW_TO_WORKER`, `WORKER_ORDER`, `_IMPOSSIBLE`, `all_tasks_done`, `route_supervisor`, `route_ask_slot`, `route_scope_guard`
- `prompts.py` — supervisor delegation prompt
- `graph.py` — topology assembly, `build_graph(checkpointer=...)`
- `nodes/` — `load_context`, `scope_guard`, `extract_patch`, `validate_patch`, `apply_patch`,
  `ask_slot`, `supervisor`, `hotel_node`, `itinerary_node`, `booking_node`, `qa_node`,
  `budget_check`, `respond`

Modified: `config.py` (flag), `api/routes.py` (dispatch), `agents/session.py` (additive
read-only `SessionRegistry.checkpointer` property), `.env.example`.

New tests: `tests/test_graph_v2_skeleton.py`, `tests/test_supervisor_routing.py` (23 tests,
all passing, zero real LLM/network calls). One pre-existing test updated:
`test_structural_regression_harness.py::test_create_react_agent_has_exactly_two_owners_in_src`
(the guard was already stale before this phase — `agents/supervisor.py` no longer calls
`create_react_agent`; updated to the current legitimate two owners).

## Decisions made this session

1. **Phase 2's `guardrails/scope.py` doesn't exist** despite its plan doc saying done —
   confirmed absent from the repo. User chose: **stub `scope_guard`'s out-of-scope half**
   rather than fold Phase 2's work into this phase. Real jailbreak detection (a *different*,
   already-shipped control) was wired in during review — see findings below.
2. **`pending_tasks` state field** — the plan's supervisor pseudocode recomputes `workers`
   from `detect_impact(state["applied_changes"])` every call but never shows where
   `all_tasks_done`'s `state["pending_tasks"]` comes from. Resolved by seeding it once in
   `apply_patch` (from `impacted_workflows`), each worker popping itself off on completion,
   and the supervisor filtering the shrinking queue instead of re-deriving from
   `applied_changes` (which the code-reviewer confirmed the plan's literal approach would
   have crashed on: `detect_impact` expects `PatchChange` objects, `applied_changes` is
   stored as plain dicts for checkpointer serialization).
3. **`budget_check` node** — the plan's edges route worker completion here but the node is
   never in the plan's own `add_node(...)` list or Related Code Files. Added as a pass-through
   stub so the literal topology compiles; real logic is Phase 14's.
4. **`ask_slot`'s `"ask"` outcome routes to `respond`, not `END`** — every path must build the
   frozen `PlannerChatResponse` shape; routing to `END` directly would `KeyError` in
   `_run_turn_via_graph`.

## Code review findings — all fixed

A `code-reviewer` and a `tester` subagent ran independently against the implementation.
Three real defects surfaced and were fixed (with regression tests):

- **HIGH — stale cross-turn reply.** `respond`'s reply-from-`messages` scan didn't stop at the
  newest human message, so any turn whose worker sets no reply (every hotel/itinerary turn
  today) re-emitted the *previous* turn's `qa_node` answer. Fixed: stop scanning backwards at
  the first `human` message.
- **HIGH — jailbreak guard silently bypassed on the graph plane.** `detect_jailbreak` is
  shipped, wired legacy infra (not the unbuilt Phase 2 stub) — the graph plane skipped it
  entirely. Fixed: `scope_guard` now calls it, honoring `JAILBREAK_GUARD_MODE`, with a real
  `blocked -> respond` conditional edge (`route_scope_guard`).
- **MEDIUM-HIGH — supervisor could delegate outside its own queue.** The LLM's proposed
  worker was checked against `_IMPOSSIBLE` but never against `pending_tasks`, so a
  hallucinated re-pick of an already-completed worker would starve genuinely pending work for
  the whole 5-iteration cap. Fixed: reject `decision.next_worker not in workers` when `workers`
  is non-empty (still leaves `qa_node` reachable when nothing is pending).

Also applied: `enforce_contract` now actually wraps the three function workers in
`build_graph` (previously only exercised in tests); `graph_v2`'s import moved into
`_get_graph_v2()` so `orchestrator=legacy` boots never pull in the tree; a log line when the
checkpointer falls back to `MemorySaver`; a reducer-trap comment on `pending_tasks`/
`task_results` for Phase 8-9; `ORCHESTRATOR` documented in `.env.example`; an `isinstance`
guard on the structured-output result. Two vacuous/undercovered tests fixed: `all_tasks_done`'s
"no LLM" claim is now proven structurally (bytecode `co_names` inspection) instead of a
monkeypatch on a symbol the function can't reach; added an integration test that drives
`hotel_node -> all_tasks_done(True) -> budget_check -> respond` through the real compiled
graph (previously unexercised).

## Known limitations (flagged, not fixed — by design or out of scope)

- **`orchestrator=graph` dispatch covers `POST /planner_chat` only.** `/planner_chat/stream`
  (the frontend's actual default transport), `/hotels/select`, `/hotels/change`, and
  `/itineraries/generate` all still run the legacy cascade regardless of the flag. Documented
  loudly in `config.py`'s field description and `.env.example`. **Do not flip this flag in any
  environment the frontend talks to** until streaming dispatch is added or Phase 11 cuts over.
- **The graph plane never persists to Supabase/`TripSession`.** Its state lives only in the
  LangGraph checkpointer. A graph-plane turn is invisible to session restore/list until a
  later phase decides whether/how to bridge that.
- **`extract_patch` (Phase 6) is a stub**, so no real turn through the compiled graph today
  ever populates `pending_tasks` — `hotel_node`/`itinerary_node`/`booking_node` are reachable
  in the graph and correctly wired, but only exercised by tests until Phase 6 lands.
- **`make test` is not literally green.** It runs the full unscoped `pytest tests/`. Pre-existing
  failures (confirmed via `git stash` to predate this phase): `test_agents/test_supervisor.py`
  (7 tests — a stale mock referencing a `build_supervisor` symbol that no longer exists),
  `test_session_store.py` (1 test — missing migration file), `test_structural_regression_harness.py
  ::test_full_session_structural_signature` (1 test — unrelated `AttributeError` in the legacy
  agent-stream path), and 6 `test_api/` failures (payload-field mismatches + one LLM-content
  assertion, in code this phase never touches). Every test in this phase's own scope is green.

## Verification

- `pytest tests/test_graph_v2_skeleton.py tests/test_supervisor_routing.py` — 23/23 passed, no
  real LLM/network calls (all monkeypatched).
- `pytest tests/test_domain_layer_purity.py tests/test_travel_state.py
  tests/test_travel_state_read_through.py tests/test_checkpointer.py tests/test_routing.py
  tests/test_structural_regression_harness.py` (plus the two new files) — 88 passed, 1 skipped,
  1 pre-existing failure (see above).
- Manually confirmed: full graph compiles and runs end to end against a real local LLM;
  jailbreak guard blocks a real jailbreak prompt on the graph plane; a completed worker
  correctly routes through `budget_check` to `respond`.
- Did not run `tests/test_api/` or `test_agents/test_supervisor_routing_accuracy.py` broadly —
  they hit real OpenAI/LangSmith with live credentials (project convention).

## Unresolved questions

- Should `/planner_chat/stream` gain graph-plane dispatch now, or is `/planner_chat`-only
  acceptable until Phase 11? (Blocks flipping the flag in any environment the frontend uses,
  since streaming is its default transport.)
- Should the graph plane persist to Supabase/`TripSession` before Phase 11, or is
  checkpointer-only state the accepted interim?
