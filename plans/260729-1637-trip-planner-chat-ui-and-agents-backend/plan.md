---
title: "Trip Planner Chat UI And Agents Backend"
description: "Re-layer the trip planner into services/agents/cli, replace the two global JSON files with per-session state, return structured itinerary and hotel payloads, and build a React/Vite chat UI."
status: pending
priority: P1
effort: "3-4d"
branch: "main"
tags: [chatbot, langgraph, agents, react, vite, trip-planner]
blockedBy: []
blocks: []
created: 2026-07-29
updated: 2026-07-30
---

# Trip Planner Chat UI And Agents Backend

> **Revised 2026-07-30** against the tree at `3bd9e80`. Eight commits landed since the
> 2026-07-29 draft, including a working web chat endpoint and page. The plan's
> *destination* is unchanged; roughly half its *premises* are now wrong. See
> "What changed" below. The 2026-07-29 revision note (upstream's `scripts/` → `src/cli/`
> extraction) is folded in and no longer repeated.

## Overview

Upstream now ships a functioning web chat: `POST /api/v1/planner_chat` and a
server-rendered `GET /chat` page, both driven by a new transport-agnostic
`src/services/chat_session.py` shared with the CLI. That closes the "CLI and web
share one core" goal **behaviourally**. Four things remain:

1. **De-globalize** — state still lives in two module-level JSON files under `data/`.
   26 call sites read or write them. Two browser sessions still overwrite each other,
   which is now worse than in July: a real multi-session HTTP endpoint ships on top
   of process-global state.
2. **Re-layer** — 1741 lines of business logic and 573 lines of agent wiring sit in a
   package named `cli`, and `services/chat_session.py` imports *upward* from `src.cli`,
   inverting the intended dependency direction.
3. **Structure the payload** — `PlannerChatResponse` is `{reply, suggestions}`. No
   `stage`, no `hotel_options[]`, no `trip_plan`. A client cannot render an itinerary
   panel from it.
4. **Build the React UI** — nothing exists in `frontend/`.

## What changed since the 2026-07-29 revision

| Plan item (2026-07-29) | Status on 2026-07-30 |
|---|---|
| "CLI and web must share one core" (rationale for D5) | **Delivered** by `src/services/chat_session.py` (400 lines, commit `138deed`) — but via a module that violates the layering rule it was meant to establish |
| Phase 3: "expose a chat API" | **Partly delivered.** `POST /api/v1/planner_chat` exists with `session_id` + in-memory session dict. Missing: `stage`, `hotel_options[]`, `trip_plan`, TTL, registry lock, 404-on-unknown-id |
| Phase 5: "restore a root dependency manifest" | **Done** — commit `bff186c` |
| D7: hotel options as clickable cards | **Superseded in mechanism.** `suggestions_for()` already emits server-declared `{label, value}` chips for the pending hotel list. Cards become a *presentation* of the same contract, not a new one |
| Phase 4: React/Vite app | **Still needed** — confirmed 2026-07-30. `GET /chat` (Jinja) is the interim surface and is retired in Phase 5 |
| D5: full re-layer into `services/` + `agents/` | **Still confirmed** 2026-07-30, despite the sharing goal already being met. Cost rose: `trip_builder_svc.py` grew 1004 → 1741 lines |
| "Four-branch state machine, verified line by line" | **Stale.** `process_chat_turn` now has seven decision points plus two dead ones. See below |
| `/api/v1/ask` regressions | **Unchanged** — all three still reproduce in the working tree |
| "No root dependency manifest" | **Resolved** |
| *(new)* `services/` → `cli/` import inversion | **New finding** |
| *(new)* Dead code in `process_chat_turn` | **New finding** |
| *(new)* Baseline test/lint suite is not green | **New finding** — see "Quality gate" |

## Verified current state

Read from the tree at `3bd9e80` on 2026-07-30. Every row checked directly.

