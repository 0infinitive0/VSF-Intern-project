---
phase: 7
title: "Postgres Checkpointer And Registry Removal"
status: deferred
priority: P3
effort: "1d"
dependencies: [6]
---

# Phase 7: Postgres Checkpointer And Registry Removal

> **DEFERRED — out of scope for this delivery** (validation session 1,
> 2026-08-02). No feature freeze was agreed and Demo Day is under four weeks
> out, so delivery ends at Phase 6. The design below is verified and kept for
> after Demo Day. Do not start it without an explicit scope change.

<!-- Updated: Validation Session 1 - deferred out of scope; TTL/prune decision recorded -->

## Overview

Swap `MemorySaver` for `PostgresSaver` so trip state survives a restart, and
delete `SessionRegistry` — its TTL, cap, and eviction responsibilities move to
the checkpointer.

Only meaningful because phases 3-5 moved state into the graph. Before those,
this phase would have persisted the message list and nothing else.

**Deferred.** Phase 6's original go/no-go gate was resolved in advance by
validation session 1: the answer was no. Restarting this phase requires an
explicit scope change after Demo Day, not a judgement call at Phase 6.

## Requirements

- Functional: restart the process mid-conversation; the next turn still sees
  `trip_data`, intake facts, and hotel preferences.
- Non-functional: the connection pool outlives a single request.
- Non-functional: concurrent requests on one `session_id` remain serialized.

## Architecture

**New dependency.** `requirements.txt` has neither package:

```
psycopg[binary,pool]>=3.2
langgraph-checkpoint-postgres>=2.0
```

**New configuration.** Verified: `src/config.py:42-49` has `database_url`
(sqlite default) and `supabase_url` / `supabase_service_key` — **no Postgres
DSN**. `supabase_url` is an HTTPS REST endpoint and cannot be used here. Add a
distinct `checkpointer_dsn` setting plus a new deploy secret. Do not overload
`database_url`, whose sqlite default would fail confusingly.

**Pool lifetime — the trap.** The docs example is

```python
with PostgresSaver.from_conn_string(DB_URI) as checkpointer: ...
```

which closes the pool on context exit. In FastAPI that means the *next* request
gets a dead pool. Build it once in the lifespan instead:

```python
pool = ConnectionPool(dsn, min_size=1, max_size=5, kwargs={"autocommit": True})
checkpointer = PostgresSaver(pool)
```

Size the pool against FastAPI's threadpool; t3.micro is already swap-dependent,
so start at `max_size=5` and measure.

**Supabase pooler mode.** The transaction pooler (port 6543, pgbouncer
transaction mode) breaks the prepared statements psycopg uses. Use the direct
connection (5432) or the session pooler. Assert the port at startup and fail
loudly with a clear message rather than dying at the first checkpoint write.

**`setup()` runs once** — at startup or as a migration step, never per request.
It creates the checkpoint tables in `public`.

**Registry removal.** `SessionRegistry` (`session.py:629-706`) holds TTL, cap,
eviction, and a per-session `threading.Lock`. The checkpointer replaces the
storage; it is **not** a lock. Keep a small `{session_id: Lock}` map so two
concurrent requests on one thread cannot interleave writes.

**Retention — and the TTL that would otherwise be silently lost.**
`SessionRegistry` enforces a 2-hour session TTL from `src/config.py:52`
(`session_ttl_seconds`, default 7200). A checkpointer has no TTL: once state
moves to Postgres, conversations live forever unless something deletes them.
Deleting the registry without replacing this is an unannounced behavior change —
a user returning after three hours would resume an old trip instead of starting
fresh.

Decision (validation session 1): **keep `session_ttl_seconds` and have the prune
job enforce it.** Same semantics as today, different enforcement point. Do not
repurpose the key or change its default as part of this phase.

## Related Code Files

