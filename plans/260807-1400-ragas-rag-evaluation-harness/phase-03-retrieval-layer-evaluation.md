---
phase: 3
title: "Retrieval layer evaluation"
status: pending
priority: P1
effort: "1d"
dependencies: [1, 2]
---

# Phase 3: Retrieval layer evaluation

## Overview

Run the golden retrieval set through `search_hotels_with_rooms` and `search_attractions`, convert
results into RAGAS samples, and score them with both deterministic ID-matching metrics and LLM-judged
relevance metrics.

## Requirements

- Functional: every retrieval record in the golden set is executed and scored.
- Functional: both non-LLM (free, exact) and LLM (semantic) metrics are computed and reported apart.
- Functional: per-language and per-search-type (hotels vs attractions) breakdowns.
- Functional: `--limit N` and `--layer retrieval` for cheap iteration.
- Non-functional: `supabase_search.py` is not modified. The harness calls it as a library.
- Non-functional: raw per-sample scores persisted, not just aggregates — an average hides which
  query failed, and the failing query is the useful part.

## Architecture

### Two metric families, reported separately

Averaging a deterministic ID-match score with an LLM's opinion produces a number that means neither
thing. They answer different questions and stay in different columns.

**Non-LLM (deterministic, free, CI-viable):**

- `NonLLMContextPrecisionWithReference` — of what was retrieved, how much was expected?
- `NonLLMContextRecall` — of what was expected, how much was retrieved?

These compare strings via `rapidfuzz`. Feeding raw descriptions would make fuzzy matching
meaningless, so contexts are rendered as **canonical ID-anchored strings**, making the comparison
effectively an exact ID match:

```python
def as_context(place: dict) -> str:
    """Stable, ID-anchored rendering so non-LLM matching is exact, not fuzzy."""
    return f"[{place['id']}] {place.get('name', '')}"
```

`reference_contexts` are built the same way from `expected_ids` + the fixture's names.

**LLM-judged (semantic, paid):**

- `LLMContextPrecisionWithoutReference` — does the retrieved place actually answer the query?
- `ContextRelevance` — how relevant is the retrieved set overall?

These catch the case the ID match cannot: a hotel absent from `expected_ids` that is nevertheless a
perfectly good answer. That is precisely what `acceptable_ids` was introduced for, and the LLM
metric is the cross-check on whether that list is complete.

### Sample construction

```python
sample = SingleTurnSample(
    user_input=record["query"],
    retrieved_contexts=[as_context(p) for p in results],
    reference_contexts=[as_context(p) for p in expected_places],
    reference=record.get("rationale", ""),
)
```

`response` is deliberately absent — there is no generated answer at this layer, and metrics
requiring one are not in this phase's list.

### Calling the retriever

```python
from src.services.supabase_search import search_attractions, search_hotels_with_rooms

results = search_hotels_with_rooms(
    query=record["query"],
    match_count=10,
    use_llm_filter=True,   # part of the pipeline under test, not a harness detail
    model=None,
)
```

`use_llm_filter=True` is intentional. `extract_search_filters`
(`backend/src/services/supabase_search.py:107`) is a real stage of production retrieval — turning it
off would measure a pipeline that does not exist. Record the extracted filters per query so a bad
score can be attributed to filter extraction rather than to embeddings.

### Cost control

Non-LLM metrics run always. LLM metrics run under `--llm-metrics` (default on for full runs, off
under `--limit`). Judge caching from Phase 1 applies, so re-scoring an unchanged dataset is free.

## Related Code Files

- Create: `eval/harness/retrieval_eval.py`
- Create: `eval/harness/context_format.py` — `as_context`, shared with Phase 4
- Create: `eval/run_ragas.py` — CLI entry (`--layer`, `--limit`, `--llm-metrics/--no-llm-metrics`, `--out`)
- Modify: `eval/harness/dataset_loader.py` — retrieval-record accessors
- Read only: `backend/src/services/supabase_search.py`
- Read only: `eval/datasets/golden-retrieval.jsonl`

## Implementation Steps

1. Write `context_format.py` with `as_context` plus its inverse (parse an ID back out of a context
   string) — the report needs to name which hotel was missed.
2. Write `retrieval_eval.py`: load records → dispatch on `search` field to the right service
   function → build `SingleTurnSample`s → assemble an `EvaluationDataset`.
3. Capture per-query diagnostics alongside scores: extracted filters, resolved `destination_id`,
   result count, wall-clock latency. Attribution matters more than the score itself.
4. Score with the non-LLM pair first — no judge, no cost, fast. Confirm scores are sane before
   spending anything: a query whose `expected_ids` all appear must score recall 1.0. If it does not,
   the context rendering is broken, not the retriever.
5. Add the LLM metric pair behind `--llm-metrics`, using the Phase 1 judge.
6. Write `run_ragas.py` as the CLI front end, defaulting to `--layer all` but supporting
   `--layer retrieval` alone.
7. Persist raw per-sample results to `eval/results/ragas-<ts>.json` — every score, every diagnostic,
   the golden record `id`, and the retrieved ID list.
8. Run the full retrieval set. Record wall-clock time and judge token spend.
9. Inspect the 5 worst-scoring queries by hand. Classify each: bad expectation, bad filter
   extraction, bad embedding match, or thin corpus. Write the classification into the phase's
   completion notes — this is what Phase 5's report is built on.

## Success Criteria

- [ ] All golden retrieval records execute without unhandled exceptions.
- [ ] Non-LLM precision and recall are produced for every record.
- [ ] LLM precision and relevance produced under `--llm-metrics`.
- [ ] Scores broken down by language, by search type, and by `pair_id` for cross-language cases.
- [ ] A deliberately perfect record (expected == retrieved) scores exactly 1.0 on both non-LLM
      metrics — the harness's own correctness check.
- [ ] Two consecutive runs produce byte-identical non-LLM scores.
- [ ] `eval/results/ragas-<ts>.json` contains per-sample rows, not only aggregates.
- [ ] The 5 worst queries are classified by cause.
- [ ] `git diff backend/src/services/supabase_search.py` is empty.

## Risk Assessment

- **Fuzzy matching degrading into false positives.** Two hotels with similar names could partially
  match on `rapidfuzz`. The `[uuid]` prefix dominates the string and makes near-matches score low;
  step 4's sanity check is what proves the rendering behaves as intended.
- **`use_llm_filter=True` adds a per-query LLM call** through `get_fast_llm`, so the "free" non-LLM
  path is not actually free — the *retrieval* costs money even when the *metrics* don't. Report
  retrieval-side and judge-side costs separately.
- **Live Supabase dependency** makes runs non-hermetic; corpus changes shift scores. Record corpus
  row counts in the report so a score change can be attributed to data drift.
- **`match_threshold` defaults differ** between hotels (0.35) and attractions (0.4). Use the
  production defaults, state them in the report, and do not tune them here — tuning is out of scope.
- **`extract_search_filters` failures fall back silently** to `{"clean_query": query}` after logging
  a warning (`supabase_search.py:151`). Surface that fallback as a diagnostic flag; otherwise a
  filter-extraction outage reads as an embedding-quality problem.
