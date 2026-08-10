---
title: "LangGraph Full Orchestration And Durable State"
description: "Move chat-turn state ownership from the mutable TripSession dataclass into LangGraph state, convert session-closure tools to ToolRuntime/Command, and replace the process_chat_turn cascade with an explicit StateGraph. Durable Postgres checkpointing is designed but deferred out of scope."
status: pending
priority: P1
effort: "6.5-8.5d (phases 1-6)"
branch: "dev"
tags: [langgraph, state-graph, checkpointer, postgres, agents, refactor]
blockedBy: [260731-1508-supervisor-react-router-for-chat-turn]
blocks: []
created: 2026-08-02
---

# LangGraph Full Orchestration And Durable State

## Overview

Today's chat turn is a hand-driven Python cascade over a mutable `TripSession`
dataclass. LangGraph is present but shallow: `create_react_agent` handles the
fallback chat branch, and `MemorySaver` (`src/agents/graph.py:52`) checkpoints
**only `messages`**.

This plan moves state ownership into LangGraph so the checkpointer actually owns
the conversation, and replaces the cascade with an explicit graph.

> **Scope decision (validation session 1, 2026-08-02):** phases 7-8 (Postgres
> checkpointer, `interrupt()`) are **deferred out of scope**. No feature freeze
> was agreed, and 8-11 days of migration against an unfrozen backlog with under
> four weeks to Demo Day is not a schedule anyone should sign. **Delivery ends at
> Phase 6.** Goals 1, 2, 4, 5 ship; goal 3 (durable state) does not. Phases 7-8
> stay in the plan as designed work for after Demo Day — their design is verified
> and worth keeping, just not now.

## The ordering constraint (most important thing in this plan)

Verified: every business fact — `trip_data`, `intake_state`, `hotel_pref_state`,
`pending_hotel_selection`, `initial_plan_complete`, `planning_new_trip` — lives
in `TripSession` (RAM, held by `SessionRegistry`), **outside the checkpoint**.
The four agent tools are closures bound to that session
(`build_recommend_hotels_tool(session)`) and mutate it in place. LangGraph can
only checkpoint graph channel values.

Consequence: **swapping `MemorySaver` → `PostgresSaver` today buys nothing.** It
would persist the message list and still lose all trip state on restart — worse
than the status quo, because it *looks* durable.

Phases 3 → 4 → 5 → 7 are therefore strictly ordered:

| Order | Work | Violating the order gives |
|-------|------|---------------------------|
| 3 | `TripSession` → serializable `TripState` | — |
| 4 | Tools: closure → `ToolRuntime` + `Command(update=...)` | Doing 5 first: nodes still mutate a session, the graph is decoration |
| 5 | `process_chat_turn` cascade → `StateGraph` | — |
| 7 *(deferred)* | `MemorySaver` → `PostgresSaver`, drop `SessionRegistry` | Doing 7 before 3: **fake persistence** |

Phase 6 is the delivery boundary: everything works on `MemorySaver` with no
Postgres risk. The ordering above still matters because it is exactly why Phase 7
cannot be pulled forward as a "quick win" later — without phases 3-5 it persists
the message list and nothing else.

## What makes this cheaper than it looks

`process_chat_turn` was already decomposed into `_run_select_hotel`,
`_run_finalize`, `_run_edit_draft`, `_run_intake`, `_run_chat_agent`
(`src/agents/session.py:476-628`). Those are node-shaped already. Phase 5 is the
cheapest phase, not the most expensive.

`src/agents/routing_decision.py` is the purest module in the repo — `RouteContext`
reads 8 booleans and nothing else. It migrates nearly free.

## Verified findings that shaped this plan

| Finding | Evidence | Effect |
|---|---|---|
| Template graph is dead | `src/api/routes.py` no longer imports `agent`; only `tests/test_agents/test_graph.py` does. `graph.py:5-7` docstring claiming otherwise is stale | Phase 1 deletes it |
| CLI fork is orphaned | `src/cli/planner_tools.py` (683 L) + `src/cli/trip_builder_svc.py` (1802 L) imported only by each other + one test. `terminal_chat.py` uses `src/agents/session` | Phase 1 deletes ~2485 L |
| `trip_planner` is the surviving fork | `tests/test_trip_modification.py:3` writes `import src.services.trip_planner as trip_builder_svc` | Phase 1 diffs before deleting |
| Intake/pref state serializes cleanly | `TripIntakeState` = `str` / `tuple[str, ...]`; `HotelPreferenceState` = `Literal` + `float` — all primitive | De-risks Phase 3; only `tuple` → `list` coercion needed |
| No Postgres DSN exists | `src/config.py:42-49` has `database_url` (sqlite default) + `supabase_url` / `supabase_service_key` only | Phase 7 adds a real DSN config field + secret |
| Tools carry a circular-import workaround | `recommend_hotels.py` does `from src.agents.session import _save_pending_hotel_selection` *inside* the function body | Phase 4 removes the cycle |
| Re-route already exists | `session.py:456-462` re-decides the route after a dropped hotel list | Phase 5 makes it a real edge — needs a loop guard |

