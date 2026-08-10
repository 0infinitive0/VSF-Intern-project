---
phase: 2
title: "Re-layer into services / agents / cli"
status: pending
priority: P1
effort: "1.5d"
dependencies: [1]
---

# Phase 2: Re-layer into services / agents / cli

## Overview

Business logic (1741 lines) and agent wiring (573 lines) sit in a package named `cli`,
and the shared turn logic under `services/` imports *upward* from `src.cli`. Split
along real boundaries (D5), move `chat_session.py` to where it belongs (D9), and
replace the two module-level JSON files with per-session state (D1).

> Supersedes the 2026-07-29 version. Its premise — "move the logic so CLI and web can
> share one core" — was overtaken: `chat_session.py` already achieves the sharing.
> What remains is the layering hygiene and, far more importantly, the de-globalization
> that the sharing work skipped. The file grew 74% in the meantime, so the relocation
> cost is higher and the merge-conflict risk is the top risk in this plan.

## Requirements

- Functional: `services/` holds business logic and imports nothing from `agents/`,
  `cli/` or `api/`.
- Functional: `agents/` holds agent wiring and conversation orchestration only — no
  Supabase call, no `open()`, no HTTP.
- Functional: `cli/` holds terminal I/O only.
- Functional: `TripSession` isolates trip data, pending hotel selection, intake state,
  hotel-preference state and conversation memory per `session_id`.
- Functional: the CLI and `GET /chat` behave identically before and after — same
  prompts, same observable tool sequence, same `suggestions[]`.
- Non-functional: **the file moves are pure relocations; the state-access rewrite is
  not.** Separate steps, separate diffs. See "Two kinds of change".
- Non-functional: quality gate per D11.

## Architecture

### Two kinds of change

An earlier draft required "no logic changes; the diff must read as a relocation" while
*also* requiring the two global JSON files to become session fields. Those are
incompatible. The file I/O is not centralized in the load/save/clear helpers — it is
inlined across **26 call sites in four files**, up from 11 in three when this was first
written:

| File | Call sites | Notable |
|---|---|---|
| `src/cli/planner_tools.py` | 10 | `:297,301` `select_hotel`; `:353,357` `_legacy_modify_trip_plan`; `:434,437` `execute_trip_edit_request`; `:496,499` `modify_trip_plan`; `:520,523` `finalize_trip_plan` |
| `src/services/chat_session.py` | 7 | `:84` chip generation; `:105` `_saved_duration_days`; `:241,246` branch 1; `:264,270,281` branches 2-4 |
| `src/cli/trip_builder_svc.py` | 6 | `:83,88,91,99,100` pending-selection helpers; `:520` `_save_trip_data` |
| `src/cli/terminal_chat.py` | 3 | `:35,39,73` suggestion-action detection |

Counts re-verified 2026-07-31 (RT-3): 3 + 6 + 10 + 7 = **26**. If Phase 1 removed
`_saved_duration_days` as orphaned, `chat_session.py` drops to 6 and the total to 25.
Re-run the grep after Phase 1 lands rather than trusting this table:

```
grep -rnE "open\(\s*(CURRENT_TRIP_PLAN_FILE|PENDING_HOTEL_SELECTION_FILE)|os\.path\.exists\(\s*(CURRENT_TRIP_PLAN_FILE|PENDING_HOTEL_SELECTION_FILE)|os\.remove\(\s*(CURRENT_TRIP_PLAN_FILE|PENDING_HOTEL_SELECTION_FILE)" src/
```

Converting these to `session.trip_data` / `session.pending_hotel_selection` is a
**rewrite of the state-access layer**, not a move. Split the work:

- **Steps 4-5 and 8-11 are relocations** — review them as rename-only diffs.
- **Step 7 is a rewrite** — all 26 call sites, reviewed on its own merits, with a
  structural regression check after each file.

An engineer who follows "pure relocation" literally will leave the `open()` calls
inside `services/trip_planner.py` and silently defeat per-session isolation.

### The persistence adapter — one interception point

