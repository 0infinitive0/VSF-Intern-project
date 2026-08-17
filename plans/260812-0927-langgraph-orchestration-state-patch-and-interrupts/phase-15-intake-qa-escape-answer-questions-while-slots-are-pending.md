---
phase: 15
title: "Intake QA escape: answer questions while slots are pending"
status: completed
priority: P1
effort: "1.5d"
dependencies: [7, 11]
---

# Phase 15: Intake QA escape: answer questions while slots are pending

## Overview

While any required slot is still missing, the graph physically cannot answer a user's
question — the `ask_slot` conditional edge short-circuits to `respond`, so no worker runs.
This phase adds a read-only `intake_qa` node on that branch so a question asked mid-intake
gets an answer **and** the pending question in the same turn.

## Problem

`graph.py:107` wires `ask_slot` through `route_ask_slot` (`routing.py:58-64`), which returns
`"ask"` — straight to `respond` — for every turn where `missing_slots` is non-empty. The
supervisor and all four workers, `qa_node` included, are unreachable for the whole intake
phase.

So a legitimate question during intake ("Đà Nẵng tháng 7 mưa không?") runs:

1. `extract_patch` classifies `general_question`, emits zero changes;
2. `apply_patch` commits nothing;
3. `ask_slot` sees the slot still missing and — because the slot was already in the previous
   turn's `missing_slots` — prefixes `"Mình chưa hiểu rõ ý bạn ở câu trả lời trước."`
   (`ask_slot.py:165-167`) before re-asking.

The user asked a perfectly clear question and the bot blames them for it. This is the same
failure family as Goal 2 ("No pending question can deadlock the conversation"): Phase 7 fixed
a pending question blocking an unrelated **fact**; it still blocks an unrelated **question**.

### Why this is a routing fix, not a text fix

Replacing `ask_slot`'s hardcoded strings with LLM-generated ones changes nothing here: the
node still runs, still returns a question, and `respond.py:165` still gives `next_question`
absolute priority. The bot would ask more fluently and stay just as deaf.

### Three constraints the design must respect

| Constraint | Evidence |
|---|---|
| `intent == "general_question"` is **not** a reliable "user asked something" signal | `extract_patch.py:317-318` returns it after all retries fail; `:324` returns it for an empty message. Routing on it as-is would send a parse failure or a provider outage to an LLM to answer confidently |
| `qa_node` cannot be reused | It shares only the `messages` channel with the parent graph (`qa_node.py` docstring), so it cannot read `travel_state` and cannot know which slot is pending. Its tools are also wrong for intake: `query_hotel`/`query_hotel_rooms` have nothing to query before any search has run |
| `respond` swallows any answer produced before it | `respond.py:165` — `next_question` wins over `task_results` and `messages` unconditionally |

### This does not overturn a recorded decision

`plan.md`'s "Decided while planning" table already says: *"Does `intent` pick the worker? **No.**
Worker selection is `detect_impact(changes)` → `WORKFLOW_TO_WORKER`… `intent` only separates
read-only Q&A from state-changing turns."* Separating read-only Q&A is exactly what this phase
uses it for. The narrower claim lives only in `state.py:37`'s comment (*"audit trail only,
never routes"*) and the doc §36 line it cites; both need their wording corrected to match the
decision that was actually made.

## Requirements

- Functional: when required slots are missing **and** the turn is a genuine read-only question,
  the reply contains both the answer and the pending slot question, in that order.
- Functional: an extraction failure or an empty message never routes to `intake_qa` — it falls
  through to the existing `"ask"` branch, and the failure stays visible in logs.
- Functional: `intake_qa` is strictly read-only. It never writes `travel_state`, `patch`, or
  `applied_changes`; it runs after `apply_patch`, so a write there would bypass `validate_patch`
  entirely.
- Functional: first-ask slot question text is unchanged — byte-identical with the frontend's
  `intakeDatesQuestion`, per Phase 7's contract.
- Functional: `intake_qa` never asks a slot question itself; `ask_slot` remains the sole owner
  of `next_question`.
- Non-functional: at most one extra LLM call per turn, only on the question branch. A turn that
  answers the slot normally still makes exactly one call (`extract_patch`).
- Non-functional: every existing test passes **without modification**, including the three
  byte-identical assertions in `test_ask_slot.py`.

