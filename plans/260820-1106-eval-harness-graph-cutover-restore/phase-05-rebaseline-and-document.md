---
phase: 5
title: "Rebaseline and document"
status: pending
priority: P1
effort: "0.5-1d"
dependencies: [3, 4]
---

# Phase 5: Rebaseline and document

## Overview

Run the restored harness end to end, commit a baseline that measures the graph plane, and make
the superseded baseline unmistakably superseded rather than silently wrong.

## Problem

`eval/results/baseline.json` (2026-08-11, `dataset_hash 28c553772bf69468`) was measured against
the plane phase 11 of the cutover plan deleted. It is not stale — it is unusable. Its e2e half
describes execution machinery that no longer exists.

The danger is specific: `run_ragas.py --compare-baseline` will happily diff against it, because
the dataset hash still matches — the *dataset* did not change, the *system* did. Whoever runs
that gets a confident, meaningless delta. The guard was never designed for this failure mode.

## Requirements

- Functional: a full both-layer run against the graph plane, committed as the new baseline.
- Functional: `--compare-baseline` cannot silently diff across the cutover boundary.
- Functional: `eval/README.md` reflects the graph architecture, not the deleted one.
- Functional: the old Ragas plan's frontmatter stops claiming `pending` for completed work.
- Non-functional: no secrets in committed results — scores and query text only.

## Architecture

**Guard the comparison.** `dataset_hash` alone is the wrong identity for a baseline; it answers
"did the questions change" and says nothing about "did the system change". Add a plane marker
(e.g. `harness_version` / `plane: "graph"`) written into results and checked on comparison, so
a cross-plane diff refuses instead of misleading. This is the concrete lesson of the whole
plan — the harness had no way to notice the system underneath it had been replaced.

**Preserve, don't delete.** Keep the 2026-08-11 baseline as
`baseline-pre-graph-cutover-20260811.json`, with a README note on what plane it measured and
why it is not comparable. It is the historical record of the pre-graph system; deleting it
destroys evidence to save a file.

**Report honestly.** The new report presents new numbers, not a delta. Any temptation to write
"faithfulness improved/declined vs baseline" is wrong by construction — a different execution
plane, a wider context capture (phase 4), and judge variance all moved at once. State that
plainly in Caveats. Carry forward the caveats that remain true: template turns dominate
faithfulness; excluded turns are excluded rather than zero; small N (10 conversations, 44
queries); retrieval has real run-to-run nondeterminism (EN recall moved 0.5909→0.6364 across
identical re-runs); cost is wall-clock + call count, not token-metered.

**Threshold candidates stay candidates.** Recompute the non-LLM proposals from the new run and
write them into the report as proposals. The plan that owned the go/no-go on those thresholds
(`260723-1015-v-ota-poc-master-roadmap`) was deleted in `e069e3f`, so there is currently no
consumer to hand them to — record them anyway and flag that they are unowned. No CI gate (plan
non-goal).

**Bookkeeping** (per the owner's direction — these two only):
- Sync `260807-1400-ragas-rag-evaluation-harness` frontmatter: `plan.md` and all five phase
  files say `status: pending` while the body marks every phase Completed.
- Mark the old baseline superseded in `eval/README.md`.

The unticked `[ ] eval/ end-to-end ≥ ... baseline` in the cutover plan's phase 11 is
deliberately left as-is; this plan is the record of that outstanding work.

## Related Code Files

- Modify: `eval/harness/report.py` (plane marker + comparison guard)
- Modify: `eval/README.md` (graph architecture, superseded baseline, how to re-run)
- Create: `eval/results/ragas-<ts>.json` / `.md`, new `eval/results/baseline.json`
- Rename: `eval/results/baseline.json` → `baseline-pre-graph-cutover-20260811.json`
- Modify: `plans/260807-1400-ragas-rag-evaluation-harness/plan.md` + 5 phase files (frontmatter)
- Delete: `eval/results/transcripts/conv-crosslang-hyatt-danang.md` (orphan — its conversation
  was dropped from the dataset)

## Implementation Steps

1. Add the plane marker and the cross-plane comparison guard to `report.py`.
2. Rename the old baseline; note in `eval/README.md` what it measured and why it is not
   comparable.
3. Full run, both layers, LLM metrics on. Expect 15-20+ minutes of real LLM and Supabase traffic.
4. Generate the report with hand-authored findings and caveats (`report.py` deliberately does
   not auto-generate these — see its docstring).
5. Commit as the new `baseline.json`.
6. Re-run `--compare-baseline` to confirm non-LLM metrics reproduce and the guard passes
   within-plane.
7. Confirm the guard *refuses* against the renamed pre-cutover baseline.
8. Rewrite the parts of `eval/README.md` describing `process_chat_turn` / session-based
   execution.
9. Sync the old plan's frontmatter; remove the orphan transcript.
10. `detect_changes()` before committing, per project convention.

## Success Criteria

- [ ] A full both-layer run completes with 0 harness errors.
- [ ] New `eval/results/baseline.json` committed, carrying the plane marker.
- [ ] `baseline-pre-graph-cutover-20260811.json` preserved and explained in the README.
- [ ] `--compare-baseline` refuses a cross-plane comparison and succeeds within-plane.
- [ ] Non-LLM metrics reproduce exactly across two same-dataset runs (they are exact ID
      comparisons given a retrieved set).
- [ ] Report presents new numbers, never a delta against 2026-08-11, and says why in Caveats.
- [ ] `eval/README.md` contains no reference to `process_chat_turn` or the deleted plane.
- [ ] `260807-1400-...` frontmatter says `completed` across `plan.md` and all five phase files.
- [ ] `backend/requirements.txt` byte-identical to its pre-plan state.
- [ ] No credentials, keys, or raw RPC params in any committed result.

## Risk Assessment

**The new numbers may be worse and unattributable.** Three things changed at once: execution
plane, context capture, judge variance. Do not attribute. Report the new baseline as a new
baseline; if a number looks alarming, investigate it as a fresh finding against transcripts.

**A full run is slow and paid.** ~15-20+ minutes, real LLM and Supabase traffic. The disk cache
makes re-runs cheap but the first pass is not. Budget for one clean run, not iteration.

**Retrieval nondeterminism could be mistaken for signal.** Live vector search over a corpus that
drifts between calls; the previous pass measured a 0.045 swing in EN recall across identical
re-runs. Keep that caveat prominent.

**A stale README is worse than no README.** It currently documents an execution path that does
not exist and would send the next reader down it. Step 8 is not optional polish.
