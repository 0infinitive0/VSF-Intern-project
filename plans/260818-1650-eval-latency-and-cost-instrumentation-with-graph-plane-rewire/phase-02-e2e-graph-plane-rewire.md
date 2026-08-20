---
phase: 2
title: "Layer 2 graph-plane rewire"
status: complete
priority: P1
effort: "1-1.5d"
dependencies: []
---

# Phase 2: Layer 2 graph-plane rewire

## Overview

`eval/harness/e2e_eval.py` cannot import. Point it at the LangGraph plane that replaced the
deleted `session.py` entry points, re-adjudicate the two golden conversations whose
`expected_stage` the new plane can no longer emit, and get a scored e2e run back.

This phase also owns the **Vietnamese-only filter** (plan.md's scope constraint), because it
already owns dataset adjudication and `eval/datasets/README.md`. The filter spans both layers, not
just e2e.

## Requirements

- Functional: `run_e2e_eval()` drives each scripted turn through the same code path a real HTTP
  chat turn takes, including the interrupt/resume branch.
- Functional: hotel selection uses the graph's `selected_hotel_id` signal, not a deleted helper.
- Functional: stage comparison uses `agents/graph/response_payload.py::derive_stage` with its
  real three-argument signature.
- Functional: the two `expected_stage: finalized` records are re-adjudicated and the decision is
  written down in `eval/datasets/README.md`'s adjudication log.
- Functional: both loaders default to Vietnamese-only, excluding the 14 EN mirrors and
  `conv-hcm-luxury-en` while keeping all 5 `hotel-crosslang-*` probes. One flag restores the full
  set.
- Non-functional: the filter predicate is "is an EN mirror", never `language == "en"` — the two
  EN-sentence crosslang probes must survive it.
- Non-functional: an eval run never writes to the real session store or the Supabase transcript,
  and never collides with a real `session_id`.
- Non-functional: `context_recorder.record_contexts()` still captures the turn's retrieved rows —
  `_execute_rpc` is unchanged by the cutover, so this should hold, but it must be verified rather
  than assumed.
- Non-functional: no file under `backend/src/` is modified by this phase. The plan's single
  production change (`stream_usage=True`) belongs to Phase 1; a rewire that needs a second one has
  found a real coupling problem and should surface it rather than absorb it.

## Architecture

**Driving a turn.** Reuse `routes._run_turn_via_graph(session_id, message, language, extra_state)`
rather than rebuilding a driver. It is a private module function, which is a real cost — but the
alternative is worse: `_run_turn_via_graph` owns the paused-thread resume branch, the
`unresolved_resume_text` re-run, and `_response_from_result`'s interrupt shape
(`routes.py:748-816`). A harness copy of that logic would drift the first time either changed, and
an e2e eval whose turn semantics differ from production measures the wrong system. Import the
private name deliberately and say so in a module docstring, the way `context_recorder.py`
documents its own monkeypatch.

**Keeping the run out of the real store.** `routes._persistence_enabled` (`routes.py:105`) is read
once at import from `_settings.session_persistence_enabled` and gates both `_persist_turn`
(`routes.py:737`) and the registry's load/delete hooks (`routes.py:116-117`). Set
`SESSION_PERSISTENCE_ENABLED=false` in the harness process environment *before* importing
`routes`, and assert `routes._persistence_enabled is False` immediately after import. An env var
set too late is silently ignored — the assert is what makes the failure loud. Keep the existing
`ragas-eval-` session-id prefix as a second layer of protection.

**Checkpointer.** `_get_graph_v2()` (`routes.py:640`) compiles with a process-local `MemorySaver`
when `registry.checkpointer` is unset, which is exactly the hermetic behavior the eval wants. The
harness must not set a checkpointer. Because the compiled app is module-cached, all conversations
in one run share one graph instance and are separated only by `thread_id` — each conversation's
session id must be unique per run.

**Hotel selection.** `SELECT_FIRST_HOTEL_ACTION` currently resolves the first pending option and
calls the deleted `handle_frontend_hotel_selection`. The graph equivalent (`routes.py:552-570`)
routes the same intent through `_run_turn_via_graph(..., extra_state={"selected_hotel_id": str(id)})`.
The option list itself now comes from graph state via
`response_payload.hotel_options_from_task_results(state)`, not from
`session.pending_hotel_selection`.

**Stage.** `derive_stage(state, hotel_options, reply)` — three arguments off graph state, not the
old one-argument `(turn_result, session)` form. Read the final state from
`app.get_state({"configurable": {"thread_id": session_id}}).values`, the same way `routes.py:487-499`
does.

**`_hotel_grounding_ratio` and `turn_class`.** Both currently key off `TurnResult.tool`, which no
longer exists. The graph's equivalent discriminator is the node that produced the reply. Re-derive
`_TEMPLATE_TOOLS` / `_MIXED_TOOLS` against graph node names (`hotel_node`, `itinerary_node`,
`booking_node`, `qa_node`, `ask_slot`, `respond`) by inspecting which node writes the reply, and
record the mapping in a comment. The grounding metric's *substance* is unchanged — compare the
hotel IDs shown to the user against IDs a real retrieval call returned — only its source of
"what was shown" moves to `hotel_options_from_task_results`.

**The `finalized` stage.** `derive_stage` returns only `error | intake | planned | hotel_options`.
`conv-hcm-finalize-4d` and `conv-hue-finalize-2d` expect `finalized` and cannot pass. This is
Open Question 1 and is decided here, on inspection, not silently: either those records are
re-pointed at `planned` (if the graph genuinely finishes those flows and `finalized` was a
distinction the new plane dropped on purpose — `session.py:41-45` suggests it was), or the missing
stage is a real regression in the graph plane and gets filed as such rather than papered over by
editing the dataset. Whichever it is, the reasoning goes in `eval/datasets/README.md`'s
adjudication log, and editing a golden record's expectation to match observed behavior is never
done without that note.

## The Vietnamese-only filter

Mirrors are identifiable structurally, which is what makes this safe to automate: an EN mirror is a
record whose `pair_id` also has a `vi` member. The 5 crosslang probes each hold a `pair_id` with no
partner (`eval/datasets/README.md:63-70` states this explicitly), so the same predicate that
removes every mirror leaves all 5 probes standing — including the two labelled `en`.

```
is_en_mirror(r) = r.language == "en" and any(other.pair_id == r.pair_id and other.language == "vi")
```

Implement in `dataset_loader.py` as `load_golden_retrieval(include_en_mirrors=False)` and
`load_golden_conversations(include_en_mirrors=False)`, plumbed to a `--include-en-mirrors` CLI flag.
Default off. Do not add a `language=` parameter — it invites exactly the `language == "vi"` filter
this design exists to avoid.

Assert the counts at load time (30 retrieval / 9 conversations, 5 crosslang present). A filter that
silently over-matches is the failure mode here, and it would show up as quietly better scores from a
smaller set rather than as an error.

## Related Code Files

- Modify: `eval/harness/e2e_eval.py` — imports, driver, hotel selection, stage, turn classing
- Modify: `eval/harness/dataset_loader.py` — the mirror filter on both loaders
- Modify: `eval/run_ragas.py` — `--include-en-mirrors` flag
- Modify: `eval/datasets/golden-conversations.jsonl` — only the re-adjudicated `expected_stage`
  values, if that is the decision
- Modify: `eval/datasets/README.md` — adjudication log entry, plus a note that EN mirrors are
  retained in the file but excluded from default runs
- Modify: `eval/harness/transcripts.py` — if the turn record's field names change
- Read: `backend/src/api/routes.py:105,116-117,487-499,552-570,640-660,737,748-816`
- Read: `backend/src/agents/graph/response_payload.py:75-150`
- Read: `backend/src/agents/graph/graph.py:91` (`build_graph`)
- Read: `eval/harness/context_recorder.py` — must keep working unchanged

## Implementation Steps

1. Set `SESSION_PERSISTENCE_ENABLED=false` in `eval/harness/__init__.py` (which already owns the
   pre-import `load_dotenv` fix for exactly this class of import-order bug) before `routes` can be
   imported, and assert the flag took effect.
2. Replace `e2e_eval.py`'s import block: drop `process_chat_turn` / `derive_stage` /
   `handle_frontend_hotel_selection` / `TurnResult`; import `_run_turn_via_graph` and
   `_get_graph_v2` from `src.api.routes`, and `derive_stage` /
   `hotel_options_from_task_results` from `src.agents.graph.response_payload`.
3. Rewrite `_replay_conversation` to call `_run_turn_via_graph(session_id, turn_text, record.language)`
   inside the existing `record_contexts()` block and the existing `time.perf_counter()` window, so
   the latency semantics Phase 3 aggregates stay "one user turn, agent side only".
4. Rewrite the `SELECT_FIRST_HOTEL_ACTION` branch: read options from
   `hotel_options_from_task_results(app.get_state(config).values)`, take the first id, and call
   `_run_turn_via_graph(..., extra_state={"selected_hotel_id": str(hotel_id)})`. Keep the existing
   loud `RuntimeError` when no options are pending — a silent skip would turn a broken flow into a
   passing conversation.
5. Read final state from the checkpointer after the last turn and compute
   `derive_stage(state, hotel_options, reply)`. Keep `harness_failure = reached_stage != expected_stage`
   and keep the exception branch setting `harness_failure = True` — `e2e_eval.py:128-129` documents
   why that default matters.
6. Re-derive `_turn_class` from the producing graph node. Determine the node per turn from the
   graph result (or from `PHASE_KEY_BY_NODE` / the updates stream) rather than guessing from reply
   text.
7. Verify `record_contexts()` still captures rows: run one conversation and assert the captured
   list is non-empty on a turn that must have hit retrieval.
8. Run `--layer e2e --limit 1 --no-llm-metrics` and confirm no ImportError, no write to the real
   session store (check the Supabase session table row count before/after), and a transcript is
   written.
9. Investigate the `finalized` records, decide, and write the adjudication note.
9a. Implement the mirror filter with the count assertions above, and add a unit test pinning that
    all 5 `hotel-crosslang-*` ids survive a default load — the regression this phase is most likely
    to cause is a later "simplify the filter" commit collapsing it to `language == "vi"`.
10. Stop at `--limit 1` (plus the `--limit 2` isolation check below). The stage-success rate across
    the whole conversation suite — the number Phase 6 compares against the 2026-08-11 report's 80% —
    needs a full pass and therefore waits for the user to ask for one. Do not run the suite here to
    "see where we stand"; a rewire is verified by one conversation completing correctly, not by a
    success percentage.

## Success Criteria

- [x] `eval/run_ragas.py --layer e2e --limit 1 --no-llm-metrics` completes with exit 0.
- [x] ~~Supabase session/transcript row counts are unchanged across the `--limit 2` run.~~
      **Amended 2026-08-18 (user decision).** Transcript/`chat_messages` counts *are*
      unchanged (466 → 466). `sessions` gains one **empty** row per conversation from a
      path `SESSION_PERSISTENCE_ENABLED` does not gate — see Results §3. Accepted and
      documented rather than patched, to keep latency fidelity.
- [x] `routes._persistence_enabled is False` is asserted, not assumed.
- [x] A turn that retrieved hotels has a non-empty captured context list (10 rows).
- [x] `hotel_grounding` produces a real ratio on at least one turn — `1.0` on the
      hotel-search turn of `conv-nhatrang-couple-3d`.
- [x] The `finalized` question is decided, and the decision plus its reasoning is in
      `eval/datasets/README.md`.
- [x] A default load yields 30 retrieval records and 9 conversations, asserted at load time.
- [x] All 5 `hotel-crosslang-*` ids survive a default load, pinned by a test.
- [x] `--include-en-mirrors` restores 44 and 10.
- [x] No record is deleted from either `.jsonl`.
- [x] No file under `backend/src/` is modified by this phase.

## Results (measured 2026-08-18)

### 1. The rewire works, and it drives production's own turn path

`--layer e2e --limit 1 --no-llm-metrics`: 1 conversation, 3 turns, reached its expected
stage, 0 errors. `conv-nhatrang-couple-3d` end to end:

| Turn | Worker | Class | Contexts | Grounding | Latency |
|---|---|---|---|---|---|
| intake question | — | generated | 0 | — | 8.5s |
| hotel search | `hotel_node` | template | 10 | **1.0** | 13.0s |
| hotel pick → itinerary | `hotel_node` | template | yes | — | 13.8s |

`record_contexts()` still captures unchanged — `_execute_rpc` was untouched by the
cutover, and 10 real rows arrived on the search turn. Grounding `1.0` means all 5
options shown to the user were IDs a real retrieval call returned.

**Turns are driven through `routes._run_turn_via_graph`** and the answer is read off the
returned `PlannerChatResponse` (`.reply`, `.stage`, `.hotel_options`) — the exact object
the HTTP API serializes. The harness therefore cannot disagree with production about what
a turn did. `derive_stage` is not called harness-side at all; `respond` already ran it to
build that response, and re-deriving would have been a second implementation of the thing
`response_payload.py` exists to prevent.

**Deviation from the plan, deliberate:** the hotel-pick turn reads its option list from
the previous turn's `PlannerChatResponse.hotel_options` rather than calling
`hotel_options_from_task_results(state)` directly. Same data — `respond` builds that field
with that function — but it is what the frontend actually holds when the user clicks a
card, and it removes one more private-internal coupling.

`_turn_class` now keys off `task_results[-1]["worker"]`, which `load_context` resets to
`[]` every turn, so it never reads a stale entry. Mapping: `hotel_node`/`booking_node`/
`budget_check` → template, `itinerary_node` → mixed, no worker → generated. `TurnRecord.tool`
became `.worker`; `hotel_pick` and `asked_question` are now explicit fields rather than
things `transcripts.py` re-inferred from a tool name.

### 2. Cross-conversation isolation holds

`--limit 2`, one compiled graph shared by both, separated only by `thread_id`:

```
thread ragas-eval-conv-nhatrang-couple-3d: 6 messages, trip_data present
thread ragas-eval-conv-danang-family-3d:   6 messages, trip_data present
SESSION IDS DISTINCT: True
NO TRANSCRIPT BLEED:  True   (conv 1's first turn absent from conv 2's messages)
```

Both reached `planned`.

### 3. An eval run does write one row to the real Supabase — measured, not gated

`routes._persistence_enabled is False` is asserted at import (`e2e_eval.py` raises if it
is not), and it holds: `chat_messages` was **466 before and after** the `--limit 2` run,
and no transcript row was written.

But `sessions` went **130 → 131**. The writer is
`trip_planner._persist_itinerary_metadata` (`trip_planner.py:406-425`), which upserts
`{"session_id": ...}` as an FK prerequisite before persisting the itinerary bundle. It is
on the itinerary path, not the session-persistence path, so `SESSION_PERSISTENCE_ENABLED`
does not reach it.

Measured blast radius: **one empty row per conversation** (`session_id` only, prefixed
`ragas-eval-`), idempotent on re-run. `itineraries` rows written: **0**. So a full
9-conversation run leaves 9 empty prefixed rows, once, and reruns add none.

**User decision 2026-08-18: accept and document.** Patching it out (a `context_recorder`-
style wrapper) would stop the eval exercising the `persisting` step, and Phase 3's
itinerary-turn latency would then understate production by however long that write takes.
Phase 5 carries this in the report's caveats.

### 4. The `finalized` adjudication — decided, and it uncovered two defects

Full reasoning and evidence: `eval/datasets/README.md`, section
"`expected_stage: finalized` adjudication (2026-08-18)".

**The stage is genuinely gone by design.** `ChatStage` is
`intake | hotel_options | planned | error`; `respond.py`'s docstring states that
`finalized`/`modified` were dropped because their only producer was the deleted
`process_chat_turn` cascade. Both records re-pointed to `planned`. `dataset_loader`'s
`_VALID_STAGE` was narrowed to match `ChatStage`, so a third record cannot declare an
unachievable stage.

**Both conversations were replayed before the edit, and neither works.** These are filed,
not fixed — changing agent behavior is a plan non-goal:

- **`conv-hcm-finalize-4d` — the finalize request is not understood.** Turns 1-3 work
  (intake → 5 hotels → hotel picked → 2-day itinerary). Turn 4, `"Chốt lịch trình"`,
  routes to `itinerary_node` and fails: log `itinerary_node: malformed task — lock_days
  received an empty days_to_lock`, reply *"Mình chưa hiểu yêu cầu này"*, itinerary status
  still `Draft`. **The stage check passes anyway**, because turn 3's itinerary is still
  present — so re-pointing to `planned` makes this record green while the behavior under
  it is broken. Its `"finalize confirmation message is shown"` assertion is kept for
  exactly that reason: it is the only part of the record that still says what should have
  happened.
- **`conv-hue-finalize-2d` — a 1-day trip cannot be created at all.** Turn 1 is rejected
  during intake: *"Dữ liệu chưa hợp lệ: end date must be after the trip's start date"*.
  `"trong N ngày"` resolves to an end date `N-1` days after the start, so `N=1` yields
  `end == start`. The same `N-1` arithmetic shows on the passing conversations — `"2
  ngày"` builds a *"lịch trình 1 ngày"*, `"3 ngày"` a *"lịch trình 2 ngày"*. Whether that
  reading of `ngày` is right is a product question; `N=1` failing outright is not. The
  record keeps its `1 ngày` phrasing — rewriting it to `2 ngày` would make the
  conversation pass and delete the only evidence of this defect in the suite.

### 5. The Vietnamese-only filter

44 → 30 retrieval, 10 → 9 conversations, asserted at load time. All 5 `hotel-crosslang-*`
probes survive, including the two labelled `en`, because `_is_en_mirror` keys off **pair
partnership, not the `language` field** — the 5 probes each hold a `pair_id` no other
record uses. `--include-en-mirrors` restores 44/10, and the flag is recorded in the run's
`run_metadata` so two reports produced under different settings cannot be silently
compared.

Pinned by `backend/tests/test_golden_dataset_filter.py` (6 tests), including one that
asserts every removed record genuinely has a `vi` partner — the failure mode a
`language == "vi"` "simplification" would produce.

### 6. Environment

Importing `src.api.routes` in the eval venv needed `email-validator` (pydantic `EmailStr`
in `models/schemas.py`) and `resend` (`services/email_service.py`); both added to
`requirements-eval.txt` under the existing "needed to import backend/... directly"
convention. Import takes 1.5s and opens no connections.

### 7. Verification

- `--layer e2e --limit 1 --no-llm-metrics`: exit 0.
- `--layer retrieval --limit 1 --no-llm-metrics`, with and without `--include-en-mirrors`:
  exit 0 both ways.
- Backend suite: **839 passed, 7 failed** — all 7 pre-existing and unrelated
  (`test_supabase_search`, `test_room_availability_schema`, `test_trip_modification` read
  migration `.sql` files that are not in the repo, e.g.
  `20260817_add_hotel_search_eligibility_indexes.sql`). No `backend/src/` file was touched
  by this phase.
- ruff on `eval/`: 6 findings, all pre-existing (`git show HEAD:eval/harness/e2e_eval.py`
  carries the same `I001`). No new ones.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Importing `src.api.routes` pulls in FastAPI, auth, and module-level Supabase clients, and may fail or connect at import time | Try the import first, in isolation, as step 1. If import side effects are unacceptable, fall back to a harness driver built on `build_graph` + `app.invoke` and accept the fidelity loss — but only after measuring that the interrupt/resume path is not exercised by any golden conversation |
| Depending on private `_`-prefixed functions breaks silently on the next refactor | The alternative (a harness copy) breaks silently too, and worse — divergence produces wrong numbers instead of an ImportError. An import error is the loud failure mode; prefer it. Document the coupling in the module docstring |
| Editing `expected_stage` to match observed behavior turns the golden set into a mirror of current behavior and it stops being able to fail | Step 9 requires a written adjudication before any dataset edit — the same bar `eval/datasets/README.md` already applies to the retrieval set's disputed records |
| The mirror filter over-matches and silently removes the 2 EN-sentence crosslang probes, erasing half of BR-10's evidence | The predicate keys off `pair_id` partnership rather than the `language` field, load-time assertions pin the counts, and step 9a's test names the 5 probe ids explicitly. This is the specific bug the whole filter design is shaped around |
| Scores appear to improve simply because 14 records were removed | Phase 6's findings must compare like with like — the VI subset of the 2026-08-11 run, never its blended average |
| The graph plane is mid-migration: `260812-0927` and `260816-2205` are both pending and both touch it | Those plans change nodes and contracts, not `_run_turn_via_graph`'s signature. If they land first, re-verify step 2's imports; the coupling is one function, not a surface |
| One cached graph app across conversations leaks state between them via a shared checkpointer | Each conversation uses a unique `thread_id` (`ragas-eval-<conv-id>`), which is the checkpointer's isolation unit. Verify with `--limit 2`, asserting the second conversation does not start with the first's `trip_data`. This is the one place this phase exceeds `--limit 1`, because cross-conversation isolation cannot be shown with a single conversation |
