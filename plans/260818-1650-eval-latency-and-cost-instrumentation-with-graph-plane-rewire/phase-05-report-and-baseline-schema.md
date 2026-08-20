---
phase: 5
title: "Report and baseline schema"
status: complete
priority: P1
effort: "0.5d"
dependencies: [2, 3, 4]
---

# Phase 5: Report and baseline schema

## Overview

Surface the new latency and cost measurements in the markdown/JSON report, extend the frozen
baseline to carry them, propose bounds without enforcing any, and bring `eval/README.md` back in
line with what the harness actually does.

## Requirements

- Functional: `## Latency` and `## Cost` sections in the markdown report, with the cost section
  split app-side / judge-side.
- Functional: `baseline.json` carries per-family latency percentiles and per-scope cost, alongside
  the existing per-record quality scores.
- Functional: `--compare-baseline` diffs latency and cost as well as `non_llm_precision`, and keeps
  refusing to compare across differing `dataset_hash` values.
- Functional: proposed latency ceilings and cost ceilings are emitted alongside the existing
  retrieval floors, labelled as proposals.
- Non-functional: `report.py` still runs against a raw JSON that predates these keys.
- Non-functional: the report still leads with hand-authored findings and still emits no single
  headline number (`report.py`'s own module docstring).

## Architecture

**Report sections.** Two new top-level sections, placed after the existing quality sections and
before `## Run metadata` — quality is still the point of the harness; latency and cost are how much
that quality costs. `## Run metadata` absorbs the price-table `as_of` / `source` / `version`, the
judge cache state, and replaces its current line 217 ("Judge-side latency and token spend not
separately measured this run") which this plan makes false.

**Baseline extension.** `_extract_baseline_scores` (`run_ragas.py:163-179`) currently freezes
per-record quality scores plus `dataset_hash`. Add `latency` (per-family percentile summaries) and
`usage` (per-scope aggregates), and a `baseline_schema_version` so a future reader can tell a
pre-extension baseline from a post-extension one instead of inferring it from missing keys.

**Comparison semantics differ per family, and that is the design.** Retrieval `non_llm_precision`
is an exact ID comparison and reproduces byte-identically (`report.py:92-98` establishes measured
variance = 0.0), so any delta is signal. Latency and cost are not: latency varies with network and
provider load; token counts vary because the models are non-deterministic. So `--compare-baseline`
prints latency and cost deltas as **percentages with an explicit "informational, not a
regression signal" label**, and only the existing quality delta keeps its current framing. Treating
a 15% P95 movement the way a 0.05 precision drop is treated would generate noise that trains the
reader to ignore the whole comparison.

**Threshold proposals.** Extend `threshold_candidates()` rather than adding a parallel mechanism.
Its existing contract — observe, propose, state the margin's reasoning, decide nothing — extends
cleanly:

- Latency: propose a P95 ceiling per family at the observed P95 plus a stated margin. The margin
  must be justified by measured spread, not picked; with only one run there is no spread yet, so
  the first proposal states "single run, no variance measured" as its reasoning and proposes a
  deliberately loose ceiling. That honesty is the point — the existing retrieval floors carry the
  same kind of note.
- Cost: propose a per-request ceiling app-side only. A judge-side ceiling would encode the eval's
  own budget as a product constraint.

Both carry `"enforced": false`, so the field exists the day someone wants to turn gating on and no
one has to guess whether these were ever gates.

**BR-10 subsection must be repointed, not left to render empty.** `cross_language_pairs()`
(`report.py:66-84`) groups by `pair_id` and skips any group with fewer than 2 members. With EN
mirrors filtered out, every `pair_id` has exactly one member, so the function returns `[]` and the
report's "Cross-language pairs (BR-10)" heading renders with nothing under it — indistinguishable
from "cross-language retrieval is untested", when in fact BR-10's real evidence (the 5 standalone
`hotel-crosslang-*` probes) ran fine.

Replace the pair-delta view with a table over the 5 probes: id, direction (VI-sentence/EN-name vs
EN-sentence/VI-name), and non-LLM recall. That is a better fit for BR-10 as the BRD actually states
it — mixed-language queries — than the mirror deltas ever were; the mirrors measured
translated-query parity, which is a different question and one now out of scope. Keep
`cross_language_pairs()` itself for `--include-en-mirrors` runs rather than deleting it.

**README reconciliation.** Three claims are now wrong and one is stale:
- `README.md:86-88` says embeddings resolve to local Ollama `bge-m3`; `backend/.env` sets
  `EMBEDDING_PROVIDER=cloudflare`, `EMBEDDING_MODEL=@cf/baai/bge-m3`.
- `README.md:141-148` ("What a run costs") says cost is wall-clock and call count, not token
  metered — superseded by Phase 4.
- `README.md:135-138` describes `--layer e2e` in terms of `create_chat_session` /
  `process_chat_turn` — superseded by Phase 2's graph driver.
- The Layout block needs `stats.py`, `usage_recorder.py`, `cost.py`, `pricing/`.

## Related Code Files

- Modify: `eval/harness/report.py` — new sections, extended `threshold_candidates`, run metadata
- Modify: `eval/run_ragas.py` — `_extract_baseline_scores`, `_compare_baseline`
- Modify: `eval/README.md` — the four corrections above
- Modify: `backend/Makefile` — only if the `eval-ragas` target's invocation changes
- Read: `eval/results/baseline.json` — the shape being extended
- Read: `eval/results/ragas-20260811-0732.md` — the report shape being extended

## Implementation Steps

0. Repoint the BR-10 subsection at the 5 standalone crosslang probes, and make the language
   breakdowns tolerate a run with no EN records (a `by_language` map holding only `vi` must render,
   not raise).
1. Add `## Latency` to `build_report`: one table per family (`n | p50 | p95 | p99 | mean | max`),
   then the breakdown tables, then the judge cache-state line.
2. Add `## Cost` with two subsections. App-side: per-model token totals, `cost_this_run`,
   `cost_cold_cache`, cost per retrieval query, cost per e2e turn, cost per conversation — each
   with its divisor. Judge-side: the same shape, plus an embeddings sub-heading showing calls and
   input tokens with cost rendered `UNPRICED (neuron-billed)` and excluded from the judge-side
   dollar total — see Phase 4's embeddings decision.
3. Update `## Run metadata`: add price-table `version` / `as_of` / `source`, judge cache state, and
   delete the now-false "not separately measured" line.
4. Extend `threshold_candidates` with latency and cost proposals carrying `enforced: false` and a
   reasoning string that names the sample size.
5. Extend `_extract_baseline_scores` with `latency`, `usage`, and `baseline_schema_version`.
6. Extend `_compare_baseline` with latency/cost delta printing under an explicit informational
   label; leave the `dataset_hash` refusal and the quality delta framing untouched.
7. Guard every new section behind `.get()` with a "not measured this run" fallback, and verify by
   regenerating a report from the committed `ragas-20260811-0732.json`.
8. Rewrite the four `README.md` sections against the code as it now is, and re-check every other
   claim in that file while there — the drift found in this phase suggests more.
9. Add the new report/baseline fields to `report_json` so the machine-readable artifact keeps
   parity with the markdown.

## Success Criteria

- [x] A report generated from `ragas-20260811-0732.json` renders with latency/cost marked "not
      measured this run" and does not raise.
- [x] A report generated from a post-Phase-4 raw file shows populated latency and cost sections.
- [x] `baseline.json` written by `--save-baseline` contains `latency`, `usage`, and
      `baseline_schema_version`.
- [x] `--compare-baseline` prints latency/cost deltas labelled informational, and still refuses to
      compare across a changed `dataset_hash`.
- [x] Every threshold candidate — old and new — carries `enforced: false`.
- [x] No `README.md` claim contradicts the code: embeddings provider, cost metering, and the e2e
      driver description are all current.
- [x] The report still contains no single headline number.
- [x] The BR-10 subsection lists the 5 crosslang probes with recall; it is never blank.
- [x] A VI-only run renders language breakdowns without raising, and the report states the run was
      Vietnamese-only so a `vi`-only breakdown is not mistaken for missing data.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| The report grows long enough that the hand-authored findings stop being read | New sections go *after* quality and before run metadata; findings stay first. If length becomes a real problem, latency/cost detail moves to the JSON and the markdown keeps only the headline table per family |
| Latency/cost deltas get read as pass/fail despite the label | The label is on the delta line itself, not only in a preamble, and `enforced: false` is machine-visible in the JSON |
| Extending `baseline.json` invalidates the committed one | `baseline_schema_version` makes the difference explicit, and Phase 6 rewrites the baseline anyway — the current one is already stale against a dataset the harness can no longer run |
| README rewriting turns into an unbounded audit | Step 8 is scoped: fix the four known-wrong sections, note anything else found, and file it rather than fixing it here |

## Results (measured 2026-08-18)

### BR-10 no longer renders blank

`cross_language_pairs()` returns `[]` on a Vietnamese-only run (every `pair_id` has one member),
which would have printed an empty heading — indistinguishable from "cross-language retrieval is
untested". Added `crosslang_probes()`: a table of the 5 standalone probes with direction
(VI-sentence/EN-name vs EN-sentence/VI-name, derived from each record's own `language`) and
recall. `cross_language_pairs()` is kept and still renders, under its own heading, on
`--include-en-mirrors` runs where the pairs actually exist.

The Retrieval section now states the Vietnamese-only scope explicitly, so a `by_language`
breakdown holding only `vi` reads as the intended result rather than missing data.

### Thresholds

`threshold_candidates` gained `enforced: false` on every entry; `latency_cost_candidates` adds
p95 latency ceilings per family and per-request cost ceilings **app-side only** — a judge-side
ceiling would encode the eval's own budget as a product constraint. Both multipliers are 2x and
say why in their reasoning string: with one run there is no measured spread to derive a margin
from, so the first proposal is deliberately loose and names its own `n`. Verified: all candidates
across both generators carry `enforced: false`.

Removed the hardcoded line "No e2e threshold is proposed this run: finding 1 blocks essentially
all quality signal (0% reached expected stage)" — run-specific commentary baked into the
template, and now false (100% reached expected stage on current runs). Findings belong in the
hand-authored section.

### Baseline

`baseline_schema_version: 2` (1 = quality scores + `dataset_hash`; 2 adds `latency` and `usage`).
Written and verified: `--save-baseline` produced all six keys with `retrieval.search` /
`retrieval.judge` latency families and per-scope usage totals.

`--compare-baseline` keeps the quality delta framing untouched and prints latency/cost movement
under `--- Latency and cost deltas (INFORMATIONAL — not a regression signal) ---`. The label
earned itself immediately: across two identical back-to-back runs, `non_llm_precision` max delta
was `0.0000` while `retrieval.search` p95 moved **−37.3%** and app-side output tokens **+36.4%**.
Framing that movement as a regression signal would train the reader to ignore the comparison.
The `dataset_hash` refusal still fires (verified against a doctored baseline).

### README

Four corrections, all verified against current code: embeddings resolve to Cloudflare
`@cf/baai/bge-m3` (not Ollama); cost is token-metered app/judge-separately (not wall-clock +
call count); `--layer e2e` drives turns through `routes._run_turn_via_graph` with the
persistence assert and the one measured empty-`sessions`-row exception; Layout gains `stats.py`,
`usage_recorder.py`, `cost.py`, `pricing/`. Also added the Vietnamese-only scope, the
`--include-en-mirrors` flag, and the `override=True` env-precedence note. A grep for the other
stale claims (`process_chat_turn`, `create_chat_session`, `finalized`, "not metered") returns
nothing further.

### Compatibility

A report generated from `ragas-20260811-0732.json` renders both new sections as "Not measured
this run — this raw file predates … instrumentation" and does not raise; a report from a
post-Phase-4 raw file populates both. `report_json` carries `latency`, `usage` (aggregates only —
the per-call audit trail stays in the raw file), `crosslang_probes`, `latency_cost_candidates`,
and `price_table` provenance.
