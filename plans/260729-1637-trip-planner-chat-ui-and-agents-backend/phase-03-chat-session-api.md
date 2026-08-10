---
phase: 3
title: "Per-session state and structured chat API"
status: pending
priority: P1
effort: "5h"
dependencies: [2]
---

# Phase 3: Per-session state and structured chat API

## Overview

Put the re-layered agent behind the contract frozen in Phase 1: explicit session
creation, a chat turn returning structured hotel options or itinerary alongside the
existing text and chips, plan retrieval, and session reset.

> Supersedes the 2026-07-29 version, which assumed the chat endpoint did not exist yet.
> It does — `POST /api/v1/planner_chat` (`routes.py:21-38`). This phase **hardens and
> extends** it rather than creating it.

## Requirements

- Functional: all four endpoints from `docs/chat_api_contract.md`.
- Functional: `stage`, `hotel_options` and `trip_plan` reflect what actually happened.
- Functional: `reply` and `suggestions` keep their exact current meaning (D10) — the
  `GET /chat` page must keep working with no change to it.
- Functional: a `session_id` the server never issued is a 404, not a new session.
- Functional: existing `/api/v1/status`, `/search_attractions`, `/search_hotels` keep working.
- Non-functional: a 60s plan build does not block other sessions.
- Non-functional: two concurrent requests on the *same* session serialize.
- Non-functional: quality gate per D11.

## Architecture

### What already exists, and what is wrong with it

`routes.py:21-38` is the starting point, not a blank page:

```python
_CHAT_SESSIONS: dict[str, ChatSession] = {}          # :18

@router.post("/planner_chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:   # def — correct
    session = _CHAT_SESSIONS.get(request.session_id)
    if session is None:
        session = create_chat_session(request.session_id)               # auto-creates any id
        _CHAT_SESSIONS[request.session_id] = session                    # unsynchronized
    try:
        reply = process_chat_turn(session, request.message)
        suggestions = suggestions_for(session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))             # leaks exception text
    return PlannerChatResponse(reply=reply, suggestions=suggestions)
```

| Keep | Fix |
|---|---|
| `def`, not `async def` — the docstring already records why | Bare dict → `SessionRegistry` from Phase 2, with its lock, TTL and cap |
| `suggestions_for(session)` on every turn | Auto-create on any id → `resolve` or 404; creation only via `POST /chat/session` |
| `PlannerChatRequest`/`Response` model names and path | `detail=str(e)` → generic 5xx body, exception to the log only |
| The `reply` field's meaning | No `stage` / `hotel_options` / `trip_plan` / `intake` |
| | `session_id: str` → `UUID`, so malformed ids are rejected at the boundary |

**`UUID` is safe for `GET /chat` — settled, not deferred** (RT-6). The page generates
its id with `crypto.randomUUID()` (`src/templates/chat.html:200,349`, stored under
`vsf_trip_planner_session_id` at `:194`) and posts it at `:312`. Typing the field as
`UUID` does not break it.

Two non-UUID callers remain and must not be forgotten:

- The CLI passes the literal `poc_trip_planner_1` (`terminal_chat.py:57,69`). It never
  crosses HTTP, so the pydantic type does not reach it — but the Phase 2 debug-hook
  validator does, and `[A-Za-z0-9_-]+` accepts it.
- `tests/test_api/test_routes.py` already sends `str(uuid.uuid4())` (`:32,41,55`), so
  the existing tests pass unchanged.

### Turn routing lives in `agents/session.py`, not here

`process_chat_turn` owns all seven branches. The endpoint calls it and does not
re-implement routing. The full order is in `plan.md` and `docs/chat_api_contract.md`;
the handler's only job is session resolution, locking, and response assembly.

### `stage` is derived, not routed

`agents/session.py`'s agent fallthrough is a single unconditional `agent.stream()` call
— the shared core makes no distinction between an "edit" turn and any other agent turn,
so the API cannot mirror one. Derive `stage` from **which tool actually ran**:

