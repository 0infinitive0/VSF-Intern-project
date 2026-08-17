---
phase: 16
title: "Conversational polish layer for context lines and re-asks"
status: pending
priority: P3
effort: "1.5d"
dependencies: [15]
---

# Phase 16: Conversational polish layer for context lines and re-asks

## Overview

`ask_slot`'s context lines and re-asked questions are emitted verbatim every time, so a user
who answers imprecisely twice reads the identical sentence twice. This phase adds a narrow LLM
rewrite layer: **code decides what to say, the model decides how to say it.** First-ask
questions stay untouched.

## Problem

Every string `ask_slot` emits is a fixed `t()` lookup. Three of them repeat on consecutive
turns by construction:

- `"Mình chưa hiểu rõ ý bạn ở câu trả lời trước."` (`ask_slot.py:167`) — fires on every re-ask;
- `"Đã cập nhật: {joined}."` (`:133`) — fires on every turn a change lands while another slot
  is pending;
- the slot question itself, re-rendered identically by `_render_question`.

Repeating a sentence word-for-word is the clearest tell that nothing is listening. This is a
polish problem, not a correctness one — which is why it is P3 and strictly downstream of
Phase 15, where the actual defect lives.

### Why the first ask is excluded

`test_ask_slot.py:53-59` asserts the dates question is byte-identical with the frontend's
`intakeDatesQuestion`. `ask_slot.py:91-95` records why: frontend and backend previously asked
different things while the extractor was primed for a third, and Phase 7 unified them.
Rewriting the first ask would re-open exactly that defect.

The re-ask branch has no such contract — by then the user has already read the canonical
wording and it did not work.

### The phrasing that carries load

`prompts.py:74` teaches the extractor to accept `"không cần lọc theo giá"` as a valid budget
answer, and `_render_budget` (`ask_slot.py:78-82`) is what puts that phrase in front of the
user. A rewrite that drops it degrades extraction **silently** — no test fails, and the
symptom surfaces somewhere else entirely (a user stuck in a budget loop). Same for
`_context_line`'s rejection reason (`ask_slot.py:157-163`), which is a factual claim lifted
from `rejected_changes`, not free prose.

## Requirements

- Functional: `_context_line` output (`"Đã cập nhật…"`, the rejection reason, `"chưa hiểu rõ"`)
  goes through the rewrite layer on every turn it is produced.
- Functional: the slot question goes through the rewrite layer **only** on the re-ask branch —
  the slot was already in the previous turn's `missing_slots`.
- Functional: a slot's first ask is never rewritten; `_render_question`'s output reaches the
  user unchanged.
- Functional: every rewrite call is bounded by a timeout; on timeout or any exception the
  template text is used. Per the accepted design decision, output **content is not validated** —
  see Risk Assessment.
- Functional: the prompt is given the phrases that must survive (the budget hint, the rejection
  reason) as an explicit instruction. This is prompt guidance, not a post-hoc check.
- Non-functional: the model is injected, never constructed inside the render path, so tests and
  `eval/harness/` can run the deterministic template path without stubbing a factory.
- Non-functional: gettext stays the source of every template string. This layer rewrites `t()`
  output; it does not replace `t()`.
- Non-functional: at most one rewrite call per turn — the context line and the re-asked question
  are rewritten together, not separately.

## Architecture

### Placement

Rewriting happens in `ask_slot` after `_render_question` and `_context_line`, on the fully
assembled text. Rendering already lives here rather than in `domain/slot_registry.py` (Phase 3
purity), so the layer inherits that boundary for free.

```python
def ask_slot(state, *, rewriter: Rewriter | None = None) -> dict[str, Any]:
    ...
    question = _render_question(spec, pending, language)
    context = _context_line(state, spec, language)
    is_reask = spec.name in (state.get("missing_slots") or [])
    full_text = _polish(context, question, rewrite_question=is_reask,
                        rewriter=rewriter, language=language)
```

`rewriter` defaults to `None` — the deterministic path — and is supplied by `graph.py` at node
registration. This is the test seam; without it every existing test and the eval harness become
non-deterministic.

