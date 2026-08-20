---
phase: 3
title: "Latency percentiles"
status: complete
priority: P1
effort: "0.5d"
dependencies: [1]
---

# Phase 3: Latency percentiles

## Overview

Latency is already recorded per retrieval query (`retrieval_eval.py:54-67`) and per e2e turn
(`e2e_eval.py:95-105`), but `report.py:204-205` only ever sums it. Add P50/P95/P99 — and add the
judge-side latency that is currently not measured at all, which `report.py:217` admits in its own
run-metadata line.

## Requirements

- Functional: every latency family reports `n`, `p50`, `p95`, `p99`, `min`, `max`, `mean`, `sum`.
- Functional: latency families are kept separate, never pooled — retrieval search, judge scoring,
  and e2e agent turns have different distributions and pooling them produces a number that
  describes nothing.
- Functional: per-group breakdowns match the existing metric breakdowns (retrieval by
  `search` and `language`; e2e by `turn_class`).
- Non-functional: percentile computation is deterministic and its interpolation method is stated,
  because P99 over n=30 is a nearly-meaningless number if the method is left implicit.
- Non-functional: latency of a run in which the judge cache is warm is labelled as such — a cached
  judge scores in ~0.01-0.08s vs ~3s cold (`eval/README.md:91-96`), so an unlabelled judge P50 is
  a measurement of the cache, not the judge.

## Architecture

**A shared aggregation helper.** One `eval/harness/stats.py` with `percentile_summary(values) -> dict`,
used by every family. The alternative — computing percentiles inline in `report.py` per family — is
where the interpolation method quietly diverges between sections.

Use `statistics.quantiles(data, n=100, method="inclusive")` from the stdlib rather than hand-rolled
index arithmetic, and record the method name in the emitted dict so a reader knows what they are
looking at. For `n < 2`, `quantiles` raises; return the single observation for every percentile and
set an explicit `"degenerate": true` flag rather than emitting a plausible-looking number from one
sample.

**Small-n honesty.** With 30 retrieval queries (VI-only scope), P99 is the maximum by construction and P95 sits on
the 2nd-worst observation. The summary carries `n` next to every percentile and the report prints
them together, so P99 is never read as a tail estimate it cannot support. This is a labelling
requirement, not a computation one.

**Judge-side latency.** Not currently captured. This phase creates
`eval/harness/usage_recorder.py` — the durable home for the mechanism Phase 1 proved — in a
latency-only form: a `BaseCallbackHandler` bound to a `ContextVar`, registered through
`register_configure_hook`, recording `(model, start, end, cache_hit)` per call and exposed as a
`record_usage()` context manager shaped like `record_contexts()`. Phase 4 extends this same module
with token capture, scope tagging, and cost; it does not build a second handler. Splitting it this
way lands the cheap, fully reversible half first — if the `ContextVar` mechanism turns out to miss
calls, that is discovered here, at the cost of a latency table, not a whole cost model.