| Fact | Evidence |
|---|---|
| Business logic in a CLI package: `src/cli/trip_builder_svc.py`, **1741** lines (was 1004) | `wc -l src/cli/trip_builder_svc.py` |
| Agent wiring in `src/cli/planner_tools.py`, **573** lines (was 422) | `wc -l src/cli/planner_tools.py` |
| Terminal loop shrank to **91** lines — per-turn logic moved out | `wc -l src/cli/terminal_chat.py` |
| Shared turn logic in `src/services/chat_session.py`, **400** lines | `chat_session.py:235` `process_chat_turn` |
| **`services/` imports `cli/`** — the one-way rule is already violated | `chat_session.py:19` `from src.cli.planner_tools import`, `:28` `from src.cli.trip_builder_svc import` |
| Still **4** agent-visible tools; `generate_full_itinerary` still withheld | `planner_tools.py:568-573` — `[recommend_hotels, select_hotel, modify_trip_plan, finalize_trip_plan]` |
| State is still **two** module-level files under `data/` | `trip_builder_svc.py:55-57` |
| **26** file-I/O call sites on those two files, across **4** files | `grep -rnE "open\(\s*(CURRENT_TRIP_PLAN_FILE\|PENDING_HOTEL_SELECTION_FILE)\|os\.path\.exists\(...\|os\.remove\(..." src/` |
| Web chat API exists: `POST /api/v1/planner_chat` | `routes.py:21-38` |
| Session store is a bare unbounded dict, no lock, no TTL | `routes.py:18` `_CHAT_SESSIONS: dict[str, ChatSession] = {}` |
| Response carries no structure — `{reply, suggestions}` only | `schemas.py` `PlannerChatResponse` |
| Server-declared suggestion chips already exist | `chat_session.py:70` `suggestions_for()` |
| Server-rendered chat page at `GET /chat` (HEAD; **deleted in the working tree**) | `git diff src/main.py`; `src/templates/chat.html` |
| Guided hotel-preference questions | `src/services/guided_question.py` (76 lines), `HotelPreferenceState` |
| LLM-planned trip edits | `src/services/trip_edit_planner.py` (442 lines), `plan_trip_edit` |
| `src/agents/` is **still** untouched template scaffolding | `graph.py` 29 lines, `state.py` 18, `nodes/example_node.py`, `tools/example_tool.py` |
| `src/agents/graph.py:agent` still imported by the live API and served at `POST /api/v1/chat` | `routes.py:3,41-51` |
| Raw exception text leaks: **5** `detail=str(e)`, **8** `f"SYSTEM ERROR: {exc}"` | `routes.py:37,51,115,136,163`; `planner_tools.py:130,242,322,427,480,490,559,562` |
| Hardcoded session id on every persisted itinerary | `trip_builder_svc.py:490` `"session_id": "poc_trip_planner_1"` |
| Root `requirements.txt` restored | commit `bff186c` |
| `docker-compose.yml` `ollama-pull` still pulls **only** `bge-m3` | `docker-compose.yml` |
| `src/api/static/chat.html` untracked, still targets `/ask` | `chat.html:204` |

### Dead code in `process_chat_turn`

Two blocks are unreachable and must be deleted before the state machine is
documented — a contract written from the source as it reads today would describe
branches that never execute:

| Line | Issue |
|---|---|
| `chat_session.py:300` | `if False and session.pending_trip_change is not None:` — the deterministic scope-clarification branch is switched off |
| `chat_session.py:313-321` | `change_intent = None` immediately before `if is_saved_plan_edit and change_intent is not None:` — statically unreachable |

`session.pending_trip_change` and `_scope_question` are only reachable from these
blocks. Deleting them removes `parse_day_scope` and `_saved_duration_days` usage too;
confirm before deleting rather than assuming.

### `/api/v1/ask` is still broken

Re-verified 2026-07-30 against `src/services/supabase_search.py`. All three
regressions from the 2026-07-29 draft reproduce unchanged:

| # | Regression | Evidence |
|---|---|---|
| 1 | `search_attractions` has no `filters=` kwarg; `routes.py:97` passes one | `supabase_search.py:173-180` |
| 2 | `extract_search_filters` has no `search_type="auto"` branch — `"auto"` falls to the attraction prompt, which never returns `search_type`, so `/ask` routes every query to hotels | `supabase_search.py:35-37` |
| 3 | `_get_destination_id_by_name` uses `ilike %name%`; "Ho Chi Minh" does not match "Hồ Chí Minh" | `supabase_search.py:85-92` |