## Architecture

### Flow

```
apply_patch → ask_slot ─┬─ missing_slots empty ──────────────→ supervisor
                        ├─ question, extraction OK ─→ intake_qa ─→ respond
                        └─ otherwise ("ask") ───────────────────→ respond
```

`intake_qa` sits **after** `ask_slot`, not before it, so `next_question` and `missing_slots`
already exist when it runs. That lets its prompt say "the user will also be asked X right
after you" and forbid it from asking X itself — the composition problem is solved by ordering,
not by a second coordination mechanism.

### State keys

Two new fields in `TravelGraphState`, both reset by `load_context` (turn-scoped, same as
`intent`):

| Key | Writer | Purpose |
|---|---|---|
| `extraction_failed: bool` | `extract_patch` | Separates "LLM/provider failed" from "user genuinely asked nothing" — both currently collapse to `intent == "general_question"` |
| `intake_answer: str \| None` | `intake_qa` | The answer text, kept out of `task_results` because `intake_qa` is not a worker and consumes no `pending_tasks` entry |

### Routing predicate

```python
def route_ask_slot(state: TravelGraphState) -> str:
    if not state.get("missing_slots"):
        return "supervisor"
    if state.get("intent") == "general_question" and not state.get("extraction_failed"):
        return "intake_qa"
    return "ask"
```

`intent == "general_question"` with `extraction_failed` false means the extractor ran, parsed,
and concluded the message changes nothing — the only state in which "this is a question" is a
claim rather than a guess.

### Reply composition

`respond` composes instead of short-circuiting:

```python
reply = (
    _compose(state.get("intake_answer"), state.get("next_question"))
    or _reply_from_task_results(state)
    or _reply_from_messages(state)
    or ack
)
```

`_compose` joins with a blank line when both are present and returns whichever is present
otherwise, so the existing precedence is unchanged on every path that has no `intake_answer`.

### The node

One `get_fast_llm` call, no tools, no retry loop. The prompt receives the rendered
`travel_state` facts, the user's message, and the `next_question` about to be appended, and is
instructed to answer briefly, admit ignorance rather than invent trip facts, and never ask for
a slot. Prompt builder lives in `agents/graph/prompts.py` beside the supervisor and
extract_patch prompts. On any exception the node returns `{"intake_answer": None}` and the turn
degrades to today's behavior.

## Related Code Files

- Create: `backend/src/agents/graph/nodes/intake_qa.py`
- Create: `backend/tests/test_intake_qa.py`
- Modify: `backend/src/agents/graph/state.py` — add `extraction_failed`, `intake_answer`; fix the
  `intent` comment on `:37`
- Modify: `backend/src/agents/graph/nodes/load_context.py` — reset both new keys
- Modify: `backend/src/agents/graph/nodes/extract_patch.py` — set `extraction_failed` on `:317-318`
  and `:324`
- Modify: `backend/src/agents/graph/routing.py` — third branch in `route_ask_slot`
- Modify: `backend/src/agents/graph/graph.py` — register node, extend the conditional edge map,
  edge to `respond`
- Modify: `backend/src/agents/graph/nodes/respond.py` — `_compose` instead of `next_question`
  short-circuit
- Modify: `backend/src/agents/graph/prompts.py` — `build_intake_qa_prompt`
- Modify: `data/travel_chatbot_langgraph_production_architecture.md` §36 — correct the
  "intent never routes" wording

## Implementation Steps

1. Add `extraction_failed: bool` and `intake_answer: str | None` to `TravelGraphState`; reset
   both in `load_context`. Correct the `intent` comment on `state.py:37` to match `plan.md`'s
   recorded decision.
2. Set `extraction_failed=True` on both failure returns in `extract_patch` (`:317-318` retry
   exhaustion, `:324` empty message). Leave `intent` as-is so every existing consumer and the
   audit trail are untouched.
3. Write the failing test first: `extraction_failed=True` with pending slots must route to
   `"ask"`, not `"intake_qa"`. Add the third branch to `route_ask_slot` until it passes.
4. Add `build_intake_qa_prompt` to `prompts.py`.
5. Write `nodes/intake_qa.py` — one call, no tools, read-only, returns `{"intake_answer": ...}`
   or `{"intake_answer": None}` on any exception.