## API contract (verified against LangGraph 1.x docs, 2026-08-02)

Source: https://docs.langchain.com/oss/python/langgraph/use-graph-api

- Tools read state via an injected `ToolRuntime[Context, State]` (`runtime.state[...]`).
- Tools write state by returning `Command(update={...})`.
- A `Command` returned from a tool **must** include `messages` containing a
  `ToolMessage(..., tool_call_id=runtime.tool_call_id)`.
- `Command` propagation requires the prebuilt `ToolNode`.
- Postgres: `pip install -U "psycopg[binary,pool]" langgraph-checkpoint-postgres`;
  `PostgresSaver.from_conn_string(...)`; `checkpointer.setup()` creates tables.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | All chat-turn state lives in LangGraph state, not in a mutable session object | P1 |
| 2 | Chat-turn control flow is an explicit `StateGraph`, not an `if` cascade | P1 |
| 3 | ~~Trip state survives a process restart~~ — **deferred with phase 7** | — |
| 4 | The hotel-pick gate survives the refactor intact | P1 |
| 5 | Remove ~2485 lines of dead parallel implementation | P2 |
| 6 | ~~Hotel pick becomes a real human-in-the-loop `interrupt()`~~ — **deferred with phase 8** | — |

## Non-goals

- Streaming responses to the UI. `POST /planner_chat` returns a full response; no
  SSE is introduced here.
- Replacing the deterministic routing fallback. `decide_route_by_rules` /
  `validate_route` stay — they are the design's strongest property.
- Changing user-visible behavior. Every in-scope phase is behavior-preserving.
- Migrating `src/airflow/**` or the data pipeline.
- **Durable state.** After Phase 6, conversation state still dies with the
  process, exactly as it does today. Say this plainly in the architecture doc
  rather than letting a judge discover it.

## Constraints

- Demo Day in under 4 weeks; grading weights a working demo and UX.
- **No feature freeze is in place.** This is why scope stops at Phase 6 — the
  original 8-11 day plan assumed a freeze that was not agreed.
- Per `CLAUDE.md`: run `impact({target, direction:"upstream"})` before editing a
  symbol and `detect_changes()` before committing.
- EC2 t3.micro is already swap-dependent; Phase 7 adds a connection pool.

## Cross-plan dependencies

| Relationship | Plan | Note |
|---|---|---|
| `blockedBy` | `260731-1508-supervisor-react-router-for-chat-turn` | Its output (`supervisor.py`, `routing_decision.py`, `test_supervisor*.py`) is this plan's input. **Its frontmatter says `pending` but the code has shipped** — status is stale; reconcile it |
| overlaps | `260729-1637-trip-planner-chat-ui-and-agents-backend` | Introduced the `services` / `agents` / `cli` layering this plan consolidates. Phase 1 deletes the `src/cli` half it left behind |
| rolls up to | `260723-1015-v-ota-poc-master-roadmap` | Program spine |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Dead Code Cleanup](./phase-01-dead-code-cleanup.md) | Completed |
| 2 | [Phase 2: Safety Net Characterization Tests](./phase-02-safety-net-characterization-tests.md) | Completed |
| 3 | [Phase 3: TripState And State Ownership](./phase-03-tripstate-and-state-ownership.md) | Completed |
| 4 | [Phase 4: Tools To ToolRuntime And Command](./phase-04-tools-to-toolruntime-and-command.md) | Completed |
| 5 | [Phase 5: StateGraph Orchestration](./phase-05-stategraph-orchestration.md) | Completed |
| 6 | [Phase 6: Safe Stop Gate MemorySaver Green](./phase-06-safe-stop-gate-memorysaver-green.md) | Pending — **final in-scope phase** |
| 7 | [Phase 7: Postgres Checkpointer And Registry Removal](./phase-07-postgres-checkpointer-and-registry-removal.md) | **Deferred** (post-Demo Day) |
| 8 | [Phase 8: Human In The Loop Hotel Interrupt](./phase-08-human-in-the-loop-hotel-interrupt.md) | **Deferred** (post-Demo Day) |