`/ask` exists only in the working tree (`+58` lines in `routes.py`). Per D6 it is
removed, not repaired.

## Decisions

D1-D4 accepted 2026-07-29 16:37; D5-D7 16:58; D8-D11 on the 2026-07-30 state.

| # | Decision | Consequence |
|---|---|---|
| D1 | **Per-session in-memory state**, keyed by `session_id` | No migration; state lost on restart — accepted for PoC. Covers both global files |
| D2 | Configurable LLM, default Ollama | Already implemented upstream — nothing to build |
| D3 | **Single POST + progress spinner**, no SSE | Simplest client; must mitigate long-request timeouts |
| D4 | **Separate React/Vite app** in `frontend/` | **Reconfirmed 2026-07-30** with `GET /chat` already shipping. Single chat column, not the 3-panel comp |
| D5 | **Proper layering: `services/` + `agents/` + `cli/`** | **Reconfirmed 2026-07-30.** Now also fixes the `services/` → `cli/` inversion. Cost rose with the file growth; this is the plan's highest-risk phase |
| D6 | **Revert `routes.py`/`main.py` to HEAD; drop `/ask` and the static search page** | Reverting also **restores** `GET /chat`, which the working tree deleted. That is intended — see D9 |
| D7 | **Hotel options as clickable cards** | Presentation of the existing `suggestions[]` chip contract, extended with a structured `hotel_options[]` for rendering. Clicking sends the ordinal as the next message |
| D8 | **`GET /chat` stays alive until React ships, then is retired** | Avoids a window with no working UI. Phase 5 removes the route, `src/templates/`, and the Jinja2 dependency |
| D9 | **`chat_session.py` moves to `src/agents/session.py`** | It orchestrates the agent and imports tools; it is not a service. Resolves the import inversion by moving the file, not by adding indirection |
| D10 | **Extend `PlannerChatResponse`; do not introduce a parallel `ChatResponse`** | `reply` and `suggestions` stay and keep their meaning; `stage`, `hotel_options`, `trip_plan`, `intake` are added. `GET /chat` keeps working unmodified through Phase 4 |
| D11 | **Quality gate is "no new failures", not "all green"** | Baseline is 5 failing tests, 2 collection errors, 937 ruff errors in `src/`. Fixing that is real work unrelated to this feature — see "Quality gate" |

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Two browser sessions plan independently — no shared global files | P1 |
| 2 | Backend layered so the boundary is obvious: logic / agent / CLI / HTTP, one-way imports | P1 |
| 3 | Chat API returns structured itinerary **and** hotel options, not only text | P1 |
| 4 | React chat UI completes intake → hotel pick → plan → modify → finalize | P1 |
| 5 | CLI keeps working throughout, off the same core | P1 |
| 6 | No broken endpoints, no dead branches, no raw exception text left in the tree | P2 |

## Non-goals

- Bilingual VI/EN copy (BR-10). Strings stay Vietnamese, centralized for retrofit.
- The three-panel design comp, hotel image carousel, rich-media modal.
- Streaming, job queues, auth, rate limiting, Supabase-persisted sessions.
- Repairing `/ask` (D6 deletes it) or changing `supabase_search` RPC contracts.
- Restoring the diacritic-folding search fix. Real, still in `stash@{0}`, belongs to
  the search path this plan removes. **Flagged for a separate ticket** — if
  `/search_hotels` is ever user-facing, that bug returns.
- Clearing the pre-existing test and lint debt (D11).

## Target architecture

