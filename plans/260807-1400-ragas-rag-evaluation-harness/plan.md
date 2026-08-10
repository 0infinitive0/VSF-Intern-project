---
title: "RAGAS RAG evaluation harness"
description: "Measure retrieval quality and answer grounding of the trip-planner RAG pipeline with RAGAS, in an isolated eval environment, producing repeatable evidence for the M2/M3 gates."
status: pending
priority: P1
branch: "main"
tags: [eval, ragas, rag, retrieval, m2, m3]
blockedBy: []
blocks: [260723-1015-v-ota-poc-master-roadmap]
effort: "4.5-6d"
created: 2026-08-07
---

# RAGAS RAG evaluation harness

## Overview

The system retrieves hotels and attractions by semantic search and then has an LLM agent
turn them into an itinerary. Nothing today measures whether retrieval returns the *right*
places, or whether the agent's prose stays faithful to what was retrieved. Master-roadmap
phases 6 and 8 both gate on evidence of exactly that and have no harness to produce it.

This plan builds that harness with RAGAS in two layers:

- **Layer 1 — retrieval.** `search_hotels_with_rooms` / `search_attractions` scored against a
  hand-built golden set of query → expected place IDs.
- **Layer 2 — end-to-end.** `process_chat_turn` replies scored for faithfulness and relevancy
  against the contexts that were actually retrieved during that turn.

Judge is OpenAI `gpt-4o-mini` (`OPENAI_API_KEY` already in `backend/.env`), with disk caching so
re-runs are near-free. The harness lives in `eval/` with its own virtualenv so it never touches
the backend runtime's dependency set.

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Scope | Retrieval **and** end-to-end | Retrieval-only can't catch a hallucinated hotel; e2e-only can't tell you *why* an answer is wrong |
| Judge LLM | OpenAI `gpt-4o-mini`, `temperature=0` | Key already present; local `llama3.1` fails RAGAS's structured-output prompts and yields NaN/noisy scores unusable as gate evidence |
| Delivery | CLI script → `eval/results/`, isolated venv | Reproducible artifact for M3; venv isolation protects the app's dependency tree |
| RAGAS version | `ragas==0.3.9` pinned | Resolves clean against langchain-core 1.5.x / pydantic 2.13.x (verified by dry-run); `evaluate()` is the stable documented API there, whereas 0.4.x deprecates it in favour of `@experiment` |

## Established facts (verified 2026-08-07, not assumed)

- **`ragas 0.1.22` is installed in the pyenv global env and is broken.** `import ragas` raises
  `ModuleNotFoundError: No module named 'langchain_core.pydantic_v1'` — that module was removed in
  langchain-core 1.x, and ragas 0.1.22 drags in `langchain-community 0.2.19` which still imports it.
  Phase 1 must not build on this install.
- **A clean-venv dry-run of `ragas==0.3.9` resolves without conflict**, landing on
  langchain-core 1.5.3, langchain-community 0.4.2, pydantic 2.13.4 — matching the app's own pins.
  The resolution is safe; the isolation is about not adding `datasets`/`pandas`/`pyarrow`/
  `langchain-community` to the backend image.
- **Every Supabase vector search funnels through one function**: `supabase_search._execute_rpc`
  (`backend/src/services/supabase_search.py:91`), already decorated
  `@traceable(name="supabase_rpc", run_type="retriever")`. This is the single interception point
  for capturing retrieved contexts during an e2e turn.
- **`TurnResult` carries only `text` and `tool`** (`backend/src/agents/session.py:64`). It does
  *not* expose retrieved contexts, so Layer 2 cannot read them off the return value — hence the
  recorder in Phase 4.
- **`eval/fixtures/vector_bench/hotels.json` holds 1,103 hotels** with `hotel_id`, `name`,
  `destination_id`, `star_rating` — the seed for building golden expectations without re-querying
  the corpus by hand.
- **`eval/` is otherwise empty** apart from those fixtures. `eval/results/` is already the path
  roadmap phases 6 and 8 name for their reports.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | A single command produces RAGAS scores for retrieval and e2e answers | P1 |
| 2 | Scores are reproducible: pinned deps, fixed judge, cached, versioned dataset | P1 |
| 3 | A committed baseline exists so later retrieval changes are measurable as regressions | P1 |
| 4 | Bilingual VI/EN coverage, per BR-10's cross-language retrieval requirement | P1 |
| 5 | Backend runtime dependencies are unchanged | P2 |

## Non-goals

- No CI gate. LLM-judge metrics are slow, paid, and flaky in CI; a threshold gate is only
  sensible over the non-LLM metrics and is deferred until a baseline exists (Phase 5 records
  candidate thresholds, it does not wire them into CI).
- No RAGAS synthetic test-set generation. Synthetic queries over this corpus would score the
  generator's idea of a good query, not real user behaviour.
