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
from datetime import date, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import src.agents.graph.nodes.extract_patch as extract_patch_module
from src.agents.graph.nodes.extract_patch import PatchExtractionError, extract_patch
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.domain.travel_state import TravelState
from src.services.trip_intake import DestinationOption

_DESTINATIONS = (DestinationOption("Đà Nẵng"), DestinationOption("Hội An", aliases=("HA",)))

# `next_question` walks real `TravelState` slots, so a state standing in for
# "dates already answered" needs dates the date validators still accept.
_FUTURE_START = (date.today() + timedelta(days=30)).isoformat()
_FUTURE_END = (date.today() + timedelta(days=35)).isoformat()


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """Returns one queued response per `.invoke()` call, in order."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.call_count = 0
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> _FakeResponse:
        self.call_count += 1
        self.prompts.append(prompt)
        return _FakeResponse(self._contents.pop(0))


def _payload(intent: str, changes: list[dict] | None = None) -> str:
    return json.dumps({"intent": intent, "changes": changes or []})


def _state(message: str, *, travel_state: dict | None = None) -> TravelGraphState:
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
    assert result == {"patch": [], "intent": "general_question", "extraction_failed": True}


def test_invalid_first_response_recovers_on_retry(monkeypatch):
    llm = _patch(
        monkeypatch,
        _FakeLLM(["not json", _payload("general_question", [])]),
    )
    result = extract_patch(_state("chào bạn"))

    assert llm.call_count == 2
    assert result == {"patch": [], "intent": "general_question", "extraction_failed": False}


def test_no_human_message_short_circuits_without_calling_the_llm(monkeypatch):
    def _unreachable(**_kwargs):
        raise AssertionError("no human message -> the LLM must never be called")

    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", _unreachable)
    state = initial_graph_state("t1")
    state["messages"] = [AIMessage(content="a stale reply from a previous turn")]

    result = extract_patch(state)

    assert result == {"patch": [], "intent": "general_question", "extraction_failed": True}


# --- Pending-slot anchor ------------------------------------------------------
#
# The prompt is deliberately single-message, so a short reply ("Hồ Chí
# Minh", "1", "20/7") is only interpretable if the slot it answers travels
# with it. The anchor comes from `next_question(travel_state)`, not from
# `state["missing_slots"]`, so it is also present on a thread's first turn —
# the turn carrying the opening destination, when nothing has been asked
# yet. These tests assert the anchor reaches the prompt; whether a real
# model then answers correctly is Phase 10's accuracy eval, as with every
# other case in this file.


def test_first_turn_anchors_on_destination_before_anything_is_asked(monkeypatch):
    llm = _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}])]),
    )
    result = extract_patch(_state("Đà Nẵng"))

    assert "asked the user for `destination`" in llm.prompts[0]
    assert result["patch"] == [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]


def test_anchor_tells_the_model_a_question_naming_the_slot_value_is_not_an_answer(monkeypatch):
    """"địa danh nổi tiếng huế" while `destination` is pending asks about Huế,
    it does not choose Huế. Without this the anchor's "a place name is a
    perfectly good answer" pull turns every question that mentions a city
    into a destination set, and the trip silently starts."""
    llm = _patch(monkeypatch, _FakeLLM([_payload("general_question", [])]))

    result = extract_patch(_state("địa danh nổi tiến huế"))

    assert "Asking about `destination` is not answering it" in llm.prompts[0]
    assert result == {"patch": [], "intent": "general_question", "extraction_failed": False}


def test_anchor_advances_to_the_next_unanswered_slot(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM([_payload("update_trip", [{"path": "people", "operation": "set", "value": 1}])]))
    result = extract_patch(
        _state("1", travel_state={"destination": {"presence": "set", "value": "Đà Nẵng"}})
    )

    assert "asked the user for `people`" in llm.prompts[0]
    assert result["patch"] == [{"path": "people", "operation": "set", "value": 1}]


def test_no_anchor_once_every_required_slot_is_answered(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM([_payload("general_question", [])]))
    extract_patch(
        _state(
            "khách sạn nào có hồ bơi?",
            travel_state={
                "destination": {"presence": "set", "value": "Đà Nẵng"},
                "people": {"presence": "set", "value": 2},
                "dates.start": {"presence": "set", "value": _FUTURE_START},
                "dates.end": {"presence": "set", "value": _FUTURE_END},
                "budget.target": {"presence": "n/a", "value": None},
            },
        )
    )

    assert "asked the user for" not in llm.prompts[0]


def test_dates_anchor_names_both_ends_and_a_lone_date_defaults_to_the_start(monkeypatch):
    """The dates question gathers both ends in one breath, so the anchor has
    to accept a reply naming either one, and say which a single bare date
    means — otherwise a lone "20/7" is dropped as under-specified."""
    llm = _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "dates.start", "operation": "set", "value": "20/7"}])]),
    )
    result = extract_patch(
        _state(
            "20/7",
            travel_state={
                "destination": {"presence": "set", "value": "Đà Nẵng"},
                "people": {"presence": "set", "value": 2},
            },
        )
    )

    assert "asked the user for `dates.start` and `dates.end`" in llm.prompts[0]
    assert "treat it as `dates.start`" in llm.prompts[0]
    assert result["patch"] == [{"path": "dates.start", "operation": "set", "value": "20/7"}]


def test_dates_anchor_narrows_to_the_end_once_the_start_is_known(monkeypatch):
    llm = _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "dates.end", "operation": "set", "value": "25/7"}])]),
    )
    extract_patch(
        _state(
            "25/7",
            travel_state={
                "destination": {"presence": "set", "value": "Đà Nẵng"},
                "people": {"presence": "set", "value": 2},
                "dates.start": {"presence": "set", "value": _FUTURE_START},
            },
        )
    )

    assert "asked the user for `dates.end`" in llm.prompts[0]
    # Single-slot question: no "which one did you mean" tiebreak to give.
    assert "treat it as" not in llm.prompts[0]


def test_duration_from_iso_start_derives_the_required_end_date(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM(
            [
                _payload(
                    "update_trip",
                    [{"path": "dates.start", "operation": "set", "value": "2026-07-01"}],
                )
            ]
        ),
    )

    result = extract_patch(_state("Tôi muốn đi trong 2 ngày từ 2026-07-01"))

    assert result["patch"] == [
        {"path": "dates.start", "operation": "set", "value": "2026-07-01"},
        {"path": "dates.end", "operation": "set", "value": "2026-07-03"},
    ]


def test_anchor_survives_the_repair_retry(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM(["not json", _payload("general_question", [])]))
    extract_patch(
        _state(
            "20/7",
            travel_state={
                "destination": {"presence": "set", "value": "Đà Nẵng"},
                "people": {"presence": "set", "value": 2},
            },
        )
    )

    assert llm.call_count == 2
    assert all("asked the user for `dates.start`" in prompt for prompt in llm.prompts)


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


def test_included_breakfast_is_added_as_a_canonical_hotel_amenity(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("hotel_search", [{"path": "hotel_preferences.amenities", "operation": "append", "value": "swimming_pool"}])]
        ),
    )

    result = extract_patch(_state("Lọc khách sạn có bể bơi và bao gồm ăn sáng"))

    assert result["patch"] == [
        {"path": "hotel_preferences.amenities", "operation": "append", "value": "swimming_pool"},
        {"path": "hotel_preferences.amenities", "operation": "append", "value": "breakfast"},
    ]


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