- Modify: `requirements.txt`
- Modify: `src/config.py` — add `checkpointer_dsn`
- Modify: `src/main.py` — lifespan: build pool, `setup()`, dispose on shutdown
- Modify: `src/agents/graph.py` — accept an injected checkpointer instead of constructing `MemorySaver`
- Modify: `src/agents/session.py:629` — delete `SessionRegistry`; keep the lock map
- Modify: `src/api/routes.py:20,48` — `SessionRegistry` import and instantiation
- Modify: **`tests/test_api/`** — `test_chat_flow.py:26,60`, `test_routes.py:36,38`,
  `test_chat_session.py:18,61,270,299,328`. Includes class
  `TestSessionRegistryRaces`, whose concurrency cases must be retargeted at the
  retained per-`session_id` lock rather than deleted — they are the only
  coverage of the race this phase risks reintroducing
- Keep: `src/config.py:52` `session_ttl_seconds` — now enforced by the prune job
- Create: `scripts/prune_checkpoints.py`
- Modify: `.env.example`, `docs/setup/` — new secret
- Create: `tests/test_checkpointer_durability.py`

## Implementation Steps

1. Add both dependencies; pin minimums.
2. Add `checkpointer_dsn` to `Settings`; document it in `.env.example`. **Never
   commit a real DSN.**
3. Startup assertion: DSN is `postgresql://` and not port 6543. Fail with an
   explicit message naming the pooler problem.
4. Build `ConnectionPool` + `PostgresSaver` in the FastAPI lifespan; dispose on
   shutdown. Run `setup()` once, idempotently.
5. Inject the checkpointer into `build_trip_agent` / graph compilation. Keep
   `MemorySaver` as the default for tests so the suite needs no database.
6. Write the durability test: three turns → dispose the graph and rebuild from
   the same `thread_id` → assert `trip_data`, intake facts, and hotel prefs are
   intact. This is the phase's whole point.
7. Delete `SessionRegistry`; keep `{session_id: Lock}`. Update `routes.py` and
   all of `tests/test_api/`, retargeting `TestSessionRegistryRaces` at the
   retained lock instead of deleting it.
8. Write `scripts/prune_checkpoints.py` enforcing `session_ttl_seconds`;
   document the schedule. Verify a thread older than the TTL stops resuming.
9. Measure RAM on t3.micro with the pool live — before deploying, per the plan's
   open question.
10. Manual restart test against the real deployment, not just pytest.

## Success Criteria

- [ ] Restart the process mid-conversation; the next turn sees prior `trip_data`
- [ ] `tests/test_checkpointer_durability.py` passes
- [ ] Test suite still runs with no database (`MemorySaver` default)
- [ ] Startup rejects a port-6543 DSN with an explicit message
- [ ] Pool built once in the lifespan; no `with ... from_conn_string()` in request paths
- [ ] `setup()` runs once, not per request
- [ ] `grep -rn "SessionRegistry" src/` returns 0; per-session lock retained
- [ ] Concurrent-request test on one `session_id` shows no interleaved writes
- [ ] `scripts/prune_checkpoints.py` exists, enforces `session_ttl_seconds`, and is documented
- [ ] A conversation older than `session_ttl_seconds` no longer resumes — TTL semantics unchanged from today
- [ ] `TestSessionRegistryRaces` retargeted at the retained lock, not deleted
- [ ] t3.micro RAM headroom measured and recorded with the pool live
- [ ] No DSN or secret committed

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Pool closed after the first request → intermittent 500s that surface during the demo | Lifespan-scoped pool; explicit criterion forbidding `with ... from_conn_string()` in request paths |
| Transaction-pooler DSN breaks psycopg prepared statements | Startup assertion on port 6543 with a message naming the cause |
| t3.micro OOM once the pool is live | Step 9 measures before deploy; `max_size` starts at 5 |
| Test suite starts requiring a live database | `MemorySaver` stays the default for tests; only the durability test needs Postgres |
| Checkpoint tables grow unbounded | Prune script plus documented schedule |
| Deleting `SessionRegistry` also deletes the lock, allowing interleaved writes | The lock map is explicitly retained and covered by a concurrency test |
| A DSN with a password is committed | `.env.example` carries a placeholder only; secret scanning before commit |