- No retrieval tuning. This plan *measures*. Acting on the numbers is separate work.
- No changes to `supabase_search.py`, `session.py`, or any other production module. The harness
  observes from outside.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Isolated eval environment](./phase-01-isolated-eval-environment.md) | Pending |
| 2 | [Golden dataset construction](./phase-02-golden-dataset-construction.md) | Pending |
| 3 | [Retrieval layer evaluation](./phase-03-retrieval-layer-evaluation.md) | Pending |
| 4 | [End-to-end chat turn evaluation](./phase-04-end-to-end-chat-turn-evaluation.md) | Pending |
| 5 | [Report, baseline and thresholds](./phase-05-report-baseline-and-thresholds.md) | Pending |

Phase 2 is the long pole and the one that decides whether the numbers mean anything. Phases 3
and 4 are independent of each other once 2 is done.

## Target layout

```
eval/
  .venv-eval/                       # gitignored
  requirements-eval.txt             # ragas==0.3.9, rapidfuzz, python-dotenv
  README.md                         # how to run, what the numbers mean
  datasets/
    golden-retrieval.jsonl          # Layer 1: query -> expected place IDs
    golden-conversations.jsonl      # Layer 2: scripted multi-turn conversations
  harness/
    judge.py                        # RAGAS LLM + embeddings wrappers, disk cache
    context_recorder.py             # captures _execute_rpc results per turn
    retrieval_eval.py               # Layer 1 runner
    e2e_eval.py                     # Layer 2 runner
    report.py                       # EvaluationResult -> markdown + json
  run_ragas.py                      # CLI entry: --layer retrieval|e2e|all
  results/
    ragas-<YYYYMMDD-HHMM>.json      # raw per-sample scores
    ragas-<YYYYMMDD-HHMM>.md        # human-readable report
    baseline.json                   # committed reference run
```

## Success Criteria

- [ ] `make eval-ragas` runs both layers end to end and writes a timestamped report pair to `eval/results/`.
- [ ] Retrieval scored on ≥ 40 golden records covering VI and EN, including ≥ 4 cross-language cases.
- [ ] End-to-end scored on ≥ 10 scripted conversations reaching a hotel recommendation or a finished itinerary.
- [ ] A second run over an unchanged dataset reproduces the previous scores within ±0.02 on LLM metrics and exactly on non-LLM metrics.
- [ ] `eval/results/baseline.json` is committed and `eval/README.md` explains how to compare against it.
- [ ] `backend/requirements.txt` is byte-identical to its pre-plan state.
- [ ] Judge cost for a full uncached run is measured and written into the report.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Golden set encodes the current retriever's behaviour instead of user intent | Scores look good permanently; the harness measures nothing | Phase 2 authors expectations from the corpus and from BRD scenarios **before** running the retriever, and records disagreements rather than silently adopting retriever output |
| Judge cost/latency higher than expected | Runs become too expensive to repeat | `DiskCacheBackend` on by default; `--layer` and `--limit` flags; non-LLM metrics always computed and free |
| Layer 2 is dominated by templated output from `trip_formatter.py` | Faithfulness pinned near 1.0, no signal | Phase 4 scores the LLM-authored segments separately from template-rendered ones, and says so in the report |
| E2E runs are slow and non-deterministic (real LLM agent, real Supabase) | Flaky, long runs | Fixed `temperature=0`, scripted turn sequences, small N, per-conversation transcript persisted for inspection |
| Vietnamese diacritics degrade the judge's grading | Scores biased against VI | Phase 5 reports per-language breakdown; a large VI/EN gap is a finding, not a footnote |
| `.env` secrets leak into committed results | Credential exposure | Report writer serialises scores and query text only; never config, keys, or raw RPC params |

## Relationship to other plans

Supplies the measurement machinery that
[`260723-1015-v-ota-poc-master-roadmap`](../260723-1015-v-ota-poc-master-roadmap/plan.md)
phase 6 (M2 gate) and phase 8 (M3 evaluation) both assume exists. Those phases own the KPI
thresholds and the go/no-go call; this plan owns the harness that feeds them. Roadmap Open
Question 4 (KPI thresholds unset) remains open and is **not** resolved here — Phase 5 proposes
candidate thresholds from the observed baseline and flags them as proposals.

## Open Questions

1. Which destinations should the golden set cover? Corpus has 1,103 hotels across many
   `destination_id`s; the BRD scenarios lean on Nha Trang / Đà Nẵng / HCM. Phase 2 assumes those
   three plus one long-tail destination unless told otherwise.
2. Is there a human-labelled notion of a "correct" hotel for a query, or is the golden set the
   first such artefact? Assumed the latter — hence the emphasis on authoring before measuring.
3. Should attraction retrieval be weighted equally with hotel retrieval? Assumed yes; hotels
   drive booking handoff but attractions drive itinerary quality.

<!-- slug: ragas-rag-evaluation-harness -->