```
src/services/                  # business logic — no agent, no I/O framework
├── trip_planner.py            # ← src/cli/trip_builder_svc.py (1741 lines)
├── trip_formatter.py          # format_trip_response_from_json, format_hotel_options,
│                              #   parse_duration_to_days, + new to_trip_plan_payload
├── hotel_selection.py         # unchanged (upstream)
└── (trip_intake, trip_edit_planner, trip_scheduler, guided_question, suggestions,
     itinerary_store, itinerary_reuse, supabase_search, routing, vector_store, llm)

src/agents/                    # agent wiring and conversation orchestration
├── prompts.py                 # ← SUPERVISOR_PROMPT
├── session.py                 # ← src/services/chat_session.py, + TripSession/SessionRegistry
├── graph.py                   # build_trip_agent(session)  [replaces the stub]
├── state.py                   # TripAgentState             [replaces the stub]
├── nodes/intake.py            # deterministic intake gate
└── tools/                     # ← planner_tools.py — the 4 tools the agent may call
    ├── recommend_hotels.py
    ├── select_hotel.py
    ├── modify_itinerary.py
    └── finalize_itinerary.py
    # NOT a tool: generate_full_itinerary. It is @tool-decorated but never passed
    # to create_react_agent (planner_tools.py:568-573), and SUPERVISOR_PROMPT
    # forbids the LLM from calling it. Itinerary generation is reachable ONLY via
    # select_hotel, which is what enforces the hotel-pick gate. It moves to
    # services/trip_planner.py as a plain function.

src/cli/                       # terminal I/O only
└── terminal_chat.py           # loop, printing, logging

src/api/                       # HTTP
frontend/                      # Vite + React (JS), single chat column
```

**Layering rule:** `services/` never imports from `agents/`, `cli/` or `api/`.
`agents/` imports `services/`. `cli/` and `api/` import `agents/`. One direction only.
This is violated today at `chat_session.py:19,28`; D9 fixes it by moving the file.

**Why `chat_session.py` is an agent, not a service.** It imports five `@tool`
objects and `create_planner_agent`, holds the compiled agent on `ChatSession.agent`,
and drives `agent.stream()`. Leaving it under `services/` forces either a permanent
rule exception or an inversion-of-control layer that buys nothing at this size.

**Why tools are per-session closures.** `create_react_agent` tools take no session
argument, and the current tools reach for module-level file constants. Each
`TripSession` builds its own tool closures and compiled agent; the registry's TTL
eviction bounds them. Fallback if memory becomes an issue: one shared agent with
`RunnableConfig` injection.

**Why HTTP handlers are sync (`def`).** Supabase, Ollama embeddings and `ChatOllama`
all block. An `async def` handler would stall the event loop for a 30-60s plan
build. `def` puts it on Starlette's threadpool; a per-session `threading.Lock`
serializes same-session turns. `planner_chat` is already correctly a `def`
(`routes.py:22`) with the reason recorded in its docstring — preserve that.

**Two locks, not one.** Because `def` handlers run on real OS threads, the
`SessionRegistry` dict is itself shared mutable state and needs its own lock —
a per-session lock cannot protect the lookup that *produces* the session. Without
it, two concurrent requests for the same id can each construct a distinct
`TripSession` with a distinct lock, and the loser's work is silently discarded.
`_CHAT_SESSIONS` (`routes.py:18`) has this bug today. Eviction must also never
remove a session whose lock is currently held.

## Frozen API contract

Written to `docs/chat_api_contract.md` in Phase 1; Phases 3 and 4 build against it
independently.

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `POST` | `/api/v1/chat/session` | — | `{session_id, created_at}` |
| `POST` | `/api/v1/planner_chat` | `{message, session_id}` | `PlannerChatResponse` |
| `GET` | `/api/v1/chat/{session_id}/plan` | — | `{trip_plan}` or 404 |
| `DELETE` | `/api/v1/chat/{session_id}` | — | `204` |

Per D10 the existing `POST /api/v1/planner_chat` path and its `PlannerChatResponse`
model are **extended in place**, not replaced. `reply` and `suggestions` keep their
current meaning so `GET /chat` continues to work unchanged until Phase 5 retires it.

`PlannerChatResponse` after this plan:

```json
{
  "session_id": "uuid",
  "reply": "text reply, already formatted",
  "suggestions": [ { "label": "1. Muong Thanh", "value": "1" } ],
  "stage": "intake | hotel_options | planned | modified | finalized | error",
  "hotel_options": [
    { "index": 1, "id": "uuid", "name": "...", "star_rating": 4,
      "description": "...", "matched_rooms": ["..."] }
  ],
  "trip_plan": { "...null until a hotel is picked..." },
  "intake": { "destination": "...", "duration": "...", "people": "...", "missing": ["people"] }
}
```

`trip_plan`:

```json
{
  "status": "Draft",
  "destination": "Nha Trang", "duration_days": 3, "number_of_adults": 2,
  "hotel": { "id": "...", "name": "...", "star_rating": 4, "description": "...",
             "matched_rooms": ["..."], "coordinates": "..." },
  "days": [ { "day_number": 1, "theme": "...",
              "items": [ { "order_index": 1, "start_time": "08:00", "end_time": "09:30",
                           "activity": "...", "kind": "breakfast",
                           "reference_type": "Attraction", "reference_id": "uuid" } ] } ],
  "adjustments": ["..."]
}
```

`hotel_options` is populated only when `stage="hotel_options"`; the client sends the
chosen `index` back as the next `message`, matching what `select_hotel` already
parses and what `suggestions_for()` already emits as `value`.

Backwards compatibility: `message` stays required with `min_length=1` and `session_id`
stays required on `planner_chat`, so `tests/test_api/test_routes.py` passes unchanged.

## Conversation state machine

`process_chat_turn` (`chat_session.py:235`) is the single source of truth for both
transports. It has **seven live decision points** plus two dead blocks. The order is
load-bearing — reordering is a regression:

```
1. pending hotel selection exists     -> select_hotel(message)                    :241
   1a. resolved                        -> return; initial_plan_complete = True     :246
   1b. unresolved but still an attempt -> return the retry prompt, keep the list   :253
   1c. unresolved, not an attempt      -> DROP the list, fall through              :262
2. saved plan + finalization phrase   -> finalize_trip_plan()                     :264
3. saved plan, not planning_new_trip  -> new-trip detection / unsupported-city     :270-276
4. is_saved_plan_edit                 -> plan_trip_edit -> clarify | apply         :279-298
   (dead) :300  `if False and ...`     -> deterministic scope clarification
   (dead) :313-321 change_intent=None  -> deterministic modification
5. not initial_plan_complete
   and not is_saved_plan_edit          -> intake gate: question                    :323-330
6.   intake just completed             -> first hotel-preference question          :336
7.   hotel prefs incomplete            -> next preference question                 :338-343
     both complete                     -> recommend_hotels(verified_arguments)     :350
8. unconditional fallthrough          -> ReAct agent, 2 attempts                   :354-400
```

Branch 5 is the guard that stops the LLM inventing a destination or duration. It ends
at `recommend_hotels`, **not** at itinerary generation.

Branch 1c is new since July and is a real behavioural rule: with a list pending,
every later message used to be read as a choice, trapping the user. Any re-derivation
of this machine that drops 1c reintroduces that bug.

**`stage` is derived, not routed.** `chat_session.py:354` is a single unconditional
`agent.stream()` call — the shared core makes no distinction between an "edit" turn
and any other agent turn, so the API cannot mirror one. **Derive `stage` after the
fact from which tool actually ran**, and treat that derivation as new logic requiring
its own tests.

**Four of the five tool invocations bypass the agent entirely** (RT-1):
`select_hotel` `:242`, `finalize_trip_plan` `:265`, `execute_trip_edit_request` `:296`,
`recommend_hotels` `:350`. Only `:362` is the agent stream. Instrumenting the stream
alone therefore never produces `hotel_options` or `finalized` — the hotel-card turn and
the finalize turn, i.e. the two the UI most depends on. Phase 3 carries the full table.

## Quality gate

Measured on `3bd9e80`, 2026-07-30. Per D11, phases assert *no regression against this
baseline*, not a clean suite:

| Check | Baseline | Gate for this plan |
|---|---|---|
| `pytest tests` collection | 2 errors: `tests/test_qdrant_schema.py` (imports missing `src.services.qdrant_schema`), `src/airflow/tests/test_hotel_pipeline.py` | No new collection errors |
| `pytest tests --ignore=tests/test_qdrant_schema.py` | 5 failed, 193 passed | 5 known failures may persist; **0 new failures**, and every new test green |
| `pytest tests/test_api --collect-only` | collects | Must keep collecting at **every** commit — `conftest.py:7` imports `src.main` at module scope (RT-4) |
| Source-text assertion tests | 4 functions read `src/cli/*.py` from hardcoded paths | Phase 2 deletes those files; the tests are converted, not repointed (RT-2) |
| Known failures | `test_itinerary_store.py::test_persistence_migration_uses_builtin_uuid_generation`, `test_routing.py::test_get_route_info_success`, `test_trip_intake.py::test_destination_alias_schema_and_terminal_loader_contract`, `test_trip_reuse_flow.py::test_reuse_migration_contains_atomic_bundle_and_finalization_contracts`, `test_trip_reuse_flow.py::test_finalization_credits_every_upstream_ancestor_once` | Record the list before starting; re-check after |
| `ruff check src` | 937 errors (`src/cli` 122, `src/services` 85, `src/api` 6, `src/agents` 0) | `ruff check` clean **on files this plan creates or edits**, not repo-wide |