The CLI must keep writing both JSON files; the server must not. Do **not** thread a
`DEBUG_TRIP_PLAN_FILE` check through 26 call sites. Instead give the session a single
optional hook, invoked from the two save helpers only:

```python
@dataclass
class TripSession:
    ...
    persist_hook: Callable[[TripSession], None] | None = None   # CLI sets it; server leaves None
```

`_save_trip_data` / `_save_pending_hotel_selection` become pure in-memory mutations
that call `session.persist_hook(session)` if set. The CLI installs a hook that writes
both files; the server installs one only under `DEBUG_TRIP_PLAN_FILE=1`, and that hook
must write to `debug/{session_id}/` — the bare filenames are global and would re-create
the very bug this phase removes.

**`session_id` is a path component, so validate it here, not in Phase 3** (RT-5).
`session_id` is client-supplied and the debug hook interpolates it into a filesystem
path; `../../etc/x` escapes the debug directory. Phase 3 types the field as `UUID` at
the HTTP boundary, but this hook is created in *this* phase and is reachable from the
CLI too, whose id is the non-UUID literal `poc_trip_planner_1`
(`terminal_chat.py:57,69`). Make the hook itself reject any id that is not
`[A-Za-z0-9_-]+`, and build the path with `pathlib` rather than string concatenation.
Defence at the write site, not only at the boundary.

`src/main.py`'s lifespan currently calls `_clear_pending_hotel_selection()` at startup
to stop a stale file poisoning the first message of a new session. Once state is
per-session that call is meaningless; remove it as part of step 7 rather than leaving a
no-op that implies the global file still matters.

### Move map

| From | To |
|---|---|
| `src/cli/trip_builder_svc.py` (1741 lines) | `src/services/trip_planner.py` |
| ↳ `format_trip_response_from_json`, `format_hotel_options`, `parse_duration_to_days` | `src/services/trip_formatter.py` |
| ↳ *(new)* `to_trip_plan_payload`, `to_hotel_options_payload` | `src/services/trip_formatter.py` |
| ↳ `CURRENT_TRIP_PLAN_FILE`, `PENDING_HOTEL_SELECTION_FILE` + their load/save/clear helpers | `src/agents/session.py` (become session fields) |
| **`src/services/chat_session.py` (400 lines)** | **`src/agents/session.py`** — D9. It imports 7 tool symbols and drives `agent.stream()`; it is agent orchestration, not a service |
| ↳ `suggestions_for` | stays with it — chip generation reads session state directly |
| `src/cli/planner_tools.py` → `SUPERVISOR_PROMPT` | `src/agents/prompts.py` |
| ↳ the **4 agent-visible** `@tool`s — `recommend_hotels`, `select_hotel`, `modify_trip_plan`, `finalize_trip_plan` | `src/agents/tools/<one file each>.py` |
| ↳ `generate_full_itinerary`, `_generate_and_save_itinerary`, `_legacy_modify_trip_plan` | `src/services/trip_planner.py` as **plain functions**, not `@tool`, not registered with `create_react_agent` |
| ↳ `execute_trip_edit_request` | `src/agents/session.py` — it is called directly from the turn logic, not by the LLM |
| ↳ `create_planner_agent()` | `src/agents/graph.py` as `build_trip_agent(session)` |
| ↳ `_is_finalization_request`, `_validate_trip_basics` | `src/agents/nodes/intake.py` |
| `src/cli/terminal_chat.py` | stays — but reads state from a `TripSession` |
| `src/agents/nodes/example_node.py`, `src/agents/tools/example_tool.py` | **delete** (template scaffolding) |
| `src/agents/graph.py`, `src/agents/state.py` (stubs) | replaced |

Already correctly placed — **leave alone**: `hotel_selection.py`, `guided_question.py`,
`suggestions.py`, `trip_edit_planner.py`, `trip_intake.py`, `trip_scheduler.py`,
`itinerary_store.py`, `itinerary_reuse.py`, `supabase_search.py`, `routing.py`,
`vector_store.py`, `llm.py`.

### Session model (decision D1)

