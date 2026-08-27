"""Phase 15 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`route_ask_slot`'s third branch, the `intake_qa` node it feeds, and
`ask_slot`'s suppression of its "didn't catch that" framing on that branch.

No test here calls a real model — `get_fast_llm`/`get_reasoning_llm` are
monkeypatched on the node modules in every case that could reach them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import HumanMessage

import src.agents.graph.nodes.ask_slot as ask_slot_module
import src.agents.graph.nodes.extract_patch as extract_patch_module
import src.agents.graph.nodes.intake_qa as intake_qa_module
from src.agents.graph.graph import build_graph
from src.agents.graph.nodes.ask_slot import ask_slot
from src.agents.graph.nodes.intake_qa import intake_qa
from src.agents.graph.nodes.qa_node import QA_SYSTEM_PROMPT
from src.agents.graph.nodes.respond import respond
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL, build_intake_qa_prompt
from src.agents.graph.routing import is_incomplete_edit, is_intake_question, route_ask_slot, route_intake_qa
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.services.trip_intake import _COMPANION_LABELS, _DAY_RHYTHM_LABELS, _PACE_LABELS, _PREFERENCE_LABELS

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
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _FakeResponse:
        self.call_count += 1
        self.prompts.append(prompt)
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


# --- is_incomplete_edit / route_ask_slot's post-intake branch (Phase 16) ----
#
# Baseline clears every guard: no missing slots, an included intent, an
# empty patch, no pending worker, `patch_reason == "missing_value"`. Each
# row changes exactly one field off that baseline.

_BASELINE_CLARIFY_STATE = dict(
    missing_slots=[],
    intent="update_itinerary",
    patch=[],
    pending_tasks=[],
    patch_reason="missing_value",
)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "intake_qa"),
        ({"intent": "update_trip"}, "intake_qa"),
        ({"intent": "hotel_search"}, "supervisor"),  # excluded intent (guard 1)
        ({"intent": "select_hotel"}, "supervisor"),
        ({"intent": "finalize"}, "supervisor"),
        ({"patch_reason": "no_change"}, "supervisor"),  # guard 2
        ({"patch_reason": ""}, "supervisor"),  # fail-open
        ({"patch": [{"path": "people", "operation": "set", "value": 2}]}, "supervisor"),
        ({"pending_tasks": ["hotel_node"]}, "supervisor"),
        ({"extraction_failed": True}, "supervisor"),
    ],
)
def test_route_ask_slot_post_intake_branch(overrides: dict, expected: str) -> None:
    state = _state(**{**_BASELINE_CLARIFY_STATE, **overrides})
    assert route_ask_slot(state) == expected


def test_route_ask_slot_post_intake_branch_with_patch_reason_key_absent_entirely() -> None:
    """Fail-open by omission, not just by an explicit empty string -- the
    row that proves an un-upgraded model breaks nothing. `_state()` builds
    on `initial_graph_state`, which itself defaults `patch_reason` to ""
    (`load_context`'s own per-turn reset does the same) -- popping the key
    is the only way to simulate a state that predates this field."""
    state = _state(**_BASELINE_CLARIFY_STATE)
    del state["patch_reason"]
    assert "patch_reason" not in state
    assert route_ask_slot(state) == "supervisor"


def test_route_ask_slot_missing_slots_outranks_the_clarify_branch() -> None:
    """Intake still gates first even when every clarify guard would
    otherwise pass -- `ask_slot` stays the sole owner of the intake gate."""
    state = _state(**{**_BASELINE_CLARIFY_STATE, "missing_slots": ["dates.start"]})
    assert route_ask_slot(state) == "ask"


def test_route_ask_slot_missing_slots_with_a_question_still_routes_to_intake_qa() -> None:
    """Unchanged mid-intake behavior: the third branch from Phase 15 is
    untouched by Phase 16's addition."""
    state = _state(
        **{**_BASELINE_CLARIFY_STATE, "missing_slots": ["dates.start"], "intent": "general_question"}
    )
    assert route_ask_slot(state) == "intake_qa"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"intent": "update_trip"}, True),
        ({"intent": "hotel_search"}, False),
        ({"patch_reason": "no_change"}, False),
        ({"patch": [{"path": "people", "operation": "set", "value": 2}]}, False),
        ({"pending_tasks": ["hotel_node"]}, False),
        ({"extraction_failed": True}, False),
    ],
)
def test_is_incomplete_edit(overrides: dict, expected: bool) -> None:
    state = _state(**{**_BASELINE_CLARIFY_STATE, **overrides})
    assert is_incomplete_edit(state) is expected


# --- route_intake_qa: "no answer" means something different on each entry --


@pytest.mark.parametrize(
    ("missing_slots", "intake_answer", "expected"),
    [
        (["dates.start"], None, "respond"),  # intake: pending question must still go out
        (["dates.start"], "Tháng 7 có mưa.", "respond"),
        ([], "Bạn muốn đổi thành gì?", "respond"),  # post-intake: a real answer
        ([], None, "supervisor"),  # post-intake, declined/failed: safety net
    ],
)
def test_route_intake_qa(missing_slots: list[str], intake_answer: str | None, expected: str) -> None:
    state = _state(missing_slots=missing_slots, intake_answer=intake_answer)
    assert route_intake_qa(state) == expected


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