### Re-ask detection

`state["missing_slots"]` still holds the **previous** turn's pending set at this point, because
`load_context` deliberately never resets it (`load_context.py:12-18`). `_context_line` already
uses that exact signal to choose its "didn't catch that" framing, so the two decisions stay
derived from one fact rather than drifting apart.

### Failure policy

Timeout (target ~800ms) → template. Any exception → template. Every fallback logs at warning
with the slot name so the rate is observable. No content assertions.

## Related Code Files

- Create: `backend/src/services/reply_polish.py` — `Rewriter` protocol, timeout wrapper, prompt
- Create: `backend/tests/test_reply_polish.py`
- Modify: `backend/src/agents/graph/nodes/ask_slot.py` — `rewriter` parameter, `_polish`, re-ask
  detection
- Modify: `backend/src/agents/graph/graph.py` — inject the real rewriter at node registration
- Modify: `backend/tests/test_ask_slot.py` — **additions only**, exercising the injected-fake
  path; existing assertions unchanged

## Implementation Steps

1. Add `services/reply_polish.py`: a `Rewriter` protocol, a `polish(text, *, must_keep, timeout)`
   function wrapping `get_fast_llm`, and the prompt. Return the input unchanged on timeout or
   exception.
2. Add the `rewriter` keyword parameter to `ask_slot`, defaulting to `None`. With `None`,
   behavior is byte-identical to today — verify by running `test_ask_slot.py` before touching
   anything else.
3. Add `_polish`: rewrite the context line always; include the question only when
   `spec.name` is in the previous turn's `missing_slots`.
4. Pass the must-keep phrases through — the budget hint for `budget`, the rejection reason when
   `_context_line` produced one.
5. Inject the real rewriter in `graph.py`'s `ask_slot` registration.
6. Add `test_reply_polish.py`: timeout falls back to the input; exception falls back to the
   input; fallbacks are logged.
7. Add tests to `test_ask_slot.py` with a fake rewriter: first ask is never passed to it,
   re-ask is, context line always is.
8. Run the full suite plus `eval/harness/score_state_patches.py`.

## Success Criteria

- [ ] With `rewriter=None`, `ask_slot` output is byte-identical to Phase 15's — the three
      existing `test_ask_slot.py` assertions pass unmodified
- [ ] A fake rewriter receives the context line on every turn that produces one
- [ ] A fake rewriter receives the question **only** on the re-ask branch, never on a first ask
- [ ] A rewriter that sleeps past the timeout produces the exact template text and one warning log
- [ ] A rewriter that raises produces the exact template text and one warning log
- [ ] At most one rewrite call per turn (asserted on the fake's call count)
- [ ] `eval/harness/score_state_patches.py` runs the deterministic path and scores no lower
      than Phase 15

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| **Rewrite drops the budget hint phrase → extraction degrades silently.** No test fails; the symptom appears as users stuck in a budget loop | **High — accepted, not mitigated** | User decision: timeout only, no content validation. Prompt-level "must keep" instruction is guidance the model may ignore. Detection is indirect: watch `score_state_patches` and the budget-slot re-ask rate. A 5-line assertion that the phrase survived would close this and remains the recommended change if the risk materializes |
| Rewrite alters the rejection reason into a false statement about why input was rejected | Medium | Reason text is passed as must-keep; same accepted no-validation caveat applies |
| No feature flag → the only rollback is reverting the PR | Medium | Keep the phase in its own commit with no unrelated changes so revert is clean. The `rewriter=None` default means a one-line change at the `graph.py` injection site also disables it |
| Latency added to every turn that produces a context line | Low | Single call, `get_fast_llm`, ~800ms ceiling with template fallback |
| Non-deterministic output leaks into the eval harness | Low | Injection seam: the harness and all tests run with `rewriter=None` |
| Layer grows to cover `budget_check`, `trip_formatter`, worker replies | Low | Explicit non-goal. Those emit figures and trip facts, where rewriting risks misstating data |
