"""Phase 6 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`extract_patch` — one LLM call producing `{intent, changes[]}`, the
deterministic day-scope rewrite, and the destination/closed-label grounding
`apply_patch`'s own validators don't enforce. No test here calls a real
model — `get_reasoning_llm` and `_get_destination_names` are monkeypatched
on the node module in every case that could reach them.

The doc §34 phrase table tests THIS node's deterministic pipeline (parsing,
day-scope rewrite, grounding), not a real model's comprehension of each
phrase — model accuracy against these phrases is Phase 10's "State Patch
Accuracy" eval, a different kind of test. Each row here simulates a
plausible model response for its phrase and asserts the pipeline turns it
into the correct final patch (or correctly rejects it).
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import src.agents.graph.nodes.extract_patch as extract_patch_module
from src.agents.graph.nodes.extract_patch import PatchExtractionError, extract_patch
from src.agents.graph.state import initial_graph_state
from src.domain.travel_state import TravelState
from src.services.trip_intake import DestinationOption

_DESTINATIONS = (DestinationOption("Đà Nẵng"), DestinationOption("Hội An", aliases=("HA",)))


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Returns one queued response per `.invoke()` call, in order."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.call_count = 0

    def invoke(self, _prompt: str) -> _FakeResponse:
        self.call_count += 1
        return _FakeResponse(self._contents.pop(0))


def _payload(intent: str, changes: list[dict] | None = None) -> str:
    return json.dumps({"intent": intent, "changes": changes or []})


def _state(message: str, *, travel_state: dict | None = None) -> dict:
    state = initial_graph_state("t1")
    state["messages"] = [HumanMessage(content=message)]
    if travel_state is not None:
        state["travel_state"] = travel_state
    return state


def _patch(monkeypatch, llm: _FakeLLM, destinations: tuple = _DESTINATIONS) -> _FakeLLM:
    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", lambda **_kwargs: llm)
    monkeypatch.setattr(extract_patch_module, "_get_destination_names", lambda: destinations)
    return llm


# --- Call-count invariants ---------------------------------------------------


def test_valid_response_makes_exactly_one_llm_call(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM([_payload("update_trip", [{"path": "people", "operation": "set", "value": 4}])]))
    result = extract_patch(_state("đi 4 người"))

    assert llm.call_count == 1
    assert result["patch"] == [{"path": "people", "operation": "set", "value": 4}]
    assert result["intent"] == "update_trip"


def test_invalid_json_retries_once_then_falls_back_without_raising(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM(["not json", "still not json"]))
    result = extract_patch(_state("asdkjasd"))

    assert llm.call_count == 2
    assert result == {"patch": [], "intent": "general_question"}


def test_invalid_first_response_recovers_on_retry(monkeypatch):
    llm = _patch(
        monkeypatch,
        _FakeLLM(["not json", _payload("general_question", [])]),
    )
    result = extract_patch(_state("chào bạn"))

    assert llm.call_count == 2
    assert result == {"patch": [], "intent": "general_question"}


def test_no_human_message_short_circuits_without_calling_the_llm(monkeypatch):
    def _unreachable(**_kwargs):
        raise AssertionError("no human message -> the LLM must never be called")

    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", _unreachable)
    state = initial_graph_state("t1")
    state["messages"] = [AIMessage(content="a stale reply from a previous turn")]

    result = extract_patch(state)

    assert result == {"patch": [], "intent": "general_question"}


# --- Structural validation ---------------------------------------------------


def test_invalid_intent_label_is_rejected():
    with pytest.raises(PatchExtractionError):
        extract_patch_module._parse_extraction_payload({"intent": "not_a_real_intent", "changes": []})


def test_change_missing_operation_is_rejected():
    with pytest.raises(PatchExtractionError):
        extract_patch_module._parse_extraction_payload(
            {"intent": "update_trip", "changes": [{"path": "people", "value": 2}]}
        )


def test_non_object_payload_is_rejected():
    with pytest.raises(PatchExtractionError):
        extract_patch_module._parse_extraction_payload(["not", "a", "dict"])


# --- Destination grounding: apply_patch's own validator does NOT do this ---


def test_hallucinated_destination_is_dropped(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "destination", "operation": "set", "value": "Atlantis"}])]),
    )
    result = extract_patch(_state("đi Atlantis"))

    assert result["patch"] == []


def test_real_destination_is_kept(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}])]),
    )
    result = extract_patch(_state("đi Đà Nẵng"))

    assert result["patch"] == [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]


# --- Closed label grounding: also not enforced by apply_patch's validator --


def test_theme_outside_the_closed_set_is_filtered_out(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("update_trip", [{"path": "preferences.themes", "operation": "set", "value": ["biển", "made_up"]}])]
        ),
    )
    result = extract_patch(_state("tôi thích biển"))

    assert result["patch"] == [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}]


def test_companion_outside_the_closed_set_is_dropped(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("update_trip", [{"path": "preferences.companions", "operation": "set", "value": "một mình con chó"}])]
        ),
    )
    result = extract_patch(_state("đi cùng con chó"))

    assert result["patch"] == []


# --- Corrected slot: no first-non-null-wins trap ----------------------------


def test_an_already_set_slot_can_be_corrected(monkeypatch):
    """The legacy `TripIntakeState.with_message` merge (`self.x or grounded.x`)
    never runs here -- extract_patch has no merge step of its own, so a
    correction for an already-SET slot passes straight through as a `set`,
    and `apply_patch` (Phase 3) always overwrites on `set`."""
    already_set = TravelState.from_dict({"budget.max": {"presence": "set", "value": 10_000_000}}).to_dict()
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "budget.max", "operation": "set", "value": 8_000_000}])]),
    )
    result = extract_patch(_state("budget còn 8 triệu", travel_state=already_set))

    assert result["patch"] == [{"path": "budget.max", "operation": "set", "value": 8_000_000}]


# --- Day-scope rewrite: deterministic, not model-decided --------------------


def test_numeric_day_scope_rewrites_trip_level_theme_to_the_day_path(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["thiên nhiên"]}])]),
    )
    result = extract_patch(_state("Ngày 1 tôi muốn thiên nhiên"))

    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": ["thiên nhiên"]}]


def test_first_day_ordinal_phrase_resolves_to_day_1(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    result = extract_patch(_state("Ngày đầu tôi muốn đi biển"))

    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": ["biển"]}]


def test_last_day_ordinal_phrase_resolves_only_when_trip_length_is_known(monkeypatch):
    known_trip = TravelState.from_dict(
        {
            "dates.start": {"presence": "set", "value": "2026-09-01"},
            "dates.end": {"presence": "set", "value": "2026-09-04"},  # 3-night trip -> day 3 is last
        }
    ).to_dict()
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    result = extract_patch(_state("ngày cuối tôi muốn ra biển", travel_state=known_trip))

    assert result["patch"] == [{"path": "daily_preferences.3.theme", "operation": "set", "value": ["biển"]}]


def test_last_day_ordinal_phrase_does_not_guess_when_trip_length_is_unknown(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    result = extract_patch(_state("ngày cuối tôi muốn ra biển"))

    # No known trip length -> stays at the trip-level path the model proposed,
    # rather than guessing which day is "last".
    assert result["patch"] == [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}]


def test_day_and_theme_in_one_phrase_produces_the_day_scoped_change(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "daily_preferences.1.theme", "operation": "set", "value": "nature"}])]),
    )
    result = extract_patch(_state("Ngày 1 nature"))

    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": "nature"}]


def test_ambiguous_reference_without_a_day_keyword_is_not_forced_into_a_day_path(monkeypatch):
    """'Cái thứ 2' has no ngày/hôm/day keyword -- reference resolution to
    'the 2nd option' is out of this phase's scope, but it must not be
    misread as a day scope either."""
    _patch(monkeypatch, _FakeLLM([_payload("general_question", [])]))
    result = extract_patch(_state("Cái thứ 2"))

    assert result["patch"] == []
    assert result["intent"] == "general_question"


def test_non_theme_change_inside_a_day_scoped_message_is_untouched(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "budget.max", "operation": "set", "value": 2_000_000}])]),
    )
    result = extract_patch(_state("ngày 1 dưới 2 triệu/đêm"))

    assert result["patch"] == [{"path": "budget.max", "operation": "set", "value": 2_000_000}]


def test_lock_day_phrase_passes_through_unchanged(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "locked_days", "operation": "append", "value": 2}])]),
    )
    result = extract_patch(_state("Giữ nguyên ngày 2"))

    assert result["patch"] == [{"path": "locked_days", "operation": "append", "value": 2}]


# --- Remaining doc §34 phrases: pass-through paths, no special grounding ---


@pytest.mark.parametrize(
    ("message", "change"),
    [
        ("Trong vòng 3km", {"path": "hotel_preferences.radius_km", "operation": "set", "value": 3}),
        ("Có gym", {"path": "hotel_preferences.amenities", "operation": "append", "value": "gym"}),
        ("Budget 10 triệu", {"path": "budget.max", "operation": "set", "value": 10_000_000}),
    ],
)
def test_amenity_and_budget_phrases_pass_through(monkeypatch, message, change):
    _patch(monkeypatch, _FakeLLM([_payload("update_trip", [change])]))
    result = extract_patch(_state(message))

    assert result["patch"] == [change]


def test_ambiguous_date_without_a_year_is_left_for_the_model_to_omit(monkeypatch):
    """"01/07" alone has no year -- the prompt instructs the model to omit
    it rather than guess (Phase 7 owns the interrupt-based disambiguation
    for a date the model DID attempt); this asserts the node doesn't inject
    a guess of its own when the model correctly abstains."""
    _patch(monkeypatch, _FakeLLM([_payload("general_question", [])]))
    result = extract_patch(_state("01/07"))

    assert result["patch"] == []


def test_full_date_with_year_passes_through(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "dates.start", "operation": "set", "value": "2027-07-01"}])]),
    )
    result = extract_patch(_state("01/07/2027"))

    assert result["patch"] == [{"path": "dates.start", "operation": "set", "value": "2027-07-01"}]
