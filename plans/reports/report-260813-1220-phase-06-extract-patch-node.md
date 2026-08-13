---
phase: 6
plan: 260812-0927-langgraph-orchestration-state-patch-and-interrupts
title: "extract_patch node"
status: done
---

# Phase 6 completion report

## What shipped

Filled `backend/src/agents/graph_v2/nodes/extract_patch.py` (Phase 5's always-empty stub) with
the real node: one LLM call producing `{intent, changes[]}`, defensive parsing (strict JSON
parse → structural validate → retry once with the rejection reason → fall back to
`{"patch": [], "intent": "general_question"}`, never raises), deterministic day-scope rewrite,
and deterministic grounding for destination + the closed preference/companion/pace/day_rhythm
label sets.

- `backend/src/agents/graph_v2/nodes/extract_patch.py` — full implementation (was a 2-line stub)
- `backend/src/agents/graph_v2/prompts.py` — `build_extract_patch_prompt`, the one-call
  `{intent, changes}` schema prompt, reusing `trip_intake.py`'s closed label sets as the
  grounding vocabulary
- `backend/src/agents/graph_v2/state.py` — `TravelGraphState.intent` (audit-trail only, never
  routes), defaulted in `initial_graph_state`
- `backend/src/agents/graph_v2/nodes/load_context.py` — resets `intent` per turn
- `backend/src/domain/travel_state.py` — `_trip_duration_days` → public `trip_duration_days`
  (2 internal call sites updated), reused by the day-scope rewrite instead of duplicating it
- `backend/tests/test_extract_patch.py` — new, 25 tests: the doc §34 phrase table (as a test of
  this node's deterministic pipeline, not model accuracy — see the file's own docstring),
  call-count invariants, retry/fallback, destination/label grounding, day-scope rewrite,
  corrected-slot behavior
- `backend/tests/test_graph_v2_skeleton.py` — the Phase 5 e2e test now also monkeypatches
  `extract_patch`'s LLM/destination factories (it previously relied on the stub's permanent
  no-op; left unpatched it was making a real Ollama + Supabase call)

## Decisions made this session

The phase-06 doc predates Phase 5's actual delivery and is stale in three material ways;
scouted evidence resolved all three without needing a stop:

1. **File location.** The doc says create `backend/src/agents/nodes/extract_patch.py`; Phase 5
   already created `backend/src/agents/graph_v2/nodes/extract_patch.py` as the wired stub.
   Filled that file in place — no new path.
2. **"Falls back to `decide_route_by_rules`."** That function is legacy-plane-only (`RouteContext`,
   `TripState`, a 5-way `finalize|new_trip|edit_draft|intake|chat` label — a different concept
   than `{intent, changes}`) and is scheduled for deletion at Phase 11 cutover. The graph plane
   already has its own deterministic fallback for "nothing to route" (empty `pending_tasks` →
   supervisor's existing IMPACT_MAP/LLM path, unchanged from Phase 5). Implemented the literal
   requirement — **the turn still completes, no exception surfaces** — via that existing
   mechanism instead of importing the legacy router.
3. **Did not touch `session.py`/`trip_intake.py`/`trip_edit_planner.py` legacy call sites.** The
   doc's Related Code Files lists them as "Modify," but Phase 11's own risk table says the
   opposite: `TripIntakeState.with_message` and `TripPreferenceUpdate` are **deleted wholesale**
   at cutover, not migrated. Phase 5 established `orchestrator=legacy` stays byte-identical by
   design. Rewriting legacy call sites now to share extraction logic that Phase 11 deletes
   outright would be net-negative: real regression risk on the live production path, for code
   with a known deletion date. `_match_known_destination` and the closed label sets are
   **reused** (imported), not duplicated — satisfying the doc's actual grounding-vocabulary
   intent without the legacy rewrite.
4. **Day-scope ordinals ("hôm đầu", "ngày cuối") are NOT added to the shared
   `trip_scheduler.parse_day_scope`.** That function's only other caller
   (`trip_edit_planner.build_trip_edit_context`) always has a real, already-built itinerary
   length; this node usually doesn't (pre-dates-set turns are common). Added `_resolve_day_scope`
   locally in `extract_patch.py` instead: numeric/range phrasing still delegates to
   `parse_day_scope` (reused, not duplicated); first-day resolves unconditionally to day 1;
   last-day only resolves once the trip's real length is known (`travel_state.py`'s
   `trip_duration_days`) — guessing it off the generous 90-day pre-dates fallback would silently
   target the wrong day. Verified both branches with a test.
