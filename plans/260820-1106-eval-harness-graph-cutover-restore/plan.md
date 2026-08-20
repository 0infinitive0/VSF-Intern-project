---
title: "Eval harness graph-cutover restore"
description: "Bring the RAGAS eval harness back to life after the LangGraph cutover deleted the turn-execution API it was built on, and rebuild a baseline that measures the graph plane actually in production."
status: pending
priority: P1
branch: "main"
tags: [eval, ragas, langgraph, regression, harness]
blockedBy: []
blocks: []
effort: "3-4d"
created: 2026-08-20
---

# Eval harness graph-cutover restore

## Overview

The LangGraph cutover (`260812-0927-...`, phase 11) deleted `session.py`'s turn-execution
cascade and every caller with it. `eval/` was a caller. Nobody re-ran it, so the breakage
landed silently on `main` and has been there since.

The harness is not "a bit stale" — it does not start. `eval/run_ragas.py:16` imports
`e2e_eval` at module scope, `e2e_eval.py:18` imports three symbols that no longer exist, so
the entire CLI dies on import, including `--help` and `--layer retrieval`. Layer 1's own code
is fine; it is held hostage by Layer 2's import.

This plan restores both layers against the graph plane, and rebuilds the baseline. It does not
tune retrieval and does not add a CI gate — both were non-goals of the original harness plan
and stay non-goals here.

## Established facts (verified 2026-08-20, not assumed)

- **Three of four symbols `e2e_eval.py:18` imports are gone.** `create_chat_session` survives
  (`session.py:224`); `derive_stage`, `handle_frontend_hotel_selection` and `process_chat_turn`
  do not. Verified by real import, not by grep:
  `ImportError: cannot import name 'derive_stage' from 'src.agents.session'`.
  `session.py:38-44` documents the deletion in its own words: *"That cascade was deleted with
  the graph cutover and took every caller with it."*
- **The blast radius is the whole CLI, not just Layer 2.** `run_ragas.py:16` is a module-scope
  import of `e2e_eval`, so `run_ragas.py --help` raises the same `ImportError`.
- **Layer 1 is code-compatible and runs.** All four `supabase_search` symbols
  `retrieval_eval.py:23` imports still exist with signatures that accept the kwargs used. Ran
  live against the golden set: the code path executes and fails only on
  `ConnectionError: Failed to connect to Ollama` — environment (local `bge-m3` embeddings not
  running), not API drift.
- **`PlannerChatResponse` already carries everything Layer 2 needs**, so the new harness is
  *smaller* than the old one: `stage` is pre-derived (no `derive_stage` call needed),
  `hotel_options[].id` (`schemas.py:246`) replaces reading `session.pending_hotel_selection`,
  and `reply` feeds faithfulness. Fields verified at `schemas.py:550-570`.
- **`context_recorder`'s founding assumption is dead.** The original plan recorded as an
  established fact that *"every Supabase vector search funnels through
  `supabase_search._execute_rpc`"*. It no longer does: `itinerary_store.py:163` calls
  `self._client.rpc("match_itineraries", params)` directly with `query_embedding` /
  `match_threshold` — a real vector search added by the itinerary-template feature (`b288843`),
  invisible to a monkeypatch on `_execute_rpc`.
- **A naive migration would write eval conversations into the real Supabase session store.**
  `backend/.env` sets `SESSION_PERSISTENCE_ENABLED=true`, the harness loads `backend/.env`, and
  `_persist_turn` (`routes.py:1006`) is gated on exactly that setting read at import time
  (`routes.py:129`). The old harness avoided this structurally by passing no `persist_hook`;
  the replacement must be equally structural, not env-dependent.
- **Graph state is already safe in a headless run.** `_get_graph_v2` (`routes.py:773`) falls
  back to a process-local `MemorySaver` when `registry.checkpointer` is `None`, which is the
  case outside FastAPI lifespan. `checkpointer_backend` also defaults to `"memory"`.
