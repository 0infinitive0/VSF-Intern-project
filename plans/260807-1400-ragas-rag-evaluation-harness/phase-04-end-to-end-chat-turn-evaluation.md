---
phase: 4
title: "End-to-end chat turn evaluation"
status: pending
priority: P1
effort: "1-1.5d"
dependencies: [1, 2]
---

# Phase 4: End-to-end chat turn evaluation

## Overview

Replay the scripted conversations through the real agent, capture what retrieval actually returned
during each turn, and score the agent's replies for faithfulness to those contexts and relevance to
the user's question. This is the layer that answers "is the agent inventing hotels?".

Independent of Phase 3 — both depend only on Phases 1 and 2 and can proceed in parallel.

## Requirements

- Functional: conversations replay turn-by-turn through `process_chat_turn` against real services.
- Functional: contexts retrieved during a turn are captured and attached to that turn's sample.
- Functional: `Faithfulness` and `ResponseRelevancy` scored per turn.
- Functional: LLM-authored text is scored separately from template-rendered text.
- Functional: full transcripts persisted for inspection.
- Non-functional: `session.py` and `supabase_search.py` unmodified.
- Non-functional: a conversation failing to reach `expected_stage` is reported as a harness failure,
  never averaged into quality scores.

## Architecture

### Capturing retrieved contexts

`TurnResult` carries only `text` and `tool` (`backend/src/agents/session.py:64`) — the contexts are
not in the return value. They are, however, all funnelled through one function:
`supabase_search._execute_rpc` (`backend/src/services/supabase_search.py:91`), the single point every
hotel and attraction RPC passes through.

The harness wraps it for the duration of a turn:

```python
# eval/harness/context_recorder.py
import contextlib
from src.services import supabase_search

@contextlib.contextmanager
def record_contexts():
    """Capture every Supabase RPC result during a turn.

    _execute_rpc is the single chokepoint for hotel and attraction retrieval,
    so wrapping it captures the whole context set without touching production code.
    """
    captured: list[dict] = []
    original = supabase_search._execute_rpc

    def recording(rpc_name: str, params: dict):
        rows = original(rpc_name, params)
        captured.extend(rows)
        return rows

    supabase_search._execute_rpc = recording
    try:
        yield captured
    finally:
        supabase_search._execute_rpc = original
```

Two things to verify at implementation time, both of which would silently produce empty context
lists:

1. Call sites must resolve `_execute_rpc` through the module at call time, not via
   `from ... import _execute_rpc` bound at import. Current call sites use the bare name inside the
   same module, so patching the module attribute does reach them — confirm this still holds.
2. `@traceable` wraps the original function; replacing the module attribute replaces the *decorated*
   callable, so LangSmith tracing continues to work. Verify a trace still appears.

Restoration in `finally` is not optional — a leaked patch would corrupt every later run in the same
process.

### Separating templated output from generated output

`trip_formatter.py` (401 lines) renders itineraries from templates. Faithfulness over templated text
is near-1.0 by construction and says nothing about model behaviour. Scoring it together with
LLM-authored prose would inflate the headline number into meaninglessness.

Split by `TurnResult.tool`:

| `tool` value | Output character | Scored as |
|---|---|---|
| `recommend_hotels`, `select_hotel`, `finalize_trip_plan` | Mostly template-rendered | `template` |
| `agent_stream`, `None` | LLM-authored | `generated` |
| `execute_trip_edit_request` | Mixed | `mixed`, reported separately |

Both are scored; the report never merges them into one average. For `template` turns, faithfulness
functions as a grounding *regression* check (did a hotel name appear that was never retrieved?)
rather than a quality score, and the report says so.

### Sample construction

```python
with record_contexts() as captured:
    result = process_chat_turn(session, turn_text, language=record["language"])

sample = SingleTurnSample(
    user_input=turn_text,
    response=result.text,
    retrieved_contexts=[as_context(row) for row in captured],
)
```

A turn with an empty `captured` list (pure intake question — "how many people?") has no contexts to
be faithful to. Those turns are excluded from faithfulness and reported as a count. Scoring
faithfulness against an empty context set yields a meaningless number.