# --- build_intake_qa_prompt: intake vs clarify mode (Phase 16) --------------
#
# No test here calls a real model -- these assert on the built string only.

# Copied verbatim from the `_INTAKE_QA_SYSTEM_PROMPT` literal -- an
# independent record of "today's output", not derived from the module under
# test, so a refactor that silently changes the rendered text fails this
# instead of passing vacuously.
_INTAKE_MODE_PROMPT = """You are a trip-planning assistant answering one user question while some trip details are still being collected. Answer briefly and only from what you actually know -- if you don't know something (weather, prices, availability, real-time facts), say so plainly instead of guessing.

The message reaches you because an upstream classifier flagged it as "changes nothing about the trip" -- that classifier catches real questions, but ALSO greetings, acknowledgements ("ok", "cảm ơn"), and short replies it failed to connect to the pending question below. You must tell those apart: if the message does not actually ask something worth answering, reply with exactly the single word NO_ANSWER and nothing else -- do not greet back, do not comment, do not apologize.

Rules:
- Only travel planning for this trip is yours to answer. A request for anything else -- solving maths or homework, writing or debugging code, any unrelated topic -- gets one short sentence declining it and naming what you can help with instead. Do not lecture, and do not attempt it partially.
- Flights are not covered by this product at all: no flight search, schedules, prices, or booking. Say that plainly instead of guessing.
- Arithmetic about the trip itself ("chia 3 triệu cho 3 ngày", totalling costs) and a hotel near an airport are ordinary travel questions -- answer those normally.
- Never invent a trip fact (destination, dates, budget, preferences) -- only use what is listed below as already known.
- Never ask the user for any information yourself. Right after your answer, the assistant will separately ask: "{next_question}" -- do not repeat, rephrase, or anticipate that question.
- Keep the answer short (1-3 sentences).
- Reply in {language_name}.

Already known so far: {known_facts}

User's message: "{message}"
"""


def test_build_intake_qa_prompt_default_renders_intake_mode_byte_for_byte() -> None:
    message = "Đà Nẵng tháng 7 mưa không?"
    known_facts = "destination=Đà Nẵng"
    next_question = "Bạn dự định đi và về ngày nào?"
    expected = _INTAKE_MODE_PROMPT.format(
        next_question=next_question, known_facts=known_facts, message=message, language_name="Vietnamese"
    )

    actual = build_intake_qa_prompt(
        message=message, known_facts=known_facts, next_question=next_question, language="vi"
    )

    assert actual == expected
    # No `clarify` argument at all is the same call every pre-Phase-16 site
    # already makes -- must default to intake mode, not raise or clarify.
    assert actual == build_intake_qa_prompt(
        message=message, known_facts=known_facts, next_question=next_question, language="vi", clarify=False
    )


def test_intake_mode_contains_the_no_ask_rule_and_the_pending_question() -> None:
    prompt = build_intake_qa_prompt(
        message="Đà Nẵng tháng 7 mưa không?",
        known_facts="destination=Đà Nẵng",
        next_question="Bạn dự định đi và về ngày nào?",
        language="vi",
        clarify=False,
    )
    assert "Never ask the user for any information yourself" in prompt
    assert "Bạn dự định đi và về ngày nào?" in prompt


def test_clarify_mode_contains_neither_the_no_ask_rule_nor_the_pending_question() -> None:
    prompt = build_intake_qa_prompt(
        message="đổi theme ngày 1",
        known_facts="destination=Đà Nẵng",
        next_question="Bạn dự định đi và về ngày nào?",  # stale value must not leak in
        language="vi",
        clarify=True,
    )
    assert "Never ask the user for any information yourself" not in prompt
    assert "Bạn dự định đi và về ngày nào?" not in prompt


# --- out-of-scope refusal, prompt layer -------------------------------------
#
# `guardrails/scope.py` was never built, so these clauses are the only
# control on the intake and QA branches -- a refactor that drops one silently
# re-opens maths/code/flight answering. Both modes carry them, and so does
# `qa_node`, the post-intake branch.


@pytest.mark.parametrize("clarify", [False, True])
def test_both_intake_modes_refuse_out_of_scope_requests(clarify: bool) -> None:
    prompt = build_intake_qa_prompt(
        message="giải phương trình x^2+2x+1=0",
        known_facts="destination=Đà Nẵng",
        next_question="Bạn dự định đi và về ngày nào?",
        language="vi",
        clarify=clarify,
    )
    assert "Only travel planning for this trip is yours to answer" in prompt
    assert "Flights are not covered by this product" in prompt
    # The false-positive guard travels with the refusal, never separately.
    assert "are ordinary travel questions" in prompt


def test_qa_node_prompt_refuses_out_of_scope_requests() -> None:
    assert "Only travel questions about this trip are yours to answer" in QA_SYSTEM_PROMPT
    assert "Flights are not part of this product" in QA_SYSTEM_PROMPT
    assert "are ordinary travel questions — answer those normally" in QA_SYSTEM_PROMPT


