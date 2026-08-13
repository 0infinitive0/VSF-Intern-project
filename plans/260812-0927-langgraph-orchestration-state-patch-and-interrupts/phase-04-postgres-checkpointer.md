---
phase: 4
title: "Postgres checkpointer"
status: done
priority: P1
effort: "1.5d"
dependencies: []
---

# Phase 4: Postgres checkpointer

## Overview

Replace `MemorySaver` with a Supabase-Postgres-backed checkpointer. Prerequisite for the graph
(Phase 5) and hard prerequisite for `interrupt()` (Phase 7) — there is nothing to resume from
without durable checkpoints.

## Verified constraints

Checked against installed versions and current docs, not assumed:

| Fact | Evidence |
|---|---|
| `langgraph` 1.2.9, `langgraph-checkpoint` 4.1.1 installed | `pip list` |
| `langgraph-checkpoint-postgres` **not installed** | `pip list` |
| Driver present is `psycopg2-binary` 2.9.12; `PostgresSaver` needs **psycopg3** | `pip list` + docs |
| Install: `pip install -U "psycopg[binary,pool]" langgraph-checkpoint-postgres` | https://docs.langchain.com/oss/python/langgraph/add-memory |
| `PostgresSaver.from_conn_string(...)` is a **context manager**; `.setup()` creates tables | https://docs.langchain.com/oss/python/langgraph/persistence |
| `DATABASE_URL` and `SUPABASE_DB_PASSWORD` already in env | `.env` key scan |

The context-manager shape conflicts with today's per-session `MemorySaver()` construction inside
`build_trip_agent` (`graph.py:92`). The checkpointer must become an **app-lifespan singleton**
shared across sessions, keyed by `thread_id`.

Second benefit, worth stating: a durable checkpointer is also what lifts the current
single-uvicorn-worker constraint that in-memory `SessionRegistry` imposes.

## Requirements

- Functional: graph state survives a process restart; a thread resumes where it stopped.
- Functional: checkpoint tables are created idempotently at startup.
- Non-functional: `psycopg2-binary` keeps working — adding psycopg3 must not break the existing
  Supabase path.
- Non-functional: flag-gated via `checkpointer_backend = "memory" | "postgres"`, default
  `memory` on merge.
- Non-functional: checkpoint growth has a pruning policy from day one, not as a follow-up.

## Architecture

- Add `psycopg[binary,pool]` and `langgraph-checkpoint-postgres` to `requirements.txt`. Both
  drivers coexist: nothing currently imports psycopg3, and `supabase-py` is HTTP.
- Build the checkpointer once in the FastAPI lifespan; inject it into agent/graph construction,
  replacing the per-session `MemorySaver()`.
- Run `.setup()` once at startup against `DATABASE_URL`.
- Schedule the pruning job the docs recommend.

## Related Code Files

- Modify: `backend/requirements.txt`
- Modify: `backend/src/main.py` — lifespan-scoped checkpointer + `.setup()`
- Modify: `backend/src/agents/graph.py` — accept an injected checkpointer (:92)
- Modify: `backend/src/config.py` — `checkpointer_backend`
- Create: `backend/tests/test_checkpointer.py`

## Implementation Steps

1. Add dependencies; run the **full existing suite immediately**, before any code change, to
   prove psycopg2/psycopg3 coexistence.
2. Move checkpointer construction to the app lifespan; inject it.
3. Add `checkpointer_backend`, default `memory`.
4. Run `.setup()` at startup; confirm the tables land in Supabase.
5. Test restart durability: write state, restart the process, read it back.
6. Add the pruning job.
7. Flip the default to `postgres` only after step 5 passes.

## Success Criteria

- [ ] Checkpoint tables exist in Supabase after startup — code path is correct (`ConnectionPool` against the
      Supavisor pooler DSN, `.setup()` at startup) but unverified against a real database: this session's sandbox
      blocked a live connection attempt (permission classifier) and had no local Postgres available (Docker
      paused). Run `RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS=1 CHECKPOINTER_DATABASE_URL=<pooler DSN> pytest
      tests/test_checkpointer.py -k live_restart` (or point it at a local `postgres:16` container) to close this.
- [ ] Graph state survives a process restart — same verification gap. Additionally, do **not** flip
      `checkpointer_backend` to `postgres` until the message-duplication risk below is resolved.
- [x] With `checkpointer_backend=memory`, behavior is identical to today — verified: the memory branch injects
      nothing; `build_trip_agent`'s pre-existing `checkpointer=None` fallback is untouched. Confirmed via a
      failing-test-name diff against a clean `git worktree` checkout (same names, zero new failures).
- [x] The existing suite passes immediately after the dependency add, before other changes — verified: psycopg2
      2.9.12 and psycopg3 3.3.4 import side by side; full suite run before any other code change.
- [x] A pruning job exists and is scheduled — two mechanisms, both unit-tested: event-triggered (`delete_thread`
      from `SessionRegistry.evict_expired`/`drop`, piggybacking on the existing TTL-eviction trigger) for live
      sessions, plus a startup SQL-aggregate sweep for threads orphaned by a restart (bounded, best-effort at
      very large scale — see risk row below).
- [x] `make test` green — confirmed by failing-test-*name* diff (not count) against a clean checkout: 44
      pre-existing, environment-dependent failures (no live Ollama; some reference missing absolute-path
      fixtures) on both sides, byte-identical, zero new. 523 passed, 2 skipped (one pre-existing, one this
      phase's opt-in live-Postgres test).

## Risk Assessment

| Risk | Mitigation |
|---|---|
| psycopg3 alongside psycopg2 breaks the existing DB path | Step 1 runs the full suite right after the dependency add, before anything else changes |
| Context-manager checkpointer does not fit per-session construction | App-lifespan singleton keyed by `thread_id` — the documented pattern |
| Changing `thread_id` semantics disturbs live sessions | Flag-gated, default `memory` on merge; in-memory sessions drain via `SESSION_TTL_SECONDS`. **Open Question 3** |
| Checkpoint table growth | Event-triggered pruning plus a bounded startup orphan sweep, both in this phase, not deferred. Sweep is best-effort past its `limit` — see the table-growth open question below |
| Direct `db.<project_ref>.supabase.co` connection is IPv6-only, unreachable from this project's Docker/EC2 deployment | Discovered and fixed during code review (verified via real DNS resolution): connect through the Supavisor pooler DSN instead, supplied whole via `CHECKPOINTER_DATABASE_URL` rather than derived from `SUPABASE_URL` |
| **Message transcript duplicates on every restart when `session_persistence_enabled=true`** | **Not yet fixed — blocks flipping the default.** `session_store`'s rehydrated `HumanMessage`/`AIMessage` objects carry no stable `id`, so LangGraph's `add_messages` reducer can't dedupe them against the same turns already sitting in a restored Postgres checkpoint; proven empirically (2 messages → 4 after one simulated reseed). Two candidate fixes, not yet chosen: give rehydrated messages stable ids in `session_store`, or skip the transcript reseed when the thread already has checkpoint state. Needs a deliberate decision before Postgres becomes the default |