## Effort

| Phase | Estimate |
|---|---|
| 1 Dead code cleanup | 0.5d |
| 2 Safety net | 1d |
| 3 TripState | 2-3d |
| 4 Tools | 1-2d |
| 5 StateGraph | 1-2d |
| 6 Verification + docs | 1d |
| **In-scope total** | **6.5-8.5d** |
| 7 Postgres *(deferred)* | 1d |
| 8 HITL interrupt *(deferred)* | 1d |

## Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Hotel-pick gate lost in Phase 4. Today it is enforced *structurally* — `generate_full_itinerary` is simply never registered with `create_react_agent` (`graph.py:30-32`). That trick does not survive the rewrite | **Critical** | Phase 2 writes the characterization test first; Phase 4 re-implements the gate as an explicit `state["pending_hotel_selection"]` check |
| R2 | `select_hotel → router` becomes a real cycle; a misrouting LLM loops forever burning tokens | High | `reroute_count` in state, hard cap at 1 (Phase 5) |
| R3 | Schedule overrun eats demo-polish time | High | Scope stops at Phase 6. If phases 1-5 overrun, phases 1-2 alone are still a coherent, shippable subset |
| R4 | Existing mechanism-based gate tests (`test_agents/test_graph.py:19`, `test_trip_reuse_flow.py:15`) survive Phase 4 and pass vacuously, hiding a lost gate | High | Phase 4 deletes both once Phase 2's invariant test replaces them (validation decision 1) |
| R5 *(deferred)* | `PostgresSaver` pool closed early — the docs example uses `with ... from_conn_string()`, which kills the pool on exit and 500s the next request | High | Build `PostgresSaver(ConnectionPool(...))` once in the FastAPI lifespan (Phase 7) |
| R6 *(deferred)* | Supabase transaction pooler (port 6543) breaks psycopg prepared statements | High | Use a direct or session-pooler DSN; assert at startup (Phase 7) |
| R7 *(deferred)* | Checkpoints never expire, so conversations live forever — `SessionRegistry`'s 2-hour TTL has no equivalent in a checkpointer | Medium | Prune job reusing `session_ttl_seconds` (Phase 7, validation decision 2) |
| R8 *(deferred)* | Concurrent requests on one `thread_id` race — a checkpointer is not a lock | Medium | Keep the per-`session_id` `threading.Lock` after `SessionRegistry` is deleted |

## Success Criteria

- [ ] `grep -rn "session\." src/agents/tools/` returns 0 — no tool touches a session object
- [ ] `create_react_agent` appears exactly twice in `src/` (supervisor router + trip agent)
- [ ] Main graph has 6 nodes (router + 5 handlers), no orphan branches
- [ ] `reroute_count` never exceeds 1 across the test suite
- [ ] Hotel-gate characterization test passes — no path produces an itinerary before a hotel is chosen
- [ ] The two mechanism-based gate tests are deleted, not left passing vacuously
- [ ] `pytest` 100% pass, no new skips
- [ ] Per-turn p50 latency within 20% of the Phase 2 baseline
- [ ] Architecture doc states plainly that state is not durable

Deferred with phases 7-8, not delivered by this plan: restart durability,
`SessionRegistry` removal, `interrupt()`-based hotel pick.

## Open questions

1. Plan `260731-1508` is marked `pending` but its code has shipped. Reconcile its
   status before or during Phase 1.
2. *(deferred, phase 7)* EC2 t3.micro is already swap-dependent; a psycopg
   connection pool needs RAM headroom measured before deploying.
3. *(deferred, phase 7)* Which Supabase connection string — direct (5432) or
   session pooler? Needs a decision plus a new deploy secret.

## Validation Log

### Session 1 — 2026-08-02
**Trigger:** `/ak:plan validate` immediately after plan creation
**Questions asked:** 4
**Verification tier:** Full (8 phases, 4 roles)

#### Verification Results
- **Claims checked:** 34
- **Verified:** 30 | **Failed:** 4 | **Unverified:** 0