### Session setup

Use `create_chat_session` (`backend/src/agents/session.py:267`) with a per-conversation UUID and
**no persist hook** — eval runs must not write into the real session store.

## Related Code Files

- Create: `eval/harness/context_recorder.py`
- Create: `eval/harness/e2e_eval.py`
- Create: `eval/harness/transcripts.py` — persist full conversation transcripts
- Modify: `eval/run_ragas.py` — wire `--layer e2e`
- Modify: `eval/harness/dataset_loader.py` — conversation-record accessors
- Read only: `backend/src/agents/session.py`, `backend/src/services/supabase_search.py`,
  `backend/src/services/trip_formatter.py`

## Implementation Steps

1. Write `context_recorder.py` as above.
2. Prove it works before building on it: a standalone check that runs one hotel search inside the
   context manager and asserts `captured` is non-empty, then asserts `_execute_rpc` is restored to
   the original object afterwards.
3. Write `e2e_eval.py`: for each conversation, create a hook-less session, replay turns in order,
   record each turn's `(user_input, response, contexts, tool, latency)`.
4. After the last turn, compare `derive_stage(result, session)` to `expected_stage`. On mismatch,
   mark the conversation `harness_failure` with the stage reached, and keep its turns out of the
   quality aggregates.
5. Classify each turn `template` / `generated` / `mixed` from `TurnResult.tool`.
6. Build `SingleTurnSample`s, skipping faithfulness for turns with no captured contexts.
7. Score with `Faithfulness()` and `ResponseRelevancy()` using the Phase 1 judge and embeddings.
8. Persist full transcripts to `eval/results/transcripts/<conversation-id>.md` — every turn, its
   contexts, its scores. When a score looks wrong the transcript is the only way to tell whether the
   agent or the judge was at fault.
9. Run the full set. Record wall-clock time, judge spend, and how many conversations failed to reach
   their expected stage.
10. Read the 3 lowest-faithfulness turns end to end and determine whether each is a genuine
    hallucination, a context-capture gap, or a judge misfire. Write the finding down.

## Success Criteria

- [ ] All conversations replay without unhandled exceptions.
- [ ] Step 2's check passes: contexts captured, `_execute_rpc` restored.
- [ ] ≥ 80% of conversations reach their `expected_stage`; the rest are listed with the stage reached.
- [ ] Faithfulness and relevancy scored per turn, split `template` / `generated` / `mixed`.
- [ ] Turns with no retrieved contexts are excluded from faithfulness and counted in the report.
- [ ] A transcript file exists for every conversation.
- [ ] A deliberately hallucinated reply (injected in a scratch check) scores materially lower on
      faithfulness — proving the metric discriminates on *this* data, not just Phase 1's toy sample.
- [ ] The 3 lowest-faithfulness turns are diagnosed by cause.
- [ ] `git diff backend/src/` is empty.

## Risk Assessment

- **Monkeypatching is fragile.** If `_execute_rpc` is ever re-bound at import in a call site, capture
  silently returns empty and every faithfulness score becomes meaningless. Step 2 is the guard, and
  an empty-capture rate above ~20% on turns whose `tool` implies retrieval should be treated as a
  harness bug, not a finding.
- **Full agent runs are slow.** Ten conversations × 4 turns × real LLM + real Supabase is minutes,
  not seconds. Support `--limit` and per-conversation resume; do not let slowness become a reason to
  shrink the set.
- **Non-determinism across runs.** Even at `temperature=0` the agent may route differently. Fix the
  judge via cache, accept agent variance, and report it: run the same conversation twice and record
  the score spread as a stated confidence interval rather than pretending to precision.
- **Cross-turn context bleed.** Contexts retrieved in turn 2 are not the contexts for turn 4. The
  recorder resets per turn; verify that turn 4's samples do not carry turn 2's hotels.
- **Real writes escaping into production stores.** No persist hook, and a distinct session-ID prefix
  (`ragas-eval-`) so anything that does leak is identifiable and removable.
- **Templated turns inflating the headline.** Mitigated by the split, but only if the report actually
  keeps them apart — Phase 5's success criteria enforce that.