The two global files become two session fields. This is the whole point of the phase:
`chat_session.py:241` routes on `os.path.exists(PENDING_HOTEL_SELECTION_FILE)`, which
is process-global and cannot support two users — yet a multi-session HTTP endpoint
already ships on top of it.

`TripSession` **absorbs the existing `ChatSession` dataclass** (`chat_session.py:47-60`)
rather than sitting beside it. Its current fields — `agent`, `config`, `intake_state`,
`hotel_pref_state`, `initial_plan_complete`, `planning_new_trip`,
`pending_trip_edit_request` — are already correct per-session state; they were simply
never joined by the two that stayed global.

```python
# src/agents/session.py
@dataclass
class TripSession:
    session_id: str
    agent: CompiledGraph
    config: dict
    intake_state: TripIntakeState = field(default_factory=TripIntakeState)
    hotel_pref_state: HotelPreferenceState = field(default_factory=HotelPreferenceState)
    initial_plan_complete: bool = False
    planning_new_trip: bool = False
    pending_trip_edit_request: str | None = None
    trip_data: dict | None = None                 # was current_trip_plan.json
    pending_hotel_selection: dict | None = None   # was pending_hotel_selection.json
    persist_hook: Callable[[TripSession], None] | None = None
    created_at: datetime
    last_seen_at: datetime
    lock: threading.Lock

class SessionRegistry:
    """In-memory, TTL-evicted. Process-local — run one uvicorn worker.

    Handlers are sync `def`, so these run on real OS threads: every mutation of
    the internal dict must hold `_registry_lock`. A per-session lock cannot
    protect the lookup that produces the session.
    """
    _registry_lock: threading.Lock           # guards the dict itself

    def create(self) -> TripSession: ...     # the only way a session comes into being
    def resolve(self, session_id: str) -> TripSession | None: ...
    def drop(self, session_id: str) -> None: ...
    def evict_expired(self) -> int: ...      # TTL 2h, cap 200, LRU beyond
        # MUST skip any session whose lock is held (non-blocking lock.locked()),
        # otherwise a session inside a 60s tool call is evicted mid-request and
        # the next request builds a fresh one that runs concurrently with it.
```

**Why the registry needs its own lock.** Two requests carrying the same
not-yet-registered `session_id` — a client retry, a double submit, or the eviction race
above — can both pass a naive check-then-create, each build a distinct `TripSession`
with a distinct `threading.Lock`, and clobber each other in the dict. The two requests
then never contend on the same lock, so Phase 3's "same-session turns serialize"
guarantee silently does not hold, and the loser's completed work is discarded.
`routes.py:18-32` has exactly this shape today.

**Eviction is also a liveness concern.** Session creation is unauthenticated and
unthrottled; a caller looping `POST /chat/session` past the 200-session cap evicts
*other* users' in-progress sessions. Skipping locked sessions bounds the damage; add a
coarse per-IP limit if the demo is ever exposed beyond localhost.

**What eviction actually discards** (RT-8). `create_planner_agent` constructs a fresh
`MemorySaver()` per call (`planner_tools.py:567`) and `ChatSession.config` pins a
`thread_id` (`chat_session.py:66`), so full LangGraph message history already lives
inside each session object — it is not a process-wide store. Two consequences the
cap must be sized against:

- Evicting a session silently drops its entire conversation history, not just a cache.
  A user idle past the TTL resumes with an agent that has never met them, while
  `trip_data` may still be on their screen. Decide deliberately whether the client
  surfaces this (Phase 4 already treats a 404 as "start over"); do not let it be a
  surprise.
- The memory driver is accumulated message history × 200, not the compiled graph.
  Measure one finished session's footprint before trusting the cap.

The CLI keeps writing both JSON files — genuinely useful for a terminal tool. It gets
one long-lived `TripSession` whose `persist_hook` writes both files. The server leaves
the hook unset.

### Tools become session-bound factories

Today each `@tool` reaches for module-level file constants. After the move:

```python
def build_select_hotel_tool(session: TripSession) -> BaseTool:
    @tool
    def select_hotel(selection: str) -> str:
        """..."""            # docstring is the LLM-visible contract — copy verbatim
        pending = session.pending_hotel_selection
        ...
```