Two of the known failures are migration/contract assertions on Supabase SQL, and one
is a routing distance assertion — none touch the chat path. If any of them starts
passing or failing differently after a phase, that is a signal, not noise.

## Phases

| # | Phase | Status | Depends on |
|---|-------|--------|------------|
| 1 | [Phase 1: Freeze the contract, clean the tree](./phase-01-start.md) | Pending | — |
| 2 | [Phase 2: Re-layer into services / agents / cli](./phase-02-agents-backend-port.md) | Pending | 1 |
| 3 | [Phase 3: Per-session state and structured chat API](./phase-03-chat-session-api.md) | Pending | 2 |
| 4 | [Phase 4: React chat frontend](./phase-04-react-chat-frontend.md) | Pending | 1 (contract only) |
| 5 | [Phase 5: Wire up, verify, retire the Jinja page](./phase-05-wire-up-and-verify.md) | Pending | 3, 4 |

Phases 3 and 4 run in parallel once Phase 1 freezes the contract.

## Success criteria

- [ ] `grep -rnE "^\s*(from|import)\s+src\.(agents|cli|api)" src/services/` returns
      nothing — the narrower `from src.agents` form misses `import src.agents.session`
- [ ] `src/agents/` contains no Supabase call, no `open()`, no HTTP
- [ ] `generate_full_itinerary` is **not** in `build_trip_agent`'s tool list
- [ ] No `open(` or `os.path.exists(` on the two plan files outside the persist hook
- [ ] No endpoint returns raw exception text; 5xx bodies are generic
- [ ] Both dead blocks removed from the turn logic; no `if False` remains
- [ ] `python scripts/poc_trip_planner.py` still completes the full flow after re-layering
- [ ] Two browser sessions plan two destinations concurrently, neither overwriting the other
- [ ] `POST /api/v1/planner_chat` returns `hotel_options` then `trip_plan` at the right stages
- [ ] `stage` is observed at all five tool-invocation sites, not only the agent stream —
      one test per direct-call site (RT-1)
- [ ] `grep -rn 'src" / "cli"' tests/` returns nothing; the source-text assertion tests
      are converted to behavioural checks (RT-2)
- [ ] `suggestions[]` keeps working — `GET /chat` is unmodified through Phase 4
- [ ] React UI completes intake → hotel card click → plan → modify → finalize
- [ ] No endpoint in the tree raises `TypeError` on a normal request
- [ ] Persisted itineraries carry the real session id, not `poc_trip_planner_1`
- [ ] Quality gate per D11: no new test failures, no new collection errors, `ruff` clean
      on touched files

## Relationship to existing plans

- `plans/260723-1015-v-ota-poc-master-roadmap/` — delivers the first concrete slice of
  its Phases 3, 5 and 7, deliberately narrower (one column, Vietnamese, no streaming).
  Its phase-05 remains the target for the full 3-panel bilingual UI. No blocking
  relationship; the roadmap is program-level.
- `plans/260729-0959-vector-search-supabase-vs-qdrant/` — independent. This plan
  changes no `supabase_search` signature. Note it will find `/ask` gone (D6) and the
  diacritic-folding fix absent. Also note `tests/test_qdrant_schema.py` imports a
  module that does not exist — that belongs to this plan, not ours (D11).

> The 2026-07-29 draft cited `plans/260730-1215-llm-based-intake-and-intent-classification/`
> as a compatibility concern. **No such plan directory exists.** The LLM-based intake
> work landed directly as commits `0cca298` and `3bd9e80`; `TripIntakeState` already
> uses `_llm_extract_intake_facts` with `_match_known_destination` as the deterministic
> grounding step, so the branch-5 guard holds as described. Reference removed.