- **The eval venv can already import the graph and HTTP layers.** Verified:
  `src.agents.graph.response_payload`, `src.api.routes` and `src.models.schemas` all import
  cleanly under `eval/.venv-eval` (it has fastapi 0.141.1, langgraph 1.2.10, supabase 2.31.0).
  Feasibility is not a risk here.
- **The state-patch harness is unaffected and current.** `harness/score_state_patches.py`
  imports cleanly, `--help` works, last run 2026-08-15 (micro-F1 0.929). Do not touch it.
- **The old baseline cannot be reused.** `eval/results/baseline.json` (2026-08-11,
  `dataset_hash 28c553772bf69468`) was measured against the plane that phase 11 deleted. Even a
  perfectly migrated harness cannot legitimately `--compare-baseline` against it.

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | Restore Layer 1 **and** Layer 2 | Layer 2 is the layer that earned its keep — it caught the `max_price="2026"` price-hallucination bug that every unit test missed, because the suite fakes `recommend_hotels` |
| Graph entrypoint | Extract a turn-runner module; `routes.py` delegates to it | Eval must not import the HTTP layer to run a conversation. Calling `routes._run_turn_via_graph` works today but re-creates exactly the coupling that made the cutover break eval silently |
| Store isolation | Inject the persist hook; eval passes `None` | Structural, not configuration. Relying on `SESSION_PERSISTENCE_ENABLED` means one wrong env read writes eval junk into the real session store |
| CI gate | Still out of scope | Original plan's non-goal, unchanged. Thresholds stay proposals |
| Retrieval tuning | Still out of scope | This plan measures. The 11 adjudicated retriever gaps stay findings |
| Old baseline | Superseded, marked stale, not deleted | It is the historical record of the pre-graph plane; deleting it destroys evidence |

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | `run_ragas.py` runs again — both layers, against the graph plane | P1 |
| 2 | Eval never writes to the real session store, by construction rather than by config | P1 |
| 3 | Retrieved contexts are captured from every vector-search path, including `match_itineraries` | P1 |
| 4 | A fresh baseline exists that measures the plane actually in production | P1 |
| 5 | The harness stops being invisible to a future cutover | P2 |
| 6 | `backend/requirements.txt` unchanged | P2 |

## Non-goals

- No CI gate on eval metrics. Unchanged from the original plan: LLM-judge metrics are slow,
  paid and variable; the non-LLM thresholds stay written-down proposals.
- No retrieval tuning. The 11 adjudicated zero-recall records stay findings for separate work.
- No new golden records. Same 44 retrieval queries, same 10 conversations — changing the
  dataset in the same pass that changes the harness makes the new baseline uninterpretable.
- No revival of the two dropped conversations (`conv-danang-edit-cheaper`,
  `conv-crosslang-hyatt-danang`). They were dropped at the owner's direction; out of scope.
- No change to what the graph *does*. Phase 1 is a pure move-and-delegate refactor; if any
  conversation behaves differently afterwards, that is a bug in the refactor.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Extract the turn runner](./phase-01-extract-turn-runner.md) | Pending |
| 2 | [Unblock Layer 1](./phase-02-unblock-retrieval-layer.md) | Pending |
| 3 | [Rebuild Layer 2 on the graph](./phase-03-rebuild-e2e-on-graph.md) | Pending |
| 4 | [Widen context capture](./phase-04-widen-context-capture.md) | Pending |
| 5 | [Rebaseline and document](./phase-05-rebaseline-and-document.md) | Pending |

Phase 2 is independent of 1 and can land first — it is a two-line change that gets retrieval
running again the same day. Phase 3 depends on 1. Phase 4 is independent of 3 but must land
before 5, or the new baseline bakes in the blind spot.

## Success Criteria

- [ ] `eval/.venv-eval/bin/python eval/run_ragas.py --help` exits 0.
- [ ] `--layer retrieval` completes on the full 44-record golden set with 0 harness errors
      (requires a running Ollama for `bge-m3`).
- [ ] `--layer e2e` replays all 10 scripted conversations through the graph with 0 harness
      errors, and reaches the expected stage on at least the 8 that reached it pre-cutover.
      Fewer than 8 is a finding to investigate, not a number to accept.
