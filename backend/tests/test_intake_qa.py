"""Phase 15 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`route_ask_slot`'s third branch, the `intake_qa` node it feeds, and
`ask_slot`'s suppression of its "didn't catch that" framing on that branch.

No test here calls a real model — `get_fast_llm`/`get_reasoning_llm` are
monkeypatched on the node modules in every case that could reach them.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage

import src.agents.graph.nodes.extract_patch as extract_patch_module
import src.agents.graph.nodes.intake_qa as intake_qa_module
from src.agents.graph.graph import build_graph
from src.agents.graph.nodes.ask_slot import ask_slot
from src.agents.graph.nodes.intake_qa import intake_qa
from src.agents.graph.nodes.respond import respond
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL
from src.agents.graph.routing import is_intake_question, route_ask_slot
from src.agents.graph.state import TravelGraphState, initial_graph_state

# destination + people set, dates still missing -- next_question is the
# dates question, matching test_ask_slot.py's own fixture shape.
_DATES_MISSING = {
    "destination": {"presence": "set", "value": "Đà Nẵng"},
    "people": {"presence": "set", "value": 2},
}


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Returns one queued response per `.invoke()` call, in order (mirrors
    `test_extract_patch.py`'s fixture). A single content also works, for
    call sites that only ever invoke once."""

    def __init__(self, contents: str | Exception | list[str]) -> None:
        self._contents = list(contents) if isinstance(contents, list) else [contents]
        self.call_count = 0

    def invoke(self, _prompt: str) -> _FakeResponse:
        self.call_count += 1
        content = self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]
        if isinstance(content, Exception):
            raise content
        return _FakeResponse(content)


def _state(**overrides: Any) -> TravelGraphState:
    state = initial_graph_state("t1")
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


# --- is_intake_question / route_ask_slot's third branch ---------------------


def test_no_missing_slots_routes_to_supervisor() -> None:
    assert route_ask_slot(_state(missing_slots=[])) == "supervisor"


def test_question_with_successful_extraction_routes_to_intake_qa() -> None:
    state = _state(missing_slots=["dates.start"], intent="general_question", extraction_failed=False)
    assert is_intake_question(state) is True
    assert route_ask_slot(state) == "intake_qa"


def test_extraction_failure_routes_to_ask_not_intake_qa() -> None:
    """An unparseable response or provider outage must never be treated as
    a real question."""
    state = _state(missing_slots=["dates.start"], intent="general_question", extraction_failed=True)
    assert is_intake_question(state) is False
    assert route_ask_slot(state) == "ask"


def test_non_question_intent_with_missing_slots_routes_to_ask() -> None:
    state = _state(missing_slots=["dates.start"], intent="update_trip", extraction_failed=False)
    assert route_ask_slot(state) == "ask"


# --- ask_slot: blame-line suppression on the intake_qa branch ---------------
#
# Review finding: routing alone isn't enough -- `ask_slot` computes its
# "didn't catch that" prefix BEFORE `route_ask_slot` runs, off the same
# `missing_slots` carried from the previous turn that a genuine question
# also leaves untouched. Without this suppression, a question mid-intake
# gets answered AND blamed in the same reply.


def test_ask_slot_suppresses_blame_line_when_this_turn_is_a_question() -> None:
    state = _state(
        travel_state=_DATES_MISSING,
        missing_slots=["dates.start", "dates.end"],  # pending at the end of the prior turn too
        intent="general_question",
        extraction_failed=False,
    )
    result = ask_slot(state)
    assert "chưa hiểu rõ ý bạn" not in result["next_question"]


def test_ask_slot_keeps_blame_line_for_a_genuine_unrecognized_reply() -> None:
    """Regression guard: suppression must be scoped to `is_intake_question`
    turns only -- a real unrecognized-answer re-ask keeps its framing."""
    state = _state(
        travel_state=_DATES_MISSING,
        missing_slots=["dates.start", "dates.end"],
        intent="update_trip",
        extraction_failed=False,
    )
    result = ask_slot(state)
    assert "chưa hiểu rõ ý bạn" in result["next_question"]


# --- intake_qa node ----------------------------------------------------------


def test_intake_qa_returns_only_intake_answer(monkeypatch) -> None:
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeLLM("Tháng 7 Đà Nẵng có mưa rải rác."))
    state = _state(
        messages=[HumanMessage(content="Đà Nẵng tháng 7 mưa không?")],
        next_question="Bạn dự định đi và về ngày nào?",
    )

    result = intake_qa(state)

    assert set(result.keys()) == {"intake_answer"}
    assert result["intake_answer"] == "Tháng 7 Đà Nẵng có mưa rải rác."