## Red Team Review

### Session — 2026-07-29
**Reviewers:** Security Adversary (Fact Checker), Failure Mode Analyst (Flow Tracer),
Assumption Destroyer (Scope Auditor). Full verification tier, 5 phases.
**Findings:** 13 after dedup (13 accepted, 0 rejected).
**Severity breakdown:** 5 Critical, 3 High, 5 Medium.

| # | Finding | Severity | Status on 2026-07-30 |
|---|---------|----------|---|
| 1 | Routing branch count fabricated; `stage` must be derived from tool observation | Critical | Re-applied — the machine is now 7 branches + 2 dead |
| 2 | "No logic changes / pure relocation" contradicts de-globalizing | Critical | Still applies; call-site count rose 11 → 26 |
| 3 | `SessionRegistry` needs its own lock; sync `def` handlers mean real threads | Critical | **Now observable in shipped code** — `routes.py:18` |
| 4 | TTL eviction can evict a session mid-request | Critical | Still applies; no TTL exists yet |
| 5 | Baseline-transcript regression check is unsound — `temperature=0.3`, no seed | Critical | Still applies (`planner_tools.py:565`) |
| 6 | `generate_full_itinerary` is not an agent tool; wiring it in bypasses the gate | High | Re-verified at `planner_tools.py:568-573` |
| 7 | Raw exception text reaches clients | High | **Worse** — 5 `detail=str(e)` + 8 `SYSTEM ERROR: {exc}` |
| 8 | `session_id` accepted unvalidated and auto-created | High | **Now observable** — `routes.py:29-32` auto-creates any id |
| 9 | "46-line shim" wrong | Medium | Obsolete — the shim is no longer discussed |
| 10 | Finalized itineraries stamped `poc_trip_planner_1` | Medium | Re-verified at `trip_builder_svc.py:490` |
| 11 | `DEBUG_TRIP_PLAN_FILE=1` would reinstate the global files | Medium | Still applies |
| 12 | `services/` import-boundary grep misses `import src.agents` | Medium | Broadened to include `src.api` |
| 13 | Phase 4 VI-string grep misses quotes/templates/JSX text | Medium | Still applies |

### Re-verification — 2026-07-30
The "Verified current state" table was rebuilt from scratch against `3bd9e80` rather
than amended. Every row carries a file:line or command. Findings 3, 7 and 8 moved from
*predicted* to *present in shipped code*, which raises their priority. Findings 9 is
retired as obsolete. Three new findings were added to the state table: the
`services/` → `cli/` import inversion, the two dead blocks, and the non-green baseline.

### Session — 2026-07-31
**Lenses:** Security Adversary (Fact Checker), Failure Mode Analyst (Flow Tracer),
Assumption Destroyer (Scope Auditor). Full verification tier, 5 phases. Run inline
rather than via subagents at the user's direction; every finding carries file:line
evidence gathered against the working tree.
**Findings:** 8 (8 accepted, 0 rejected).
**Severity breakdown:** 2 Critical, 2 High, 4 Medium.

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| RT-1 | Phase 3 said two branches call tools directly; there are **four**. `recommend_hotels` `:350` and `finalize_trip_plan` `:265` bypass the agent, so `hotel_options` and `finalized` would never be derived | Critical | Accept | plan.md, Phase 3 |
| RT-2 | Four test functions read `src/cli/*.py` **source text** from hardcoded paths and assert on exact code strings; Phase 2 deletes those files → `FileNotFoundError`. One assertion is invalidated by design and needs converting, not repointing | Critical | Accept | plan.md, Phase 2 |
| RT-3 | Phase 2's I/O call-site table understated `chat_session.py` as 6; it is 7 (`:84,105,241,246,264,270,281`). Total 26 was correct | High | Accept | Phase 2 |
| RT-4 | `tests/conftest.py:7` imports `src.main` at module scope, so a broken intermediate commit errors the whole API suite at *collection* and can take the regression harness with it | High | Accept | plan.md, Phase 2 |
| RT-5 | `DEBUG_TRIP_PLAN_FILE` hook interpolates client-supplied `session_id` into a filesystem path; validation was only specified in Phase 3, one phase later, and the CLI reaches the hook with a non-UUID id | Medium | Accept | Phase 2 |
| RT-6 | Phase 3 deferred "is `chat.html`'s session_id a UUID?" to implementation. It is — `crypto.randomUUID()` at `chat.html:200,349`. Settled in the plan | Medium | Accept | Phase 3 |
| RT-7 | `ENABLE_ITINERARY_REUSE` read gate cited as `trip_builder_svc.py:58`; that is the definition, the gate is `:251` | Medium | Accept | Phase 3 |
| RT-8 | `MemorySaver()` is per-agent (`planner_tools.py:567`), so eviction silently discards full conversation history and the 200 cap is sized against the compiled graph rather than accumulated messages | Medium | Accept | Phase 2 |

