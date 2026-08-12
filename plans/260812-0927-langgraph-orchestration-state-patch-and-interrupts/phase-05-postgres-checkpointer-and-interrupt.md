---
phase: 5
title: "Postgres checkpointer and interrupt"
status: pending
priority: P1
effort: "2d"
dependencies: [4]
---

# Phase 5: Postgres checkpointer and interrupt

## Overview

Swap `MemorySaver` for a Supabase-Postgres-backed checkpointer, then use LangGraph
`interrupt()` to ask instead of guess when input is ambiguous. Fixes the "01/07 without a
year" guess and supplies the ask-for-center mechanism Phase 7 needs.

## Problem

**Ambiguity is resolved by guessing.** `_format_start_date` (`trip_intake.py:591`) only
checks that `date.fromisoformat` parses. There is no year-presence check, no past-date
check, no confirmation. Today is 2026-08-12; "01/07" resolves to a past date, which the
LLM invents a year for. The hotel RPC then joins `room_prices` over a past range, returns
nothing, and the user is told *"Không tìm thấy khách sạn có tọa độ hợp lệ"* — an error about
coordinates for a problem about dates.

`interrupt` appears **zero times** in the repo. `MemorySaver` is the only checkpointer
(`graph.py:92`), so there is nothing to resume from.

## Verified constraints

Checked against the installed versions and current docs, not assumed:

| Fact | Evidence |
|---|---|
| `langgraph` 1.2.9, `langgraph-checkpoint` 4.1.1 installed | `pip list` |
| `langgraph-checkpoint-postgres` **not installed** | `pip list` |
| Driver present is `psycopg2-binary` 2.9.12; `PostgresSaver` needs **psycopg3** | `pip list` + LangGraph docs |
| Install line: `pip install -U "psycopg[binary,pool]" langgraph-checkpoint-postgres` | https://docs.langchain.com/oss/python/langgraph/add-memory |
| `PostgresSaver.from_conn_string(...)` is a **context manager**; `.setup()` creates tables | https://docs.langchain.com/oss/python/langgraph/persistence |
| Resume protocol is `Command(resume=value)`; interrupts surface on the stream | https://docs.langchain.com/oss/python/langgraph/interrupts |
| `DATABASE_URL` and `SUPABASE_DB_PASSWORD` already exist in env | `.env` key scan |

Two consequences for design:

1. `from_conn_string` being a context manager conflicts with today's per-session
   `MemorySaver()` construction inside `build_trip_agent`. The checkpointer must become an
   **app-lifespan singleton** shared across sessions, keyed by `thread_id`.
2. `interrupt()` only works inside a graph node — which is why this phase depends on Phase 4
   turning intake into a node.

## Requirements

- Functional: a date without a year asks for the year instead of inventing one.
- Functional: a start date in the past is rejected with a specific message naming the reason.
- Functional: graph state survives a process restart; a resumed thread continues mid-question.
- Functional: `Command(resume=...)` carries the user's next message into the paused node.
- Non-functional: `psycopg2-binary` stays installed — adding psycopg3 must not break the
  existing Supabase client path.
- Non-functional: rollout is flag-gated; `MemorySaver` remains selectable.

## Architecture

- Add `psycopg[binary,pool]` and `langgraph-checkpoint-postgres` to `requirements.txt`.
  Both drivers coexist: nothing currently imports `psycopg` (v3), and `supabase-py` uses HTTP.
- Build the checkpointer once in the FastAPI lifespan and inject it into `build_trip_agent`,
  replacing the per-session `MemorySaver()` at `graph.py:92`.
- Run `.setup()` once at startup (idempotent) against `DATABASE_URL`.
- `settings.checkpointer_backend = "memory" | "postgres"` gates the swap.
- Ambiguity detection is **deterministic and lives in Phase 2's validators**, not in the model:
  `dates.start` rejects a missing year, a past date, and an implausible range. The node calls
  `interrupt()` with the specific question; the model never decides whether input was ambiguous.
- Reuse the pattern already proven for prices — `MIN_PLAUSIBLE_PRICE_VND` /
  `_sanitize_price` is the same class of defence, applied to dates.

## Related Code Files

- Modify: `backend/requirements.txt` — add `psycopg[binary,pool]`, `langgraph-checkpoint-postgres`
- Modify: `backend/src/agents/graph.py` — accept an injected checkpointer (:92)
- Modify: `backend/src/main.py` — lifespan-scoped checkpointer + `.setup()`
- Modify: `backend/src/config.py` — `checkpointer_backend` setting
- Modify: `backend/src/services/travel_state.py` — `dates.start` / `dates.end` validators
- Modify: `backend/src/agents/nodes/extract_patch.py` — raise ambiguity instead of guessing
- Modify: `backend/src/agents/session.py` — resume path via `Command(resume=...)`
- Modify: `backend/src/api/routes.py` — surface a paused turn to the client

## Implementation Steps

1. Add dependencies; verify `psycopg2` and `psycopg` coexist by running the existing suite first.
2. Move checkpointer construction to the app lifespan; inject into `build_trip_agent`.
3. Add the `checkpointer_backend` setting, defaulting to `memory` so nothing changes on merge.
4. Run `.setup()` at startup against `DATABASE_URL`; confirm the checkpoint tables land in Supabase.
5. Add date validators: missing year, past date, end ≤ start, implausible span.
6. Call `interrupt()` from the intake node when a validator reports ambiguity.
7. Implement resume: the next user message becomes `Command(resume=<message>)`.
8. Test restart durability: pause on the year question, restart the process, resume, complete.
9. Flip the default to `postgres` only after step 8 passes.

## Success Criteria

- [ ] "01/07" asks which year instead of picking one
- [ ] Answering the year resumes the same turn without re-asking earlier slots
- [ ] A past start date is rejected with a date-specific message, not a coordinates error
- [ ] A paused thread survives a process restart and resumes correctly
- [ ] Checkpoint tables exist in Supabase after startup
- [ ] With `checkpointer_backend=memory`, behavior is identical to today
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| psycopg3 alongside psycopg2 breaks the existing DB path | Run the full suite immediately after the dependency add, before any code change. Nothing imports psycopg3 today; `supabase-py` is HTTP |
| Context-manager checkpointer does not fit per-session agent construction | App-lifespan singleton, sessions keyed by `thread_id` — the documented pattern |
| Persistent checkpointer changes `thread_id` semantics for live sessions | Flag-gated, default `memory` on merge. In-memory sessions drain via `SESSION_TTL_SECONDS`. **Open question 1 in plan.md** |
| Checkpoint table growth | Docs recommend a pruning cron; schedule it in this phase, not later |
| `interrupt()` inside a node the deterministic cascade calls directly | Phase 4 already moved intake into a node — hard dependency, enforced by phase ordering |
| A paused turn confuses the frontend | Paused turns return an existing `stage` with the question as `reply`; no new client contract |