def test_clarify_mode_offers_every_closed_set_label_from_the_imported_vocabulary() -> None:
    prompt = build_intake_qa_prompt(
        message="đổi theme ngày 1", known_facts="", next_question="", language="vi", clarify=True
    )
    for label in (*_PREFERENCE_LABELS, *_COMPANION_LABELS, *_PACE_LABELS, *_DAY_RHYTHM_LABELS):
        assert label in prompt


def test_clarify_mode_contains_the_no_answer_sentinel_instruction() -> None:
    prompt = build_intake_qa_prompt(
        message="đổi theme ngày 1", known_facts="", next_question="", language="vi", clarify=True
    )
    assert INTAKE_QA_NO_ANSWER_SENTINEL in prompt
    assert "REDO work" in prompt


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


def test_intake_qa_passes_clarify_true_when_no_slot_is_missing(monkeypatch) -> None:
    """Read from state, not recomputed -- proves the node's `clarify` flag
    tracks `missing_slots` the same way `route_ask_slot` does, so the two
    can never disagree about which entry point a turn came through."""
    llm = _FakeLLM("Bãi biển hoặc thiên nhiên, bạn muốn ngày 1 theo hướng nào?")
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: llm)
    state = _state(
        travel_state={"destination": {"presence": "set", "value": "Đà Nẵng"}},
        messages=[HumanMessage(content="đổi theme ngày 1")],
        missing_slots=[],
    )

    intake_qa(state)

    assert "named no value to change it to" in llm.prompts[0]
    assert "Never ask the user for any information yourself" not in llm.prompts[0]


def test_intake_qa_passes_clarify_false_while_a_slot_is_still_missing(monkeypatch) -> None:
    llm = _FakeLLM("Tháng 7 Đà Nẵng có mưa rải rác.")
    monkeypatch.setattr(intake_qa_module, "get_fast_llm", lambda **_kwargs: llm)
    state = _state(
        travel_state=_DATES_MISSING,
        messages=[HumanMessage(content="Đà Nẵng tháng 7 mưa không?")],
        missing_slots=["dates.start", "dates.end"],
        next_question="Bạn dự định đi và về ngày nào?",
    )

    intake_qa(state)

    assert "Never ask the user for any information yourself" in llm.prompts[0]
    assert "named no value to change it to" not in llm.prompts[0]


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


def test_question_during_intake_is_answered_without_repeating_the_last_question(monkeypatch) -> None:
    """Turn 1 leaves `dates.*` pending (so `missing_slots` carries them into
    the checkpoint); turn 2, on the SAME thread, asks a genuine question
    about one of those still-pending slots. This is the scenario the blame
    line only fires on -- a fresh thread's first turn never has a
    previously-pending slot to misfire against, so a single-turn test would
    pass identically whether or not the suppression exists.

    Turn 1 already put the dates question on screen, so turn 2 answers and
    stops there; turn 3 asks again and, with no question in the reply
    directly above it, the dates question comes back. The intake never goes
    two consecutive replies without a way forward, and never repeats the
    identical question back-to-back."""

    extract_llm = _FakeLLM(
        [
            json.dumps({"intent": "update_trip", "changes": [{"path": "people", "operation": "set", "value": 2}]}),
            json.dumps({"intent": "general_question", "changes": []}),
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
    assert "đi và về" in turn1["response"]["reply"]

    turn2 = app.invoke(
        {"messages": [HumanMessage(content="Đà Nẵng tháng 7 mưa không?")]},
        config=thread,
    )

    reply2 = turn2["response"]["reply"]
    assert "mưa rải rác" in reply2
    assert "đi và về" not in reply2
    assert "chưa hiểu rõ ý bạn" not in reply2

    turn3 = app.invoke(
        {"messages": [HumanMessage(content="Đà Nẵng tháng 7 nóng không?")]},
        config=thread,
    )

    reply3 = turn3["response"]["reply"]
    assert "mưa rải rác" in reply3
    assert "đi và về" in reply3


def test_a_plain_intake_turn_spends_one_extractor_call_and_one_rewording_call(monkeypatch) -> None:
    """The whole LLM budget for a turn that just answers the pending slot:
    one extractor call, one `ask_slot` question rewording, and `intake_qa`
    never running at all. Pinning the total is what stops a third call from
    being added to the intake's hot path without anyone deciding to."""
    extractor = _FakeLLM(json.dumps({"intent": "update_trip", "changes": [{"path": "people", "operation": "set", "value": 2}]}))
    rewording = _FakeLLM("Bạn muốn đi đâu?")

    def _unreachable(**_kwargs):
        raise AssertionError("intake_qa must not run when the message isn't a question")

    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", lambda **_kwargs: extractor)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: ())
    monkeypatch.setattr(ask_slot_module, "get_fast_llm", lambda **_kwargs: rewording)
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

    assert extractor.call_count == 1
    assert rewording.call_count == 1