5. **Grounding gap not stated explicitly in the doc:** `apply_patch`'s own validators
   (`_nonempty_str`) do **not** enforce known-destination matching or the closed label sets —
   that enforcement lived only in the legacy `_ground_extracted_facts`. Without a code-side
   grounding step in this node, a hallucinated city or an out-of-vocabulary theme label would
   sail straight through `apply_patch`'s weak generic-string validator. Added `_ground_changes`
   as an explicit post-extraction pass (destination via `_match_known_destination`, the four
   closed label sets via set-membership filtering) — matches the doc's "destination grounding
   stays deterministic" requirement and its "keep the closed label sets... as the grounding
   vocabulary" implementation step literally.

## Bug found and fixed during self-review

**Model-construction failures weren't caught by the retry/fallback loop.** First draft called
`get_reasoning_llm(temperature=0.0)` once, before the `try`/`except` retry loop — so a factory
failure (not a `.invoke()` failure) propagated uncaught and crashed the whole node, violating
the "never raises, turn still completes" requirement. Caught by my own regression test for the
e2e test file (`test_graph_completes_a_turn_end_to_end_and_returns_a_planner_chat_response`,
updated to monkeypatch `get_reasoning_llm` itself, not just `.invoke`) — the test failed with
an uncaught `RuntimeError` instead of exercising the fallback. Fixed by moving model
construction inside the retry loop's `try` block.

## Known limitations (flagged, not fixed — by design or out of scope)

- **Model accuracy against the doc §34 phrases is not measured here.** `test_extract_patch.py`
  tests this node's deterministic pipeline (parsing, day-scope rewrite, grounding) against
  simulated model responses for each phrase — real model comprehension of Vietnamese phrasing
  is Phase 10's "State Patch Accuracy" eval, a different and necessarily-model-dependent kind
  of test.
- **`orchestrator=graph` still only dispatches `POST /planner_chat`** (Phase 5's known
  limitation, unchanged by this phase). `extract_patch` is unreachable from the frontend's
  actual default transport (`/planner_chat/stream`) until later phases.
- **Append/remove operations on `hotel_preferences.amenities`/`locked_days` are not
  closed-set-grounded** — by design; those two paths accept any non-empty string / valid day
  number respectively (no vocabulary to enforce), matching `apply_patch`'s own validators.

## Verification

- `pytest tests/test_extract_patch.py` — 25/25 passed, no real LLM/network calls (all
  monkeypatched).
- `pytest tests/test_graph_v2_skeleton.py tests/test_supervisor_routing.py` — 23/23 passed
  (0.69–0.7s total, confirming no accidental network/LLM calls after the e2e test fix).
- `pytest tests/test_travel_state.py tests/test_trip_scheduler.py tests/test_trip_edit_planner.py`
  — all passed (untouched by this phase's changes; run to confirm the `trip_duration_days`
  rename didn't break anything).
- `ruff check` on every touched file — clean (2 findings found and fixed: an unused local, an
  unsorted import block).
- `mypy` scoped to every touched `src/` file — **zero** errors in the touched files themselves.
  (The full `mypy src/` run surfaces ~110 pre-existing errors in `trip_planner.py`/
  `hotel_selection.py`, files this phase imports from but does not modify — matches the
  documented baseline in `.claude/agent-memory/code-reviewer/lint-type-baselines-are-red.md`.)
- `gitnexus detect_changes(scope="all")` — 43 changed symbols across 13 files, all inside the
  intended scope (`extract_patch.py` and its new helpers, `prompts.py`, `state.py`,
  `load_context.py`, `travel_state.py`'s rename, the two test files). 8 affected processes, all
  newly-reachable `extract_patch`-rooted flows (expected: the node went from a permanent no-op
  to a real, wired implementation) — no unrelated flow was touched. `AGENTS.md`/`CLAUDE.md`/
  gitnexus-skill files also show as changed in this scope but predate this session (pre-existing
  uncommitted changes, not made by this work) and were left alone.
- **`make test` (`pytest tests/` unscoped) was intentionally NOT run** — project convention
  (this session's memory, and Phase 5's own report) is that several unrelated test files hit
  real OpenAI/LangSmith via `.env` credentials. Ran every test file this phase's scope evidence
  named or touched instead (see above), all green.
- **Pre-existing, unrelated:** `tests/test_trip_intake.py` has 6-7 failures depending on run
  (one, `test_preference_update_replaces_confirmed_facts_and_recalculates_end_date`, is flaky —
  reproduced passing and failing across 3 consecutive isolated runs with zero code changes,
  smelling of hash-seed-dependent set iteration order in legacy code this phase never touches).
  Confirmed via `git stash` that all of these predate this session's changes.

## Unresolved questions

- None blocking. Phase 7 (slot registry/interrupt) is the next dependency-satisfied phase.