Preserve every tool docstring exactly. `SUPERVISOR_PROMPT` references tool names and
their sequencing rules; a reworded docstring changes model behaviour.

Preserve the `SYSTEM ERROR:` prefix convention — the CLI, `suggestions_for`, and
Phase 3's API all branch on it (`chat_session.py:248,267`; `terminal_chat.py:78`). The
current bodies interpolate raw exceptions at **8** sites (`planner_tools.py:130,242,322,
427,480,490,559,562`); Phase 3 sanitizes before returning them over HTTP, so keep the
prefix but do not add new raw-exception interpolation here.

Also stamp the real session id where the code hardcodes one: `trip_builder_svc.py:490`
writes `"session_id": "poc_trip_planner_1"` into every persisted itinerary, so finalized
rows from every user are indistinguishable in Supabase. Pass `session.session_id`
through instead. Note `trip_builder_svc.py:318-324` already upserts into a `sessions`
table from that same value — check the FK before changing what is written.

### Regression checking without a text diff

`create_planner_agent(temperature=0.3)` (`planner_tools.py:565`) samples
non-deterministically and nothing sets a seed, so a captured-transcript text diff is
either permanently red from harmless wording drift — training reviewers to wave diffs
through — or it hides a real regression as "LLM noise".

Assert on **structure**, not prose. After each scripted turn, capture and compare:

1. which tool was invoked, and with what arguments;
2. the order of tool invocations across the session;
3. the shape of `session.trip_data` — day count, items per day, hotel id, `status` —
   and of `session.pending_hotel_selection`;
4. whether the response starts with `SYSTEM ERROR:`;
5. the `suggestions_for(session)` output — this is a shipped contract `GET /chat` reads.

Write this as a pytest harness driving the session directly with a stubbed LLM whose
tool choices are scripted, so the check is deterministic and runs in CI. The existing
`tests/test_chat_session.py` and `tests/test_api/test_routes.py` already stub
`create_chat_session` and `_get_destination_names` — reuse that pattern rather than
inventing a second one. Use a live-Ollama run only as a final manual smoke test.

### Import direction

`services/` → nothing internal above it. `agents/` → `services/`. `cli/` and `api/` →
`agents/`. Enforce with:

```
grep -rnE "^\s*(from|import)\s+src\.(agents|cli|api)" src/services/
```

must return nothing. The narrower `from src.agents` form misses `import
src.agents.session`, which is exactly how a lazy type-hint import sneaks past. `src.api`
is included because nothing stops a service importing a pydantic model from `routes`.

**This check fails today** at `chat_session.py:19,28`. Run it before starting so the
"after" result is meaningful.

### Source-text assertion tests — a hidden hard dependency on the current paths

Four test functions do not import the modules; they **read their source text from
hardcoded paths and assert on exact code strings**. Deleting
`src/cli/trip_builder_svc.py` and `src/cli/planner_tools.py` makes all four raise
`FileNotFoundError`. This is not an import-path fix, and it is invisible to any grep
for `from src.cli`. Verified 2026-07-31 (RT-2):

| Test | Reads | Sample assertion |
|---|---|---|
| `test_trip_reuse_flow.py:6` `test_terminal_planner_persists_complete_bundles_and_exposes_finalization` | `:8` `trip_builder_svc.py`, `:9` `planner_tools.py` | `"[recommend_hotels, select_hotel, modify_trip_plan, finalize_trip_plan]" in tools` |
| `test_trip_reuse_flow.py:20` `test_finalized_itinerary_is_not_mutated_by_the_edit_tool` | `:22` `planner_tools.py` | ordering of two source substrings |
| `test_trip_intake.py:220` `test_destination_alias_schema_and_terminal_loader_contract` | `:226` `trip_builder_svc.py` | (already failing at baseline) |
| `test_trip_scheduler.py:499` `test_generated_trip_json_keeps_day_themes_only_with_the_itinerary_record` | `:501` `trip_builder_svc.py` | source substring presence |

Three of the four pass today, so they are new D11 failures the moment step 4 runs.