6. Wire it in `graph.py`: `add_node`, extend the `ask_slot` conditional map with
   `"intake_qa": "intake_qa"`, `add_edge("intake_qa", "respond")`.
7. Add `_compose` to `respond.py` and put it at the head of the reply chain.
8. Add `test_intake_qa.py` with an injected fake model: question-during-intake produces a reply
   containing both parts; `intake_qa` returns no state keys other than `intake_answer`.
9. Run the full backend suite and confirm `test_ask_slot.py`, `test_graph_v2_skeleton.py`,
   `test_legacy_guards.py` pass with zero test-file edits.

## Success Criteria

- [x] `test_ask_slot.py`, `test_graph_v2_skeleton.py`, `test_legacy_guards.py` pass with **0
      lines of test code changed**
- [x] Asking "Đà Nẵng tháng 7 mưa không?" while `dates.*` are missing yields a reply containing
      both the answer and the date question, and **0** occurrences of "chưa hiểu rõ ý bạn"
- [x] Forcing `_extract_with_llm` to raise routes to `"ask"`, never `"intake_qa"`, and emits the
      existing extraction-failure warning
- [x] `intake_qa` returns no key other than `intake_answer` (asserted directly on the node's
      return value)
- [x] An intake turn **without** a question still makes exactly one LLM call
- [x] `eval/harness/score_state_patches.py` score is not lower than on `main`
- [x] `git diff --stat` touches none of `supervisor.py`, `qa_node.py`,
      `prompts.py::SUPERVISOR_SYSTEM_PROMPT`, or any `.po`/`.mo` file

### Post-review additions (not in the original design, required to actually meet the above)

A `code-reviewer` pass on the first implementation found two defects the plan's own design
didn't anticipate, both fixed before this phase was marked done:

- **`ask_slot` still blamed the user.** `route_ask_slot`'s new branch only changes where the
  turn goes; `ask_slot` itself computes its "Mình chưa hiểu rõ ý bạn ở câu trả lời trước." prefix
  *before* that routing decision runs, off the same carried-over `missing_slots` a genuine
  question also leaves untouched. Without a fix, criterion 2 above failed on any turn past a
  thread's first (a single-turn test can't catch this — nothing was "previously pending" yet).
  Fixed by extracting the routing predicate to `routing.is_intake_question` and having
  `ask_slot._context_line` skip its re-ask framing when it's true.
- **`general_question` over-fires past real questions.** `extract_patch`'s own prompt documents
  `general_question` as a catch-all for "anything that changes nothing" — greetings,
  acknowledgements, and short replies the pending-slot anchor fails to rescue all land there too,
  not only genuine questions. Routing every such turn to `intake_qa` risked fabricated chatter
  ("You're welcome!" to "cảm ơn") and an uncounted extra LLM call. Contained (not eliminated —
  the underlying classifier is out of this phase's scope, see `plan.md`'s recorded decision on
  `intent`) by giving `intake_qa`'s own prompt an escape hatch: reply with the literal sentinel
  `NO_ANSWER` when the message isn't actually a question, which the node maps back to
  `{"intake_answer": None}`.

Both are covered by new tests in `test_intake_qa.py`: a same-thread two-turn graph test (the
only way to reproduce the first bug), a direct `ask_slot` unit test for the suppression plus its
inverse (blame line still fires for a genuine unrecognized reply), and a `NO_ANSWER` sentinel
test.

## Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| `intake_qa` invents trip facts (weather, prices, availability) it has no source for | High | Prompt requires admitting ignorance over guessing; node is read-only so nothing it says can enter `travel_state`. A wrong sentence is a wrong sentence, never a corrupted fact |
| Routing on `intent` re-couples classification to control flow, the coupling Phase 6 removed | Medium | Scoped to one read-only branch that selects **no worker** — consistent with the recorded decision that `intent` separates read-only Q&A. Worker selection stays `detect_impact` |
| `intake_qa` and `qa_node` drift into two divergent answering prompts | Medium | Note the overlap in both docstrings; revisit merging once `qa_node` can read `travel_state` |
| Extra latency on the question branch | Low | `get_fast_llm`, no tools, no retry — one round trip, only when a question was actually detected |
| `_compose` changes reply precedence for paths that never intended it | Low | `_compose` returns `None` when `intake_answer` is absent, leaving the existing chain byte-identical; covered by the untouched existing tests |