**Claims that held up under re-verification:** the seven-branch state machine and every
line citation in it; `detail=str(e)` × 5; `f"SYSTEM ERROR: {exc}"` × 8; service-role key
via `SUPABASE_SERVICE_KEY` (`trip_builder_svc.py:107`); the two `services/` → `cli/`
import violations (`chat_session.py:19,28`); 26 total I/O call sites; the D11 baseline
counts.

Both Critical findings were defects in phases written during the 2026-07-30 rewrite,
and both would have produced a plan that reads as complete while shipping a UI with no
hotel cards (RT-1) or a test suite failing in a way the D11 gate forbids (RT-2).

### Whole-Plan Consistency Sweep — 2026-07-31
- Files reread: `plan.md`, `phase-01-start.md`, `phase-02-agents-backend-port.md`,
  `phase-03-chat-session-api.md`, `phase-04-react-chat-frontend.md`,
  `phase-05-wire-up-and-verify.md`
- Decision deltas checked: 8 (RT-1 … RT-8)
- Reconciled stale references: 6 — "two branches call tools directly" → four, in
  `plan.md` and Phase 3 (statement, steps, tests, risk row); `chat_session.py | 6` → 7
  in Phase 2; the UUID investigation step and its risk row replaced with the settled
  answer in Phase 3; the three source-text test modules moved out of the
  "(import paths)" list into their own entry in Phase 2; `trip_builder_svc.py:58`
  qualified as definition-vs-gate in Phase 3; the "has not been re-red-teamed" note in
  `plan.md` replaced by this session
- Cross-phase checks: Phase 4 depends on `stage="hotel_options"` in 6 places
  (`:36,87,144,157,159`) — all remain correct and are now actually reachable given the
  RT-1 fix in Phase 3. Phase 1's dead-code deletion still precedes Phase 2's call-site
  re-count, which the RT-3 note makes explicit
- Unresolved contradictions: 0

### Whole-Plan Consistency Sweep — 2026-07-30
- Files reread: `plan.md`, `phase-01-start.md`, `phase-02-agents-backend-port.md`,
  `phase-03-chat-session-api.md`, `phase-04-react-chat-frontend.md`,
  `phase-05-wire-up-and-verify.md`
- Decision deltas applied: 11 (D4, D5, D6 reconfirmed/extended; D8-D11 new)
- Reconciled stale references: 8 — four-branch → seven-branch in 3 files; 1004 → 1741
  and 422 → 573 lines in 2 files; 11 → 26 I/O call sites in 2 files; new
  `ChatResponse` → extended `PlannerChatResponse` in 3 files; `requirements.txt`
  missing → restored in 2 files; nonexistent LLM-intake plan reference removed from 1
  file; "pytest green / ruff clean" → D11 gate in 5 files; `/chat` deletion →
  restore-then-retire in 3 files
- Unresolved contradictions: 0

## Open questions

- Who owns re-applying the diacritic-folding search fix from `stash@{0}`? Out of scope
  here, but it is a live bug in `/search_hotels`.
- Should the 5 known test failures and 2 collection errors get their own cleanup
  ticket? D11 excludes them from this plan but does not assign them.
- Production serving of the built React app is deferred to whoever owns deployment.
- Does anything outside the repo consume `GET /chat`? D8 retires it in Phase 5;
  confirm with the team before removing the route.

<!-- slug: trip-planner-chat-ui-and-agents-backend -->