**Repointing the path is not enough for `test_trip_reuse_flow.py:15`.** That assertion
requires the literal string `[recommend_hotels, select_hotel, modify_trip_plan,
finalize_trip_plan]` to appear in the source — which this phase **deliberately
destroys** by replacing the static list with per-session tool factories. The test
encodes the current implementation shape as a contract.

Convert it, don't repoint it: assert on **behaviour** — build an agent via
`build_trip_agent(session)` and assert the names in its bound tool list, which is what
the test was actually protecting (that `generate_full_itinerary` is absent). Treat the
other three the same way where cheap; a mechanical path repoint is acceptable only
where the asserted string genuinely survives the move unchanged.

### The API test suite imports `src.main` at collection time

`tests/conftest.py:7` does `from src.main import app` at module scope, so **every** test
in `tests/test_api/` transitively imports `src.api.routes` → `src.agents.graph`. If
`src.main` fails to import at any intermediate commit, the whole API suite errors during
*collection*, not as a test failure — and the structural harness may become uncollectable
with it, removing the regression net exactly when it is needed. Step 10's `graph.py`
replacement is the moment this bites. Keep `src.main` importable at **every** commit,
and re-run `pytest tests/test_api -q --collect-only` as part of each per-step check.

## Related Code Files

- Create: `src/services/trip_planner.py`, `src/services/trip_formatter.py`
- Create: `src/agents/prompts.py`, `src/agents/session.py`, `src/agents/nodes/intake.py`,
  `src/agents/tools/{recommend_hotels,select_hotel,modify_itinerary,finalize_itinerary}.py`
- Modify: `src/agents/graph.py`, `src/agents/state.py`, `src/agents/__init__.py`,
  `src/agents/tools/__init__.py`, `src/agents/nodes/__init__.py`
- Modify: `src/cli/terminal_chat.py`, `src/cli/__init__.py`, `scripts/poc_trip_planner.py`
- Modify: `src/main.py` — drop the now-meaningless `_clear_pending_hotel_selection()`
  lifespan call and its import
- Modify: `src/api/routes.py` — import path changes only; the full rewrite is Phase 3
- Delete: `src/cli/trip_builder_svc.py`, `src/cli/planner_tools.py`,
  `src/services/chat_session.py`, `src/agents/nodes/example_node.py`,
  `src/agents/tools/example_tool.py`
- Modify (forced by removing the `graph.py` stub): `tests/test_agents/test_graph.py`
- Modify (import paths): `tests/test_chat_session.py`, `tests/test_terminal_chat.py`,
  `tests/test_planner_tools_hotel_flow.py`, `tests/test_api/test_routes.py`,
  `tests/test_trip_modification.py`, `tests/test_trip_cloning_and_recommendations.py`
- Modify (**source-text assertions — rewrite, not repoint**; see the section above):
  `tests/test_trip_reuse_flow.py` (`:8,9,22`), `tests/test_trip_intake.py` (`:226`),
  `tests/test_trip_scheduler.py` (`:501`)
- Create: `tests/test_agents/test_session.py`, `tests/test_services/test_trip_formatter.py`

## Implementation Steps

1. **Announce before starting.** This moves 2314 lines that teammates committed within
   the last two days. Confirm nobody has `src/cli/` work in flight; if they do,
   sequence after theirs. Do the whole phase on one short-lived branch and land it fast.
2. Run `impact({target: "process_chat_turn", direction: "upstream"})` and
   `impact({target: "_build_trip_data", direction: "upstream"})` per `CLAUDE.md`;
   report the blast radius. Expect HIGH or CRITICAL — this is a package-level move.
