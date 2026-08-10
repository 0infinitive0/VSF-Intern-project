---
phase: 5
title: "Report, baseline and thresholds"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: [3, 4]
---

# Phase 5: Report, baseline and thresholds

## Overview

Turn raw scores into a report a human can act on, freeze a committed baseline so future retrieval
changes are measurable, and propose (not enforce) threshold candidates for the M2/M3 gates.

## Requirements

- Functional: one command produces a markdown report and a machine-readable JSON for both layers.
- Functional: `eval/results/baseline.json` committed, with a documented comparison workflow.
- Functional: report states cost, runtime, corpus size, judge model, and dataset version.
- Functional: threshold candidates derived from observed data and labelled as proposals.
- Non-functional: no secrets, keys, connection strings, or raw RPC params in any committed output.
- Non-functional: the report leads with findings, not with a table of averages.

## Architecture

### Report shape

Averages are the least useful part of an eval and the easiest to over-read. The report is ordered
so the actionable content comes first:

```markdown
# RAGAS evaluation — 2026-08-DD

## What this run says
3-6 sentences. Plain findings. What is actually broken.

## Findings
Ranked. Each: what failed, which queries/turns, the diagnosed cause, evidence.

## Retrieval (Layer 1)
Non-LLM precision/recall | LLM precision/relevance
Breakdown: by language · by search type · cross-language pairs
Worst 10 queries with diagnosed cause

## End-to-end (Layer 2)
Faithfulness/relevancy, split generated · template · mixed
Turns excluded (no contexts): N
Conversations not reaching expected stage: N
Worst 5 turns with links to transcripts

## Run metadata
Judge model+version · dataset version+hash · corpus counts ·
wall-clock · judge tokens+cost · retrieval-side LLM cost · cache hit rate

## Caveats
What these numbers do not mean.
```

The Caveats section is mandatory and specific — templated-output inflation, small N, live-corpus
non-hermeticity, judge variance, VI/EN judge asymmetry. A number handed to a stakeholder without
its caveats will be quoted without them.

### Baseline and comparison

`eval/results/baseline.json` is a committed frozen run: per-sample scores keyed by golden-record
`id`, plus a dataset hash. `--compare-baseline` produces a per-record delta table, so the question
"did this embedding change help?" is answerable without re-reading two reports.

The dataset hash matters: comparing scores across different dataset versions is invalid, and the
tool should refuse rather than silently produce a meaningless diff.

### Threshold candidates — proposals, not gates

Roadmap Open Question 4 (KPI thresholds unset, deferred to kick-off) is **not** resolved here.
This phase observes what the system currently does and proposes floors from that; whether they are
acceptable is a business decision owned by roadmap phases 6 and 8.

Proposals are derived, not invented: set each candidate floor a stated margin below the observed
baseline, wide enough to absorb the measured run-to-run variance from Phases 3 and 4. Record the
observed value, the variance, the proposed floor, and the reasoning for each — a threshold without
its derivation is a number someone will later be unable to defend.

Only the non-LLM retrieval metrics are proposed as CI-viable; LLM-judged metrics are proposed as
review-time signals only, because they cost money and vary between runs.

## Related Code Files

- Create: `eval/harness/report.py` — `EvaluationResult` → markdown + JSON
- Create: `eval/results/baseline.json`
- Create: `eval/results/ragas-<ts>.md` / `.json` — first real report
- Modify: `eval/run_ragas.py` — `--compare-baseline`, `--save-baseline`
- Modify: `eval/README.md` — how to read a report, how to refresh the baseline
- Modify: `backend/Makefile` — finalise `eval-ragas`
- Modify: `plans/260723-1015-v-ota-poc-master-roadmap/phase-06-m2-gate-end-to-end-integration.md`
  and `phase-08-m3-evaluation-handover-and-go-no-go.md` — point at this harness
- Read only: `docs/README.md` and the docs navigation, to place the eval doc correctly

## Implementation Steps

1. Write `report.py`: consume the per-sample JSON from Phases 3 and 4, emit markdown + JSON.
2. Implement the breakdowns — by language, by search type, by `pair_id`, by turn class. Cross-language
   `pair_id` deltas are BR-10's evidence and get their own subsection.
3. Implement worst-N tables with a `cause` column populated from the Phase 3 step-9 and Phase 4
   step-10 diagnoses.
4. Add a redaction pass over everything written to `eval/results/`: no env values, no keys, no
   connection strings, no raw RPC params, no embedding vectors. Assert on it in a check rather than
   trusting review.
5. Capture run metadata — judge model, dataset hash, corpus row counts, wall clock, token usage,
   cache hit rate. Use RAGAS's `token_usage_parser` for spend if 0.3.9 exposes it; otherwise count
   at the callback layer.
6. Run both layers fully. This is the first complete run and the report is a real deliverable.
7. Write the "What this run says" and "Findings" sections by hand from the diagnoses. Generated
   prose here would be padding — the findings are the point of the whole plan.
8. Freeze `baseline.json` with `--save-baseline`; commit it.
9. Implement and verify `--compare-baseline`: re-run, confirm near-zero deltas, confirm it refuses
   to compare across differing dataset hashes.
10. Derive threshold candidates per the architecture above. Label them proposals; record observed
    value, variance, proposed floor, and reasoning for each.
11. Update `eval/README.md`: run it, read it, refresh the baseline, what it costs.
12. Add pointers from roadmap phases 6 and 8 to this harness. Do not restate the numbers there —
    link, so there is one source of truth.
13. Check whether `docs/` should carry an evaluation page; if the docs navigation has a natural home,
    add a short one that links to `eval/README.md` rather than duplicating it.

## Success Criteria

- [ ] `make eval-ragas` runs both layers and writes a timestamped `.md` + `.json` pair.
- [ ] Report opens with findings, not with averages.
- [ ] Breakdowns present: language, search type, cross-language pairs, turn class.
- [ ] Worst-N tables carry a diagnosed cause per row.
- [ ] Caveats section names templated-output inflation, small N, non-hermeticity, and judge variance.
- [ ] Run metadata includes judge model, dataset hash, corpus counts, runtime, and measured cost.
- [ ] Redaction check passes on committed outputs.
- [ ] `baseline.json` committed; `--compare-baseline` shows near-zero deltas on an unchanged re-run
      and refuses a cross-dataset-version comparison.
- [ ] Threshold candidates recorded with observed value, variance, proposed floor, and reasoning —
      explicitly marked proposals, with roadmap Open Question 4 still open.
- [ ] Roadmap phases 6 and 8 link here.
- [ ] `eval/README.md` lets someone who has never seen this plan run it and read the output.

## Risk Assessment

- **The report gets read as a grade.** A single "RAGAS score: 0.82" travels further than its
  caveats. Mitigated by leading with findings, splitting every metric family, and never emitting one
  headline number.
- **Proposed thresholds harden into accepted ones** without anyone deciding. Every threshold is
  labelled a proposal with its derivation attached, and Open Question 4 stays explicitly open.
- **Baseline captures a bad state as "normal".** If Phases 3-4 surface real defects, note in the
  baseline file that it records current behaviour including known defects — it is a regression
  reference, not a quality target.
- **Secrets in output.** Step 4's assertion runs before anything is committed; review alone is not
  sufficient.
- **Cost measurement may be unavailable** if 0.3.9's token parser does not cover the configured
  provider. Fall back to a callback-level count, or report measured wall-clock plus request count
  and say cost is estimated.
- **Dataset drift invalidating comparisons.** The hash check makes this an error rather than a
  silently wrong diff.