##### Failures
1. [Contract Verifier] `route_context_from_session` — plan said "the two call
   sites", actual **3** production call sites: `src/agents/session.py:436`,
   `src/agents/session.py:445`, `src/agents/supervisor.py:88`. Plus test
   consumers `tests/test_agents/test_supervisor_routing_accuracy.py:22,146`.
2. [Contract Verifier] `tests/test_api/` omitted from phases 5 and 7 despite
   ~10 `TripSession` / `SessionRegistry` construction sites:
   `test_chat_flow.py:26,60`, `test_routes.py:36,38`,
   `test_chat_session.py:18,61,270,299,328` including class
   `TestSessionRegistryRaces`.
3. [Fact Checker] Two existing gate guard tests were not accounted for:
   `tests/test_agents/test_graph.py:19` and `tests/test_trip_reuse_flow.py:15`.
   Both assert `"generate_full_itinerary" not in tool_names` — the mechanism,
   not the invariant — so both pass vacuously after Phase 4.
4. [Fact Checker] `src/config.py:52` defines `session_ttl_seconds` (2h TTL).
   Deleting `SessionRegistry` removes TTL eviction with no checkpointer
   equivalent; Phase 7 did not address it.

Also noted (not a failure): `src/main.py:14` references `TripSession` only in a
comment — no code dependency, but the comment goes stale after Phase 5.

#### Questions & Answers

1. **[Risks]** Hotel-gate already has 2 guard tests, but they assert
   `"generate_full_itinerary" not in tool_names` — mechanism, not invariant.
   After Phase 4 they pass vacuously. How to handle?
   - Options: Phase 2 writes invariant test, Phase 4 deletes the two old ones |
     Keep both | Convert the two existing tests into invariant form
   - **Answer:** Phase 2 writes the invariant test, Phase 4 deletes the two old ones
   - **Rationale:** A green test that checks nothing is worse than no test — it
     actively suppresses suspicion during the riskiest phase.

2. **[Architecture]** Deleting `SessionRegistry` loses the 2h TTL. Postgres
   checkpoints never expire. How should Phase 7 handle it?
   - Options: Prune job reusing `session_ttl_seconds` | Drop TTL, prune by days |
     Keep both in-process TTL and prune
   - **Answer:** Prune job reusing `session_ttl_seconds`
   - **Rationale:** Preserves today's semantics exactly, only relocating
     enforcement. Avoids an unintended user-visible change.

3. **[Scope]** 8-11 days against under 4 weeks — is the feature freeze agreed?
   - Options: Freeze agreed, run all 8 phases | Not agreed — stop at Phase 6 |
     Only phases 1-2 | Keep full scope without a freeze
   - **Answer:** Not agreed — limit scope to Phase 6
   - **Rationale:** Largest decision of this session. Goal 3 (durable state) is
     dropped. Phases 7-8 stay documented for after Demo Day.

4. **[Assumptions]** How thoroughly should the missed call sites be recorded?
   - Options: Full file:line lists in the phases | A general note
   - **Answer:** Full file:line lists in the phases
   - **Rationale:** The vague "update all callers" phrasing is exactly what let
     failure 2 through in the first place.

#### Confirmed Decisions
- Scope ends at Phase 6; phases 7-8 deferred post-Demo Day
- Goal 3 (durable state) and goal 6 (`interrupt()`) dropped from this delivery
- Phase 4 deletes the two mechanism-based gate tests
- Deferred Phase 7 reuses `session_ttl_seconds` for checkpoint pruning
- All caller lists carry explicit `file:line`

#### Impact on Phases
- Phase 2: document the two existing mechanism tests as the coverage being replaced
- Phase 3: correct to 3 call sites with file:line
- Phase 4: delete both mechanism tests; add `tests/test_api/` consumers
- Phase 5: add `tests/test_api/` (3 files); note the stale `src/main.py:14` comment
- Phase 6: terminal phase; go/no-go gate replaced by a deferred-work handoff
- Phase 7: marked deferred; TTL/prune decision recorded
- Phase 8: marked deferred

### Whole-Plan Consistency Sweep
- Files reread: `plan.md`, `phase-01` … `phase-08`
- Decision deltas checked: 5
- Reconciled stale references: 11 (effort totals, goals table, non-goals,
  phases table, risk IDs R3-R8, success criteria, open questions, phase 6
  framing, phases 7-8 status headers)
- Unresolved contradictions: 0

<!-- slug: langgraph-full-orchestration-and-durable-state -->