3. **Build the structural harness first** (see "Regression checking without a text
   diff"). Script a full session — intake → hotel prefs → hotel list → pick 1 → edit
   day 2 → finalize — with a stubbed LLM, and record the structural signature. Every
   later step re-runs it. This is a prerequisite, not a nicety: it is the only
   regression net for the whole phase. Record the pre-move `grep` import-check result
   too (it currently finds 2 violations).
4. Move `trip_builder_svc.py` → `src/services/trip_planner.py`, imports only. Harness. Commit.
5. Split the formatting helpers into `trip_formatter.py`. Harness. Commit.
6. Add `to_trip_plan_payload()` and `to_hotel_options_payload()` with unit tests against
   a fixture captured from a real `data/current_trip_plan.json`. New code, not a move —
   test them properly.
7. Create `src/agents/session.py`: move `chat_session.py` into it (D9), absorb
   `ChatSession` into `TripSession`, and add `SessionRegistry` **with its own
   `_registry_lock`** and lock-aware eviction. **Then do the state-access rewrite** —
   convert all 26 file-I/O call sites to read/write session fields, and route both save
   helpers through `persist_hook`. Review this as a rewrite, not a move. Run the harness
   after each of the four files. Install the CLI's hook so the two JSON files keep
   updating. Remove the lifespan `_clear_pending_hotel_selection()` call.
8. Move `SUPERVISOR_PROMPT` to `prompts.py` **byte-identical**.
9. Convert the **4 agent-visible** `@tool`s into session-bound factories, one file per
   tool, docstrings verbatim. Move `generate_full_itinerary`, `_generate_and_save_itinerary`
   and `_legacy_modify_trip_plan` to `services/trip_planner.py` as plain functions and
   **do not register `generate_full_itinerary`** with `create_react_agent` — wiring it in
   would let the LLM bypass the hotel-pick gate that `select_hotel` enforces. Move
   `execute_trip_edit_request` to `agents/session.py`. Run the harness after each tool.
   **Highest-risk step.**
10. Replace `graph.py`/`state.py` stubs with `build_trip_agent(session)` /
    `TripAgentState`; delete the two `example_*` files; update `src/api/routes.py` so it
    still imports and `POST /api/v1/chat` still responds (full rewrite lands in Phase 3).
11. Update `terminal_chat.py` to route on session fields instead of `os.path.exists(...)`,
    keeping `_suggestion_action`'s behaviour identical.
12. Rewrite the import block in `scripts/poc_trip_planner.py`.
13. Update every test module in the "Related Code Files" list for the new import paths;
    rewrite `tests/test_agents/test_graph.py`; add the session and registry tests.
13a. **Convert the four source-text assertion tests** (RT-2). Rewrite
    `test_trip_reuse_flow.py:15`'s tool-list assertion as a behavioural check on
    `build_trip_agent(session)`'s bound tool names — it is the guard that
    `generate_full_itinerary` stays unregistered, and a path repoint would leave it
    asserting a string this phase deliberately deletes. Handle the other three the same
    way, or repoint only where the asserted string genuinely survives unchanged.
14. Re-run the harness and confirm the structural signature is unchanged from step 3.
15. Run the import-direction grep — it must now return nothing.
16. Drive `GET /chat` through a full browser conversation, and the CLI through one full
    run against live Ollama. Judged by eye.

## Success Criteria

- [ ] `grep -rnE "^\s*(from|import)\s+src\.(agents|cli|api)" src/services/` returns
      nothing (it finds 2 violations before this phase)
- [ ] `grep -rn "supabase\|open(\|requests\." src/agents/` returns nothing
- [ ] `src/cli/` contains terminal I/O only — no planning function, no `@tool`
- [ ] Structural signature matches the step-3 baseline for the same scripted input,
      including `suggestions_for()` output
- [ ] No `open(` or `os.path.exists(` on the two plan files outside `persist_hook`
- [ ] CLI still writes both JSON files after every turn
- [ ] `GET /chat` completes a full conversation with no code change to the page
- [ ] `generate_full_itinerary` is not in any `create_react_agent` tool list
- [ ] Persisted itineraries carry the real session id, not `poc_trip_planner_1`
- [ ] Two `TripSession`s hold independent `trip_data` **and** `pending_hotel_selection`
- [ ] `SessionRegistry` evicts on TTL and on the size cap — unit tested
- [ ] Concurrent `resolve` with the same new id returns the **same** object — unit tested
- [ ] `evict_expired()` skips a session whose lock is held — unit tested
- [ ] `to_trip_plan_payload()` / `to_hotel_options_payload()` validate against Phase 3's models
- [ ] `src/main.py` no longer clears a global pending-selection file at startup
- [ ] `grep -rn 'src" / "cli"' tests/` returns nothing — the four source-text assertion
      tests are converted, not left pointing at deleted files (RT-2)
- [ ] The `generate_full_itinerary`-is-unregistered guard is a behavioural assertion on
      `build_trip_agent(session)`, not a source-string match (RT-2)
- [ ] `pytest tests/test_api -q --collect-only` succeeds at **every** commit in the
      phase, not only the last (RT-4)
- [ ] The debug persist hook rejects a `session_id` outside `[A-Za-z0-9_-]+` and builds
      its path with `pathlib` — unit tested with `../` in the id (RT-5)
- [ ] D11 gate: no new test failures, no new collection errors, `ruff` clean on every
      file this phase creates or edits

## Risk Assessment

| Risk | Mitigation |
|---|---|
| **Merge conflicts with teammates** — this moves 2314 lines committed within 48 hours | Top risk in the plan, and worse than in July (the file grew 74%). Step 1 announces first, checks for in-flight work, and requires one short-lived branch landed fast |
| A "move" that silently changes behaviour | Steps 4-9 each end with the structural harness check; commit per step so a regression bisects to one move |
| **The rewrite is mistaken for a move** and `open()` calls survive into `services/` | "Two kinds of change" separates them; the "no `open(` outside `persist_hook`" criterion catches it mechanically |
| The 26-call-site table is stale by the time step 7 runs | Step 7 says re-count after Phase 1; the table itself flags the `_saved_duration_days` dependency |
| Registry-level races (duplicate session objects, eviction mid-request) | `_registry_lock` + lock-aware eviction, both unit tested. Easy to omit because the per-session lock *looks* sufficient — and `routes.py:18` shows the mistake already shipped once |
| `generate_full_itinerary` wired into the agent, bypassing the hotel gate | Called out in the move map, step 9, and a success criterion — three places, because the symmetric-looking 5-tool layout invites the mistake |
| Tool docstrings reworded → model stops calling tools in the right order | Steps 8-9 say verbatim; `SUPERVISOR_PROMPT` sequencing rules depend on exact tool names |
| **`GET /chat` breaks silently** because `suggestions[]` changed shape | It is in the harness signature (item 5) and has its own success criterion. The page is the only UI until Phase 4 |
| Per-session compiled agents leak memory | TTL 2h + 200 cap + LRU, asserted in the registry test. Fallback: shared agent with `RunnableConfig` injection |
| `SessionRegistry` is process-local | Documented: single uvicorn worker. Multi-worker needs Supabase-backed sessions (out of scope) |
| Circular import `agents.tools` → `services.trip_planner` → `agents` | One-way rule enforced by the grep in Success Criteria |
| Test modules break on import paths and get "fixed" by weakening assertions | They are listed explicitly in Related Code Files; the D11 gate compares failure counts against a recorded baseline, so a silently disabled test shows up as a passing-count drop |
| **Four source-text assertion tests break with `FileNotFoundError`** and are invisible to any `from src.cli` grep (RT-2) | Their own section, table, Related-Code-Files entry, step 13a and success criterion. Three of the four pass today, so they land as new D11 failures the moment step 4 runs |
| The tool-list assertion is "fixed" by repointing the path, silently keeping a string check this phase invalidates by design (RT-2) | Step 13a requires converting it to a behavioural check on the bound tool list — it is the guard that `generate_full_itinerary` stays unregistered |
| **The API suite stops collecting mid-phase**, taking the regression harness with it (RT-4) | `conftest.py:7` imports `src.main` at module scope; `--collect-only` is added to the per-step check and has its own success criterion |
| Path traversal via `session_id` in the debug hook (RT-5) | Validated at the write site in this phase, not deferred to Phase 3's boundary typing — the CLI reaches the same hook with a non-UUID id |
| Session eviction silently destroys conversation history, and the 200 cap is sized against the wrong thing (RT-8) | `MemorySaver` is per-session (`planner_tools.py:567`); "What eviction actually discards" states both consequences and requires measuring one real session before trusting the cap |