def test_intake_qa_returns_none_on_llm_exception(monkeypatch) -> None:
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(RuntimeError("provider down")))
    state = _state(messages=[HumanMessage(content="Đà Nẵng tháng 7 mưa không?")])

    result = intake_qa(state)

    assert result == {"intake_answer": None}


def test_intake_qa_returns_none_for_the_no_answer_sentinel(monkeypatch) -> None:
    """The prompt's own escape hatch for a message the upstream classifier
    mislabeled as a question (a greeting, an ack, an unrescued short
    reply) -- containment for `general_question`'s over-inclusion."""
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeLLM(INTAKE_QA_NO_ANSWER_SENTINEL))
    state = _state(messages=[HumanMessage(content="chào bạn")])

    result = intake_qa(state)

    assert result == {"intake_answer": None}


# --- respond._compose: reply carries both parts, in order -------------------


def test_respond_composes_intake_answer_ahead_of_next_question() -> None:
    state = _state(
        intake_answer="Tháng 7 Đà Nẵng có mưa rải rác.",
        next_question="Bạn dự định đi và về ngày nào?",
    )

    result = respond(state)

    reply = result["response"]["reply"]
    assert "mưa rải rác" in reply
    assert "đi và về" in reply
    assert reply.index("mưa rải rác") < reply.index("đi và về")


def test_respond_without_intake_answer_is_unchanged() -> None:
    """No `intake_answer` (every non-Phase-15 path) -- byte-identical to the
    old bare `next_question` short-circuit."""
    state = _state(next_question="Bạn muốn đi đâu?")

    result = respond(state)

    assert result["response"]["reply"] == "Bạn muốn đi đâu?"


# --- End-to-end through the compiled graph -----------------------------------


def test_question_during_intake_answers_and_still_asks_the_pending_slot(monkeypatch) -> None:
    """Turn 1 leaves `dates.*` pending (so `missing_slots` carries them into
    the checkpoint); turn 2, on the SAME thread, asks a genuine question
    about one of those still-pending slots. This is the scenario the blame
    line only fires on -- a fresh thread's first turn never has a
    previously-pending slot to misfire against, so a single-turn test would
    pass identically whether or not the suppression exists."""

    extract_llm = _FakeLLM(
        [
            json.dumps({"intent": "update_trip", "changes": [{"path": "people", "operation": "set", "value": 2}]}),
            json.dumps({"intent": "general_question", "changes": []}),
        ]
    )
    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", lambda **_kwargs: extract_llm)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: _FakeLLM("Tháng 7 Đà Nẵng có mưa rải rác."))

    app = build_graph()
    thread = {"configurable": {"thread_id": "test-intake-qa-two-turn-thread"}}

    turn1 = app.invoke(
        {
            "session_id": "turn-1",
            "language": "vi",
            "travel_state": {"destination": {"presence": "set", "value": "Đà Nẵng"}},
            "messages": [HumanMessage(content="2 người")],
        },
        config=thread,
    )
    assert turn1["missing_slots"] == ["dates.start", "dates.end"]

    turn2 = app.invoke(
        {"messages": [HumanMessage(content="Đà Nẵng tháng 7 mưa không?")]},
        config=thread,
    )

    reply = turn2["response"]["reply"]
    assert "mưa rải rác" in reply
    assert "đi và về" in reply
    assert "chưa hiểu rõ ý bạn" not in reply


def test_intake_turn_without_a_question_makes_exactly_one_llm_call(monkeypatch) -> None:
    """The extractor's own call is the only LLM call when the message just
    answers the pending slot normally -- `intake_qa` never runs."""
    llm = _FakeLLM(json.dumps({"intent": "update_trip", "changes": [{"path": "people", "operation": "set", "value": 2}]}))

    def _unreachable(**_kwargs):
        raise AssertionError("intake_qa must not run when the message isn't a question")

    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", lambda **_kwargs: llm)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", _unreachable)

    app = build_graph()
    app.invoke(
        {
            "session_id": "turn-1",
            "language": "vi",
            "messages": [HumanMessage(content="2 người")],
        },
        config={"configurable": {"thread_id": "test-intake-no-question-thread"}},
    )

    assert llm.call_count == 1
