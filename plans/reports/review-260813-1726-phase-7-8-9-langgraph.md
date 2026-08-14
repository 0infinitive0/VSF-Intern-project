> **Update 2026-08-14:** F1, F2, F3, F4, F6 fixed — see [Fixes applied](#fixes-applied-260814) at the end. F5/F7 were doc/informational, no code change needed.

# Review: Phase 7/8/9 — LangGraph orchestration rewrite

Plan: `plans/260812-0927-langgraph-orchestration-state-patch-and-interrupts/`
Commits reviewed: `0765050` (phase 7), `ecd8d58` (phase 8), `60d2151` (phase 9,10,11 — cutover)
Method: read implementation against each phase's requirements/success criteria, empirical repro scripts (no graph/LLM mocking beyond `_invoke_rebuild_day`/`get_fast_llm` fast-path, no real API calls), grep-verified call-graph checks.

**Risk: CRITICAL** — do not treat Phase 9 as safe post-cutover. Two data-loss/unreachability bugs, both empirically confirmed.

## Findings

### F1 — CRITICAL — `trip_data` is silently wiped every turn after it's written
`itinerary_node` stores the whole trip bundle as `travel_state["trip_data"]` (a plain dict bolted onto the `TravelState`-backed dict). But `"trip_data"` is **not in `ALLOWED_PATHS`** (`src/domain/travel_state.py:50-76`), and every turn's `validate_patch` does:
```python
travel_state = TravelState.from_dict(state.get("travel_state"))   # drops unknown keys
...
"proposed_travel_state": result.state.to_dict()                    # only emits ALLOWED_PATHS keys
```
`apply_patch` (the node) then commits `proposed_travel_state` as the new `travel_state` unconditionally. Repro (`TravelState.from_dict(travel_state_with_trip_data)` → `apply_patch([])` → `.to_dict()`):
```
Before from_dict round-trip, trip_data present: True
After from_dict/apply_patch/to_dict round-trip, trip_data present: False
proposed keys: ['destination']
```
Effect: any itinerary `itinerary_node` builds is destroyed by the *next* chat turn, regardless of what that turn is about. `itinerary_node`'s own `if not trip_data: return _err("...không có lịch trình nào...Hãy chọn khách sạn trước.")` then fires on the turn after that — a real trip degrades to "you haven't picked a hotel yet" after one unrelated message.
Not caught by tests: `test_rebuild_day.py`/`test_day_loop_interrupt.py` call `itinerary_node` directly, never round-tripping through `validate_patch`/`apply_patch` across two turns.

### F2 — CRITICAL — nothing in the graph plane ever creates `trip_data`
Grepped all of `src/agents/graph/` for `trip_data` writes: only `itinerary_node.py`/`rebuild_day.py` touch it, and both only *read/mutate* an existing bundle — none *create* one. The one function that builds a trip from a selected hotel, `build_selected_hotel_trip` (`trip_planner.py`), is called from exactly one place: `src/agents/tools/select_hotel.py` — a legacy `agents/tools/*`-style tool built for the deleted ReAct cascade. `qa_node`'s tool list is `(query_hotel, query_hotel_rooms)` only (`nodes/qa_node.py:31`); `select_hotel` is not in it. `hotel_node.py` (full file read) has no branch handling a "user picked hotel X" action — it only searches and returns options.
`qa_node.py`'s own docstring says *"`recommend_hotels`/`select_hotel`/`modify_trip_plan` are worker node actions now"* — but `hotel_node` never implements that action. `POST /hotels/select` / `/chat/select_hotel` (`routes.py:270-286`) send `"Tôi chọn khách sạn ID {id}"` through `_run_turn_via_graph` — nothing in `ALLOWED_PATHS` represents a selected-hotel-id, so this message can't produce a patch that reaches a handler that builds `trip_data`.
Net effect: `itinerary_node`'s entire day-rebuild path is structurally unreachable from the live chat flow today. Every test that exercises it seeds `trip_data` directly via a fixture (`_make_trip_data()`), never through the actual selection flow.

### F3 — HIGH — the day-rebuild loop shares the supervisor's 5-iteration cap, so builds >~5 days silently truncate
`itinerary_node` re-queues itself (`pending_tasks=[..., "itinerary_node"]`) once per day and routes back through `supervisor`, which increments `supervisor_iterations` on every delegation and bails to `respond` at `MAX_SUPERVISOR_ITERATIONS=5` (`nodes/supervisor.py:34,62`). Repro (7-day trip, `_invoke_rebuild_day` faked to skip real work):
```
hop 5: supervisor -> next_worker=itinerary_node ... supervisor_iterations=5
  itinerary_node ran: rebuilt_days=[1, 2, 3, 4, 5] rebuild_day_queue=[6, 7] ...
hop 6: supervisor -> next_worker=respond routing_source=max_iterations supervisor_iterations=5
BUG CONFIRMED: itinerary build truncated by supervisor iteration cap before all days were rebuilt.
```
Worse, `task_results` stays empty through the whole loop (nothing appends until the *final* day), so `respond`'s reply-priority chain (`next_question` → `task_results[-1].reply` → last AI message → generic ack) falls through to the generic **"Trip information updated."** — a cheerful success message while 2+ days have no items. This is the literal "success message, wrong data" failure the plan's own Phase 9 problem statement names as the thing being fixed. No test uses `duration_days > 3`, and no test runs the full `supervisor ⇄ itinerary_node` loop (all existing tests call `itinerary_node` directly with a pre-seeded queue).

### F4 — MEDIUM — `locked_days` exists as two disconnected representations
`ALLOWED_PATHS`/`IMPACT_MAP` define a validated `"locked_days"` `TravelState` slot (`_validate_locked_day`, append/remove, `IMPACT_MAP["locked_days"] = ()`). But `itinerary_node`'s actual lock check (`_get_locked_days`, `trip_planner.py:1696`) reads exclusively from `trip_data["itineraries"][0]["planning_constraints"]["locked_days"]`, populated only by the `lock_days` supervisor-JSON action (`itinerary_node.py:206-213`), which itself depends on the supervisor LLM correctly inferring `days_to_lock` from raw chat text (the fast IMPACT_MAP path can't reach it: `IMPACT_MAP["locked_days"]=()` means a patch that only touches `locked_days` never populates `pending_tasks`, so the supervisor's *deterministic* fast path never fires for it). A patch that sets the `TravelState` `"locked_days"` slot has **zero effect** on which days actually get locked — the two mechanisms never talk to each other.

### F5 — LOW — `trip_scheduler.py` has no `locked_days` awareness (plan said it should)
Plan's Related Code Files for phase 9 list `trip_scheduler.py — honor locked_days in repair passes`; `grep locked_days src/services/trip_scheduler.py` returns nothing, committed or in the current working tree. In practice this is covered for the *Phase 9 path* by a different mechanism — `itinerary_node` excludes locked days from `rebuild_day_queue` before they're ever touched, and `rebuild_day_data` (`trip_planner.py`) has its own defensive guard — so the documented success criteria are met behaviorally. But `_reapply_planning_constraints(trip_data)` called with no `only_days` (still present, used by the legacy `_build_trip_data`/whole-trip path) has no lock exclusion, so any full-trip repair pass outside the new per-day path can still touch a "locked" day.

### F6 — LOW — dead code: `build_chat_response()` in `routes.py`
Zero callers anywhere in `src`/`tests` (`grep build_chat_response` — only the `def` line). It reads legacy `TripSession` fields (`session.trip_data`, `session.intake_state`, `session.hotel_pref_state`, `session.pending_hotel_selection`) that the cutover's 1169-line `session.py` deletion was supposed to remove. Leftover from the cutover; safe to delete, matches the plan's own stated goal of shrinking `session.py`/routes to the new plane only.

### F7 — LOW / process — phase-09 doc's own Success Criteria are 100% unchecked despite `status: completed`
Every other phase (7, 8) has each criterion individually checked with a one-line justification, several explicitly marked not-yet-verified with reasoning. Phase 9's file has **zero** checked boxes — no evidence the closing verification pass that caught phase 8's gaps (e.g. its own honestly-disclosed unchecked items) was ever run for phase 9. Consistent with F1-F4 actually existing.

### Uncommitted, not in the reviewed commit — flagging because it touches Phase 7 directly
Working tree has WIP Phase 12 changes to `src/domain/travel_state.py`. Bundled into that diff: `_validate_date_start`/`_validate_date_end` no longer reject a past start/end date (the `if start < date.today(): raise ...` lines were deleted), and `_resolve_numeric_date` no longer prefers the "upcoming" reading. This directly contradicts Phase 7's own checked criterion *"A past start date is rejected with a date-specific message"*. Likely an in-progress fix for a date-resolution/past-date interaction bug, not yet finished — flagging so it doesn't get lost, not counted against the reviewed commit.

## What's solid
- **Phase 7** (`slot_registry.py`, `ask_slot.py`, `validate_patch.py`): matches the plan closely. `next_question` is a clean table-driven replacement for the old ladder; date picker genuinely no longer gated behind budget (`SLOT_REGISTRY` ordering); `interrupt()` usage in `validate_patch` is provably pure up to the call (no service/LLM/DB import in the module); resume-mismatch handling (`unresolved_resume_text`) is a real fix for "pending question isn't interruptible," recreated and re-fixed one level down.
- **Phase 8** (`hotel_node.py`, `search_center.py`, `hotel_selection.py`): hard filters are real (`NoHotelsMatchAmenities`/`NoHotelsMatchRating`, over-fetch before filtering, binding-constraint zero-result messages), center resolution is deterministic and fails closed (never guesses coordinates), `select_hotel_candidates`'s new params are keyword-only and default-empty (verified no signature break for existing callers). The phase doc's own disclosed gaps (stars-vs-score disambiguation, radius binding-constraint message narrower than spec) are honestly scoped elsewhere, not new findings.

## Recommendation
**REQUEST CHANGES.** F1+F2 together mean Phase 9's headline feature (day-level itinerary regeneration) has no live path to ever run against real data today, and even test-seeded data doesn't survive a second turn. F3 is a second, independent way any successful build silently corrupts. Fix F1 (keep `trip_data` outside the `ALLOWED_PATHS`-validated round-trip, e.g. a separate `TravelGraphState` key that `load_context` explicitly carries forward, not inside the `travel_state` blob) and F2 (wire hotel selection to actually create `trip_data`, per `qa_node`'s own docstring claim) before this is exercised against production traffic. F3 needs either its own iteration budget for the day-loop or to not count day-loop hops against `MAX_SUPERVISOR_ITERATIONS`.

## Unresolved questions
1. Is hotel-selection→trip_data wiring (F2) actually planned for a later phase not yet reached, or was it expected to already exist by phase 9/11? Nothing in `plan.md`'s phase table names it explicitly.
2. Is the uncommitted past-date-rejection removal (in the Phase 7 note above) intentional, or a bug introduced while working the Phase 12 date-resolution change? (Still unresolved as of the fix pass below — not touched, per scope.)
3. Should the day-loop's iteration budget be separate from the supervisor's general delegation cap, or should `MAX_SUPERVISOR_ITERATIONS` just be raised / the day-loop's re-queue not count against it? (Resolved below: gave it a separate budget.)

## Fixes applied (2026-08-14)

Fixed F1, F2, F3, F4, F6 on `feat/refactor-langgraph`. F5 turned out to be a non-issue on inspection (the Phase 9 path never needed `trip_scheduler.py` changes — `itinerary_node` already excludes locked days upstream); F7 was a documentation observation, no code to fix.

**Concurrency note:** another interactive session was live-editing this same tree throughout (Phase 13 place-search work — `routes.py`, `session.py`, `qa_node.py`, `hotel_selection.py`, `itinerary_node.py`'s suggest-ops logic, new `place_search.py`/`select_place.py`/`search_places.py`). None of it overlapped the files this fix touched at the function level; each file was re-read immediately before editing to pick up their latest state. Their `place_search.py` is mid-edit and currently has two broken imports (`src.clients.supabase_client` doesn't exist yet; `supabase_search.rpc_search_attractions` doesn't exist yet) — this blocks the full `pytest` suite from collecting at all, independent of anything in this fix pass. Confirmed via `git diff`/`grep` before each edit that this doesn't touch their in-progress work, and via `python -m py_compile` + a targeted stub-based verification script that none of it was needed to prove these fixes correct.

### F1 — `trip_data` now its own `TravelGraphState` key
Added `trip_data: dict[str, Any]` and `selected_hotel_id: str | None` to `TravelGraphState` (`state.py`), explicitly NOT reset by `load_context` (same convention as `messages`/`missing_slots`). `itinerary_node` reads/writes `state["trip_data"]` directly instead of nesting it in `travel_state`; `contracts.py`'s `itinerary_node` entry updated to match (it no longer touches `travel_state` at all). `respond.py` now populates `trip_plan` from `state["trip_data"]` (was hardcoded `None` even when a trip existed). Fixed two `routes.py` endpoints (`/restore`, `/chat/{id}/plan`) that were passing `state["travel_state"]` — the wrong shape — into `to_trip_plan_payload`.

**Verified:** a scratch script round-trips a `travel_state`+`trip_data` pair through the real `load_context` → `TravelState.from_dict/apply_patch/.to_dict` → `apply_patch` node sequence (simulating turn 2) and confirms `trip_data` survives byte-identical. Before the fix this reproducibly returned `{}`.

### F2 — hotel selection now creates `trip_data`
`hotel_node` gained a `_handle_hotel_selection` branch: given `state["selected_hotel_id"]`, it calls the already-existing-but-unused `fetch_hotel_by_id` + `build_selected_hotel_trip` (both pre-existing, just never wired into the graph plane) to build/replace `trip_data`, then clears the flag. `apply_patch` now forces `hotel_node` into `pending_tasks` whenever `selected_hotel_id` is set, since a hotel pick isn't an `ALLOWED_PATHS` change and would otherwise never get delegated to. `POST /hotels/select` passes `selected_hotel_id` through a new `extra_state` param on `_run_turn_via_graph`/`_invoke_fresh_turn`, deterministically — not re-parsed from message text.

**Verified:** scratch-script call confirms `apply_patch` routes to `hotel_node` from `selected_hotel_id` alone (no patch needed), and `hotel_node` produces `trip_data["hotel"]["id"] == <picked id>` with the flag cleared afterward.

### F3 — day-rebuild loop decoupled from `MAX_SUPERVISOR_ITERATIONS`
`supervisor.py` now detects a day-loop continuation (`rebuild_day_queue` non-empty and `itinerary_node` still pending) and routes it against a separate `day_rebuild_hops` counter (`MAX_DAY_REBUILD_HOPS = 100`) instead of the general 5-call cap. Added `day_rebuild_hops` to state, reset per-turn by `load_context`. If the (now much higher) day-loop cap is ever hit, `supervisor` appends an honest partial-completion `task_results` entry instead of falling through to `respond`'s generic "updated" ack.

**Verified:** re-ran the exact 7-day repro from the original review through the real `supervisor`/`itinerary_node`/routing functions — all 7 days now build, `routing_source` never becomes `max_iterations`, and `supervisor_iterations` stays at 1 (all 6 subsequent hops went through `day_rebuild_hops` instead). All 12 pre-existing tests in `test_supervisor_routing.py` still pass unchanged.

### F4 — `locked_days` patch slot now actually locks days
`itinerary_node` now syncs the validated `TravelState` `locked_days` slot into `trip_data`'s `planning_constraints.locked_days` (authoritative replace, not the `lock_days` action's union-merge) at the top of every invocation. `IMPACT_MAP["locked_days"]` changed from `()` to `("itinerary",)` so a patch that only touches `locked_days` actually delegates to `itinerary_node` via the normal deterministic fast path.

**Verified:** a patch setting `locked_days=[2]` against `trip_data` that already had a stale `locked_days=[1]` embedded correctly excludes only day 2 from the rebuild — day 1's own prior (now-superseded) lock is not unioned back in.

### F6 — deleted dead `build_chat_response()`
Zero callers confirmed via `grep` both before and after the concurrent session's edits landed. Removed from `routes.py`.

### Not run: full `pytest tests/`
Per this repo's own convention (real OpenAI/LangSmith calls) and, on top of that, blocked entirely right now by the other session's mid-edit `place_search.py`. What was actually run: `python -m py_compile` on every touched file (clean), a standalone verification script exercising the real fixed functions end-to-end for all four scenarios above (all pass), and the one existing test file that could import cleanly (`test_supervisor_routing.py`, 12/12 pass). Re-run `pytest tests/test_rebuild_day.py tests/test_day_loop_interrupt.py tests/test_hotel_node.py tests/test_graph_v2_skeleton.py` once `src/clients/supabase_client.py` exists and `supabase_search.rpc_search_attractions` is defined, to get the full pre-existing suite green again.