Record `cache_hit` per call (from Phase 1 step 6's finding) so cached and uncached judge calls can
be summarized separately.

**Latency families to emit:**

| Family | Source | Grouped by |
|---|---|---|
| `retrieval.search` | `RetrievalResult.latency_s` | `search`, `language` |
| `retrieval.judge` | callback timing during `score_llm` | — |
| `e2e.turn` | `TurnRecord.latency_s` | `turn_class` |
| `e2e.judge` | callback timing during `_score_conversation` | — |
| `e2e.conversation` | sum of a conversation's turn latencies | — |

`e2e.conversation` is worth its own family: a user experiences a whole conversation, and a
per-turn P95 hides a conversation that is slow on every turn.

## Related Code Files

- Create: `eval/harness/stats.py` — `percentile_summary`
- Create: `eval/harness/usage_recorder.py` — latency-only recorder; Phase 4 extends it
- Modify: `eval/run_ragas.py` — emit latency summaries into the raw JSON alongside `breakdowns`
- Modify: `eval/harness/report.py` — replace the two summed lines with per-family tables
- Modify: `eval/harness/retrieval_eval.py`, `eval/harness/e2e_eval.py` — wrap judge scoring in
  `record_usage()` to capture judge-call timing
- Read: `eval/results/ragas-20260811-0732.json` — a real raw file to develop the aggregation
  against without spending a run

## Implementation Steps

1. Write `stats.py::percentile_summary(values: list[float]) -> dict` returning
   `{n, p50, p95, p99, min, max, mean, sum, method, degenerate}`. Unit-test it against a known
   sequence (e.g. `range(1, 101)`) so the interpolation method is pinned by a test, not by a
   comment.
2. Extend the raw run JSON with a top-level `latency` key holding one entry per family, each with
   an overall summary and a `by_<group>` map. Do not remove the existing per-record `latency_s`
   fields — per-record values are what makes a percentile auditable.
3. Create `usage_recorder.py` with the latency-only handler and `record_usage()` context manager,
   wrap `score_llm` / `_score_conversation` in it, and thread the collected timings into
   `run_retrieval_layer` / `run_e2e_layer`. Cross-check the captured call count against an
   independent count for one scoring pass — this is where Phase 1's `ContextVar`-propagation risk
   is settled in practice.
4. Replace `report.py`'s two summed latency lines with a `## Latency` section: one table per
   family with `n | p50 | p95 | p99 | mean | max`, plus the breakdown tables.
5. Print the judge cache state for the run (cold / warm / mixed, from the cache-hit counter) next
   to every judge latency table.
6. Add the latency summaries to `report_json` so the machine-readable report carries them too.
7. Develop and verify steps 1-6 against the committed `ragas-20260811-0732.json` before spending a
   live run.

## Success Criteria

- [x] `percentile_summary` has a unit test pinning its output for a known input.
- [x] Every latency family in the report shows `n` adjacent to its percentiles.
- [x] `n < 2` produces `degenerate: true`, never a fabricated spread.
- [x] Judge-side latency appears in the report for the first time, labelled with cache state.
- [x] Per-record `latency_s` values remain in the raw JSON.
- [x] The report is regenerable from the committed 2026-08-11 raw JSON without error (judge
      families absent there — must degrade to "not measured", not crash).

Note: this phase is verified at `--limit 1`, where every live family is `degenerate: true` by
construction — which is itself the cleanest test of the degenerate path. The committed 2026-08-11
raw JSON supplies the only real multi-sample distribution available without a full run, so develop
the percentile math against it (step 7). A live distribution waits for the user to ask for a full
pass.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Old raw JSON files lack the new keys and `report.py` crashes on them | Every new section reads through `.get()` with an explicit "not measured this run" fallback — `report.py` already does this for `llm_precision_by_language`; follow the same shape. Step 7 tests exactly this case |
| P99 over n=30 gets quoted as a tail SLO in a downstream doc | `n` is printed in the same row, and the report's Caveats state the sample size limit explicitly. A number cannot be made un-quotable, but it can be made hard to quote honestly out of context |
| Judge latency measured through `DiskCacheBackend` is mostly cache-hit time and looks fast | Cache state is printed with every judge table, and cached/uncached calls are summarized separately |
| Wall-clock latency over a live corpus is noisy run-to-run, so percentiles drift without any code change | This phase only observes. Phase 5 proposes bounds with a stated margin and gates nothing — the same posture `report.py::threshold_candidates` already takes for retrieval floors |

## Results (measured 2026-08-18)

Created `eval/harness/stats.py` (`percentile_summary`, `grouped_percentile_summary`) and
`eval/harness/usage_recorder.py` (the durable home for Phase 1's mechanism). Five latency
families are emitted, never pooled, each with `n` beside its percentiles.

**Deviation, forced by a Phase 1 measurement: `cache_hit` cannot be a per-call field.** The plan
assumed a cached judge response would arrive as a call tagged `cache_hit=True`. It does not — a
`DiskCacheBackend` hit fires **zero** callbacks, so there is no call to tag. Cache state is
instead *derived*: the scoring site reports how many operations it requested
(`note_scoring_operations`), the recorder reports how many reached a model, and the difference is
the hit count (`cache_hits_from`, clamped at zero because one ragas metric can legitimately make
several model calls). `cache_state()` renders that as `cold | warm | mixed | n/a` and the report
prints it beside every judge table.

Verified against the committed `ragas-20260811-0732.json` (step 7) — real distributions, no live
run spent:

| family | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| `retrieval.search` | 44 | 7.232 | 10.452 | 11.394 | 11.618 |
| `retrieval.search` search=hotels | 31 | 7.969 | 10.795 | 11.462 | 11.618 |
| `retrieval.search` search=attractions | 13 | 5.194 | 6.447 | 7.141 | 7.315 |
| `e2e.turn` | 37 | 5.484 | 14.774 | 21.074 | 22.717 |
| `e2e.turn` class=generated | 15 | 2.951 | 3.915 | 4.314 | 4.413 |
| `e2e.turn` class=template | 22 | 7.378 | 17.942 | 21.759 | 22.717 |
| `e2e.conversation` | 10 | 24.022 | 33.423 | 34.453 | 34.710 |

Judge latency measured live for the first time (`--layer e2e --limit 1`, cold cache): n=3,
p50 1.492s, mean 1.543s — the number `report.py:217` previously declared unmeasured.

The `ContextVar` propagation risk (step 3) is settled in practice: judge scoring reported 3
observed calls against 2 requested operations, i.e. every call was seen, plus one extra from a
ragas metric's internal second step. Nothing was lost.

Backward compatibility holds: a report built from the pre-instrumentation raw file renders
"Not measured this run — this raw file predates latency instrumentation" and does not raise.
`percentile_summary` is pinned by 5 tests in `backend/tests/test_eval_stats.py`, including exact
values over `range(1, 101)` so the interpolation method cannot drift silently.
