---
phase: 4
title: "Postgres checkpointer"
status: pending
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

- [ ] Checkpoint tables exist in Supabase after startup
- [ ] Graph state survives a process restart
- [ ] With `checkpointer_backend=memory`, behavior is identical to today
- [ ] The existing suite passes immediately after the dependency add, before other changes
- [ ] A pruning job exists and is scheduled
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| psycopg3 alongside psycopg2 breaks the existing DB path | Step 1 runs the full suite right after the dependency add, before anything else changes |
| Context-manager checkpointer does not fit per-session construction | App-lifespan singleton keyed by `thread_id` — the documented pattern |
| Changing `thread_id` semantics disturbs live sessions | Flag-gated, default `memory` on merge; in-memory sessions drain via `SESSION_TTL_SECONDS`. **Open Question 3** |
| Checkpoint table growth | Pruning scheduled in this phase, not deferred |