| Tool observed | `stage` |
|---|---|
| `recommend_hotels` | `hotel_options` |
| `select_hotel` (success) | `planned` |
| `modify_trip_plan` / `execute_trip_edit_request` (success) | `modified` |
| `finalize_trip_plan` (success) | `finalized` |
| no tool, intake or hotel-preference gate asked a question | `intake` |
| any tool output starting `SYSTEM ERROR:` | `error` |

**Four of the branches call tools directly, not through the agent** — and only the
fallthrough uses the agent at all. Verified 2026-07-31 (RT-1):

| Site | Call | Produces |
|---|---|---|
| `chat_session.py:242` | `select_hotel.invoke(...)` | `planned` |
| `chat_session.py:265` | `finalize_trip_plan.invoke({})` | `finalized` |
| `chat_session.py:296` | `execute_trip_edit_request(...)` | `modified` |
| `chat_session.py:350` | `recommend_hotels.invoke(...)` | **`hotel_options`** |
| `chat_session.py:362` | `session.agent.stream(...)` | whatever the LLM chose |

(`:309` and `:319` also call `modify_trip_plan` directly but are inside the dead blocks
Phase 1 removes.)

Observing only the agent's event stream misses **all four** — including
`recommend_hotels`, which produces the hotel-card turn this whole plan exists to
deliver, and `finalize_trip_plan`. An implementation that instruments only the stream
yields `stage="intake"` forever and the React UI never renders a card.

Have `process_chat_turn` return the observed tool name alongside the reply (a small
`TurnResult` dataclass), set at each of the five sites above. That keeps the derivation
in one place and makes it testable without HTTP. Do **not** infer the tool in the
endpoint.

This derivation is **new logic with no CLI equivalent** — it needs its own tests and
cannot be validated by "does it match the CLI".

### Sync handlers, per-session lock

```python
@router.post("/planner_chat", response_model=PlannerChatResponse)
def planner_chat(request: PlannerChatRequest) -> PlannerChatResponse:   # def, not async def
    registry.evict_expired()                      # skips sessions whose lock is held
    session = registry.resolve(request.session_id)  # 404 if unknown; never auto-creates
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    with session.lock:
        ...
```

`def` hands the request to Starlette's threadpool so blocking Supabase/Ollama work never
stalls the event loop. `session.lock` serializes same-session turns — **provided** both
requests get the same `TripSession` object, which is what the registry's own lock
guarantees (Phase 2).

Eviction runs before the lock is taken, so it **must** skip locked sessions. Otherwise a
session inside a 60s tool call is evicted, the next request builds a fresh one, and the
two run concurrently on state the caller believes is one conversation.

`DELETE /chat/{session_id}` is reachable by anyone holding the id. Acceptable for a
localhost PoC with no auth, but do not treat the id as a secret or put it in a shared URL.

### Response assembly

Derive `stage`, `hotel_options` and `trip_plan` in **one** place from the session plus
the turn result — not per branch, or they will drift:

```python
PlannerChatResponse(
    session_id=session.session_id,
    reply=result.text,
    suggestions=suggestions_for(session),                                    # unchanged contract
    stage=derive_stage(result),
    hotel_options=to_hotel_options_payload(session.pending_hotel_selection), # [] unless staged
    trip_plan=to_trip_plan_payload(session.trip_data) if session.trip_data else None,
    intake=IntakeStatus.from_state(session.intake_state),
)
```

`suggestions` and `hotel_options` describe the same pending list at different fidelities
and **must not disagree**. `suggestions[i].value` is the ordinal string;
`hotel_options[i].index` is the same ordinal as an int. Build both from
`session.pending_hotel_selection` in this one place, and assert their agreement in a test
— a client that renders cards from one and posts from the other will otherwise send the
wrong hotel the first time the two derivations drift.

`SYSTEM ERROR:`-prefixed tool output → `stage="error"`, message in `reply`, HTTP **200**
so the UI renders it as a chat turn. Only genuine server faults 5xx.

**Sanitize both paths.** The tree leaks raw exception text in two ways, and neither is
acceptable on a surface a browser reaches:

- Tools build `f"SYSTEM ERROR: {exc}"` at **8** sites (`planner_tools.py:130,242,322,427,
  480,490,559,562` pre-move), where `exc` can carry Supabase RPC names, table/column
  names, or connection detail. Before returning, map anything that is not one of the
  hand-written, non-parameterized `SYSTEM ERROR:` strings to a generic Vietnamese
  message; log the original server-side with the session id.
- Every current handler does `raise HTTPException(status_code=500, detail=str(e))`
  (`routes.py:37,51,115,136,163`). Do **not** copy that pattern into the new endpoints,
  and fix `planner_chat`'s existing one at `:37`. 5xx bodies are a fixed generic
  message; the exception goes to the log only.

### The JSON files

Server mode does **not** write `data/current_trip_plan.json` or
`data/pending_hotel_selection.json` — they are global mutable state and defeat
per-session isolation, which is the entire point of Phase 2. Mechanically this is just
"leave `session.persist_hook` unset", not a flag threaded through call sites.

Under `DEBUG_TRIP_PLAN_FILE=1` the server installs a hook that writes to
`debug/{session_id}/` — **not** the bare filenames. Writing the global paths from a
multi-session server would resurrect the exact cross-session overwrite bug this plan
exists to remove, and an intern debugging a shared deployment is precisely who would flip
that flag.

Supabase persistence via `ItineraryStore` is unaffected and still runs on finalize. It
writes with the service-role key (`get_supabase_client` reads `SUPABASE_SERVICE_KEY`,
`trip_builder_svc.py:107`) and is **not** gated by `ENABLE_ITINERARY_REUSE` — that flag
is defined at `trip_builder_svc.py:58` and gates only the read path at `:251`, so any
anonymous session can
persist an itinerary. With Phase 2's session-id stamping those rows become attributable;
leave the reuse flag off until someone owns moderation.

## Related Code Files

- Modify: `src/api/routes.py` — harden `planner_chat`, add three endpoints, replace the
  stub `POST /chat` demo agent or remove it
- Modify: `src/models/schemas.py` — extend `PlannerChatRequest` (`session_id` typed) and
  `PlannerChatResponse` (+ `session_id`, `stage`, `hotel_options`, `trip_plan`,
  `intake`), plus `TripPlanPayload` / `HotelSummary` / `HotelOption` / `DayPlan` /
  `ItineraryItem` / `IntakeStatus`
- Modify: `src/agents/session.py` — return a `TurnResult` carrying the observed tool name
- Modify: `src/config.py` — `session_ttl_seconds`, `max_sessions`,
  `debug_trip_plan_file`, and `:5173` in `cors_origins`
- Read only: `src/services/trip_formatter.py`, `src/templates/chat.html` (to confirm the
  session-id format before typing the field)
- Create: `tests/test_api/test_chat_session.py`

## Implementation Steps

1. Run `impact({target: "planner_chat", direction: "upstream"})` and
   `impact({target: "PlannerChatResponse", direction: "upstream"})` before editing.
2. Type `session_id` as `UUID` — already settled against `chat.html:200,349` (RT-6).
   No investigation step needed; just confirm the page still round-trips after step 7.
3. Add the pydantic models. Keep `message` required with `min_length=1` and `session_id`
   required so the existing 422 tests hold.
4. Instantiate one module-level `SessionRegistry` in `routes.py`, replacing `_CHAT_SESSIONS`.
5. Implement `POST /chat/session`, `GET /chat/{sid}/plan`, `DELETE /chat/{sid}`.
6. Add `TurnResult` to `agents/session.py` so the observed tool name reaches the handler.
   Set it at **all five** call sites in the table above (`:242,265,296,350,362`
   pre-move), not only the agent stream. Missing `:350` alone kills the hotel-card flow.
7. Harden `planner_chat`: registry resolve + 404, per-session lock, eviction, sanitized
   errors, and the one-place response assembly.
8. Add `:5173` to the default `cors_origins` — the Vite proxy covers the common case but
   direct calls should work.