- [ ] A full eval run performs **zero writes** to the Supabase `sessions` table, proven by a
      row-count check before and after, not by reading the code.
- [ ] `context_recorder` captures contexts from `match_itineraries` as well as
      `_execute_rpc`, proven by a conversation that reaches itinerary reuse.
- [ ] `backend/` behaviour is unchanged by phase 1: `make test` green, and the extracted
      functions are byte-identical in body to the originals modulo injected parameters.
- [ ] A new `eval/results/baseline.json` is committed, measured on the graph plane, with the
      superseded one preserved and labelled.
- [ ] `backend/requirements.txt` byte-identical to its pre-plan state.
- [ ] The old Ragas plan's frontmatter no longer claims `pending` for completed work.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Phase 1 refactor changes graph behaviour while "just moving code" | Every later number is measured against a plane that differs from production | Move bodies verbatim; the only edits allowed are parameters replacing module globals. `make test` green before phase 3 starts |
| Eval writes into the real `sessions` table | Production data polluted with `ragas-eval-` rows | Injected persist hook defaults to `None`; eval never passes one. Verified by a row-count check, which is an explicit success criterion |
| New baseline is worse than the old one and it is unclear whether the graph regressed or the harness changed | Cannot tell a real regression from a measurement change | Phase 5 reports the new numbers as a *new* baseline, never as a delta against 2026-08-11, and states plainly that the two are not comparable |
| `match_itineraries` capture changes retrieval-context sets, shifting Layer 2 scores | Phase 4 silently moves numbers phase 3 just established | Land phase 4 before the baseline run (phase 5), never after |
| Conversation dates pinned to 2026-07-01..07 no longer have room availability | Conversations fail for data reasons and look like regressions | Phase 3 re-verifies the availability window live before blaming the harness. `validate_stay_dates` does not reject past dates, so this is a data question, not a validation one |
| The harness breaks again at the next refactor | Same silent failure, later | Phase 2 adds an import smoke test to `make test` — cheap, no LLM calls, fails loudly at refactor time |

## Relationship to other plans

Repairs the harness delivered by
[`260807-1400-ragas-rag-evaluation-harness`](../260807-1400-ragas-rag-evaluation-harness/plan.md)
and supersedes its baseline. That plan's frontmatter still says `pending` across `plan.md` and
all five phase files while its body marks every phase Completed; phase 5 here syncs it.

Cleans up after
[`260812-0927-langgraph-orchestration-state-patch-and-interrupts`](../260812-0927-langgraph-orchestration-state-patch-and-interrupts/plan.md)
phase 11, whose own acceptance list still carries an unticked
`[ ] eval/ end-to-end ≥ the Phase 10 report and ≥ committed baseline` — the step that, had it
run, would have caught this. Per the owner's direction that phase file is left as-is; this plan
is the record of the outstanding work.

**A dangling reference worth knowing about.** The old Ragas plan names
`260723-1015-v-ota-poc-master-roadmap` as the consumer of its evidence (its `blocks:`
frontmatter and a relative link in its body). That plan directory no longer exists — it was
removed in `e069e3f chore: remove old plans`. So the M2/M3 gate consumer this harness was
built to feed is currently unowned, and the link in the old plan 404s. This plan does not
resurrect the roadmap; it restores the harness. Whoever owns the KPI gates should be told the
evidence machinery works again — and that the roadmap's Open Question 4 (KPI thresholds unset)
went away with its plan rather than being answered.

## Open Questions

1. Does the corpus still have room availability inside 2026-07-01..07? Today is 2026-08-20 and
   that window is now in the past. Phase 3 verifies live before interpreting any conversation
   failure.
2. Should `turn_runner.py` live under `src/agents/graph/` or a neutral `src/services/`? Assumed
   `src/agents/graph/` — it is graph orchestration and every function it takes already deals in
   graph state.
3. Is a per-run throwaway `MemorySaver` right for eval, or should conversations be replayable
   from a persisted checkpoint afterwards? Assumed throwaway; transcripts already serve
   inspection.

<!-- slug: eval-harness-graph-cutover-restore -->
