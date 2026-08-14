---
phase: 10
title: "Audit log and State Patch Accuracy eval"
status: completed
priority: P3
effort: "1.5d"
dependencies: [3]
---

# Phase 10: Audit log and State Patch Accuracy eval

## Overview

Make every state mutation auditable and measure whether the patch layer is actually correct.
Measurement, not behavior — but without it, Phases 2-7 have no regression signal beyond
unit tests.

## Problem

There is no record of how state reached its current value. When a user reports "nó không đổi
gì cả", the only evidence is application logs that do not carry before/after state. Every
diagnosis in this plan required reading source and tracing by hand.

The existing eval harness (`plans/260807-1400-ragas-rag-evaluation-harness/`, delivered)
scores retrieval and end-to-end conversations. It has already proven its worth — it caught
the `max_price="2026"` hallucination that produced `MIN_PLAUSIBLE_PRICE_VND`. But it measures
*response* quality; the architecture doc §34 is explicit that the key metric for the
conversational state layer is **State Patch Accuracy**, which nothing currently measures.

## Requirements

- Functional: every applied patch is recorded with path, before value, after value, source, timestamp.
- Functional: rejected changes are recorded too, with the rejection reason — a silently
  dropped intent must leave a trace.
- Functional: an eval dataset maps utterances to expected patches, scored automatically.
- Non-functional: audit writes never fail a chat turn (same best-effort contract as
  `supabase_persist_hook`).
- Non-functional: the eval runs in the existing isolated `eval/` venv; `backend/requirements.txt`
  stays untouched.

## Architecture

**Audit trail.** Records `{trip_id/session_id, source, path, before, after, rejected_reason, at}`.
Storage decision is plan.md **Open Question 3** — a dedicated Supabase table (doc §28) or an
append-only list on the existing `sessions.context_data`. The table is cleaner for querying;
`context_data` needs no migration. Resolve before implementing.

Write path: `apply_patch` returns applied + rejected; the caller emits both. Best-effort with
the retry-once-then-log shape `supabase_persist_hook` already uses.

**State Patch Accuracy.** Extends `eval/`, does not replace it:

```
eval/datasets/state_patches.jsonl
  {"utterance": "ngày 1 tôi muốn thiên nhiên khám phá",
   "context": {"has_trip": true, "duration_days": 3},
   "expected": [{"path": "daily_preferences.1.theme", "operation": "set", "value": "thiên nhiên"}]}
```

Scored per-change: exact path match, operation match, value match (normalized). Reported as
precision/recall over changes, plus a whole-utterance exact-match rate. Seed cases come
directly from doc §34 plus every failure in this plan's reported-symptom table — so the five
originally reported bugs become permanent regression cases.

## Related Code Files

- Create: `backend/src/services/state_audit.py`
- Create: `eval/datasets/state_patches.jsonl`
- Create: `eval/harness/score_state_patches.py`
- Modify: `backend/src/domain/travel_state.py` — emit applied/rejected for auditing
- Modify: `eval/README.md`, `backend/Makefile` — add the eval target
- Possibly create: `backend/scripts/migrations/*_state_audit_logs.sql` (pending Open Question 3)

## Implementation Steps

1. Resolve Open Question 3 (table vs `context_data`) with the user before writing storage code.
2. Implement `state_audit.py` with the best-effort write contract.
3. Emit audit records from `apply_patch` callers, including rejections.
4. Build the seed dataset: doc §34 case list + the five reported symptoms from plan.md.
5. Implement the scorer; report precision/recall per change and exact-match per utterance.
6. Add a Makefile target next to the existing RAGAS targets.
7. Record a baseline and commit it, matching the existing `eval/results/baseline.json` convention.
8. Document how to read the audit trail when diagnosing a "nothing changed" report.

## Success Criteria

- [ ] Every applied patch produces an audit record with before/after
- [ ] Every rejected change produces a record with its reason
- [ ] A DB outage during audit write does not fail the chat turn
- [ ] The eval scores State Patch Accuracy over the seed dataset and writes a timestamped report
- [ ] All five originally reported symptoms exist as dataset cases
- [ ] A committed baseline exists and is comparable across runs
- [ ] `backend/requirements.txt` is byte-identical to its pre-phase state
- [ ] `make test` green

## Risk Assessment

| Risk | Mitigation |
|---|---|
| Audit writes add latency to every turn | Best-effort and non-blocking; measure per-turn delta and record it. Drop to batched writes if measurable |
| Audit table grows unbounded | Same retention policy as the Phase 4 checkpoint pruning cron; decide both together |
| Eval dataset encodes today's wrong behavior as expected | Expected patches are derived from the requirements in Phases 1-7, not from observed output. Every case traces to a success criterion |
| Scoring Vietnamese values is brittle (normalization) | Reuse `_normalize_for_match` from `hotel_selection.py` — already the repo's diacritic-insensitive comparison |
| Duplicating the delivered RAGAS harness | This extends `eval/`, reusing its venv, results path, and baseline convention. No second harness |