9. Tests with the agent and planner mocked — no Supabase, no Ollama in CI. Extend the
   existing `tests/test_api/test_routes.py` fixtures rather than duplicating them:
   - bare "Nha Trang" → `stage="intake"`, `missing` lists duration and people
   - completed intake → hotel-preference question, still `stage="intake"`
   - completed preferences → `stage="hotel_options"` with a populated array, `trip_plan` null
   - `suggestions[i].value == str(hotel_options[i].index)` for the same turn
   - a numeric reply while a selection is pending → `select_hotel` path, not the agent;
     `stage="planned"`, `trip_plan` present
   - a **non**-choice reply while a selection is pending → the list is dropped and the
     message is handled on its merits (branch 1c; this is the shipped fix from `3bd9e80`)
   - two sessions do not see each other's `trip_data` **or** pending selection
   - `DELETE` then `GET plan` → 404
   - `SYSTEM ERROR:` output → 200 with `stage="error"`, body contains no raw exception text
   - an unknown but well-formed `session_id` → 404, and no session is created
   - a malformed `session_id` → 422
   - **race:** N threads posting the same new `session_id` all end up on one `TripSession`
   - **race:** a session whose lock is held is not evicted by a concurrent turn
   - `stage` derivation, **one test per direct-call site** (RT-1): mocked
     `recommend_hotels` → `hotel_options`; `select_hotel` → `planned`;
     `execute_trip_edit_request` → `modified`; `finalize_trip_plan` → `finalized`.
     None of these go through the agent stream, so a stream-only implementation passes
     zero of them
10. Drive `GET /chat` through a full browser conversation after the changes — it must
    still work unmodified (D10).

## Success Criteria

- [ ] All four endpoints match `docs/chat_api_contract.md` field for field
- [ ] `tests/test_api/test_routes.py` passes unchanged
- [ ] `GET /chat` completes a full conversation with no edit to `src/templates/chat.html`
- [ ] New tests green with no network access
- [ ] Two curl sessions reach different hotel lists; neither overwrites the other
- [ ] `suggestions` and `hotel_options` never disagree on the pending list — asserted
- [ ] `/docs` renders the chat schema with no `Any`-typed holes
- [ ] Server writes neither JSON file unless `DEBUG_TRIP_PLAN_FILE=1`, and then only
      under `debug/{session_id}/`
- [ ] No response body on any endpoint contains `str(exception)` text — including the
      five pre-existing `detail=str(e)` sites
- [ ] Unknown `session_id` → 404; the server never creates a session it did not issue
- [ ] D11 gate: no new test failures, `ruff` clean on touched files

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Handler written `async def` by reflex → event loop stalls 60s per plan build | The shipped `planner_chat` is already `def` with the reason in its docstring; preserve it. The two-session concurrency test catches a regression |
| Typing `session_id` as `UUID` breaks `GET /chat` | **Resolved, not mitigated** (RT-6): the page uses `crypto.randomUUID()` (`chat.html:200,349`) and the existing API tests send real UUIDs. The success criterion still requires an unmodified page to work end to end |
| **`stage` derived only from the agent stream → all four direct-call sites go undetected** and `hotel_options` never fires (RT-1) | The call-site table names all five sites with line numbers; `TurnResult` is set at each. Four tests, one per direct-call site. This is the single easiest way to ship a plan that looks complete and renders no hotel cards |
| `suggestions` and `hotel_options` drift → clicking a card sends the wrong hotel | Both built in one place from one source; equality asserted in a test |
| Branch 1c dropped when reimplementing → the hotel-list trap returns | It has its own test in step 9. This bug shipped once and was fixed in `3bd9e80`; regressing it is a visible product failure |
| Registry races defeat the per-session lock silently | Two race tests; the registry lock itself is Phase 2's deliverable |
| Raw exception text reaches the browser by copying the existing `detail=str(e)` pattern | Explicit "do not copy" instruction, plus a success criterion that covers the five pre-existing sites |
| Intake gate bypassed → LLM invents a destination | Test asserts a bare city name yields a question, not a hotel list |
| Long request killed by an upstream proxy (D3 has no streaming) | Document a 120s proxy timeout in the setup guide; the UI shows elapsed seconds. SSE is the escalation if it bites |
| Registry grows unbounded | TTL + cap from Phase 2, evicted at the top of each turn |
