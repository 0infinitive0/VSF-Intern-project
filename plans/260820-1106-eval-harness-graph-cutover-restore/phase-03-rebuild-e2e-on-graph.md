---
phase: 3
title: "Rebuild Layer 2 on the graph"
status: pending
priority: P1
effort: "1-1.5d"
dependencies: [1, 2]
---

# Phase 3: Rebuild Layer 2 on the graph

## Overview

Rewrite `eval/harness/e2e_eval.py` against `turn_runner.run_turn`, replacing three deleted
`session.py` symbols. The rewrite is a simplification, not a port: `PlannerChatResponse`
already carries what the old harness assembled by hand.

## Problem

`e2e_eval.py:18` imports `derive_stage`, `handle_frontend_hotel_selection` and
`process_chat_turn`. All three were deleted in the cutover. The harness cannot run a single
conversation.

## Requirements

- Functional: replay all 10 scripted conversations through the real graph, real Supabase.
- Functional: same scored outputs as before — reached stage, faithfulness, response relevancy,
  `hotel_grounding`, per-conversation transcripts.
- Functional: the hotel-selection step drives the same deterministic path the UI card-click
  uses (`selected_hotel_id` in extra state), not parsed text.
- Non-functional: zero writes to the real session store.
- Non-functional: same dataset, unchanged. No new records, no edited expectations.

## Architecture

### The mapping

| Old (deleted) | New |
|---|---|
| `process_chat_turn(session, text, language=...)` | `run_turn(app, sid, text, language, persist=None)` |
| `handle_frontend_hotel_selection(session, hotel_id)` | `run_turn(app, sid, msg, lang, extra_state={"selected_hotel_id": hotel_id}, persist=None)` |
| `derive_stage(turn_result, session)` | `response.stage` — already derived |
| `session.pending_hotel_selection["options"]` | `response.hotel_options` (`.id`, `schemas.py:246`) |
| `create_chat_session(session_id)` | not needed — no registry entry without persistence |

`extra_state={"selected_hotel_id": ...}` is exactly what `POST /hotels/select` passes
(`routes.py:695`), read deterministically by `hotel_node` rather than re-parsed from message
text. The harness therefore exercises the same path as a real card click, which is what the
original plan wanted and had to approximate.

### Isolation

Two independent guarantees, neither of which is an env var:

1. `persist=None` — `run_turn` has no persistence callable, so there is no code path to the
   session store. This is why phase 1 injects the policy instead of reading
   `_persistence_enabled`.
2. A per-run `MemorySaver`: the harness compiles its own graph with
   `build_graph(checkpointer=MemorySaver())` rather than calling `routes._get_graph_v2()`.
   Conversations cannot collide with server state or with each other across runs.

Keep the `ragas-eval-` session-id prefix. It costs nothing and makes any leaked row obvious.

### Scoring

Unchanged in intent. Two notes carried forward from the previous report, because they are the
difference between a meaningful number and a misleading one:

- **Template turns dominate faithfulness.** `recommend_hotels` / `select_hotel` turns render a
  fixed template sentence with no per-hotel facts in the text, so `Faithfulness` (0.28) and
  `ResponseRelevancy` (0.53) were structurally near-meaningless there. `hotel_grounding` — an
  exact ID-set comparison, no judge — is the real grounding signal and read 1.0. Preserve that
  split; do not let a headline faithfulness number stand unqualified.
- **Excluded turns are excluded, not zero.** `select_hotel` turns and agent clarifying-question
  turns contribute no faithfulness/relevancy sample. Keep that, and keep saying so.

`hotel_grounding` gets simpler and stricter: compare `response.hotel_options[].id` against the
IDs a recorded retrieval call actually returned earlier in the same conversation.

## Related Code Files

- Rewrite: `eval/harness/e2e_eval.py`
- Modify: `eval/run_ragas.py` (wire the deferred loader from phase 2 to the new entry point)
- Read only: `eval/harness/transcripts.py`, `eval/harness/context_recorder.py`
- Do not touch: `eval/datasets/golden-conversations.jsonl`

## Implementation Steps

1. Verify the availability window before writing anything: query the corpus for rooms in
   2026-07-01..07. Today is 2026-08-20 and that window is in the past. `validate_stay_dates`
   does not reject past dates, so if the data is gone, conversations fail for data reasons that
   look exactly like regressions. Resolve Open Question 1 here, in writing.
2. Rewrite `e2e_eval.py` against `run_turn`, per the mapping table.
3. Compile a per-run graph with a fresh `MemorySaver`; never call `routes._get_graph_v2()`.
4. Rewire `hotel_grounding` to `response.hotel_options`.
5. Keep transcript writing, the turn-class split, and the exclusion rules as they were.
6. Run one conversation end to end; read the transcript by hand before trusting any aggregate.
7. Run all 10. Record a Supabase `sessions` row count before and after.

## Success Criteria

- [ ] All 10 conversations replay with 0 harness errors.
- [ ] At least 8 reach their expected stage — matching pre-cutover. Fewer is a finding to
      investigate and write up, not a number to accept silently.
- [ ] `hotel_grounding` computed from `response.hotel_options` on every template turn.
- [ ] Supabase `sessions` row count identical before and after a full run.
- [ ] Transcripts written for all 10 and spot-checked by hand.
- [ ] The two known-failing cases still fail *for their original reasons*
      (`conv-unsupported-destination`: Phú Quốc absent from the corpus;
      `conv-hue-thin-corpus-probe`: deliberately thin-corpus probe).

## Risk Assessment

**The July 2026 availability window may be empty.** Step 1 exists to settle this before any
conversation is interpreted. Getting this wrong once already cost the original plan an entire
scoring pass (report pass 1 of 5).

**Under 8 conversations reaching their stage.** Genuinely ambiguous: a real graph regression, or
a harness that drives the graph slightly differently. Do not paper over it — diagnose against
the transcript, and if it is a product regression, that is the harness doing its job, exactly as
it did with the `max_price="2026"` bug.

**Silent writes to the real store.** Two structural guards plus a row-count check. The row count
is what proves it; the guards are what make it true.

**Graph state leaking between conversations.** A shared checkpointer would let conversation N+1
see N's state. Fresh `MemorySaver` per run, distinct `thread_id` per conversation.
