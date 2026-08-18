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


def _payload(intent: str, changes: list[dict] | None = None, reason: object = None) -> str:
    body: dict[str, object] = {"intent": intent, "changes": changes or []}
    if reason is not None:
        body["reason"] = reason
    return json.dumps(body)


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
    # Fail-open: a response with no `reason` key -- every response from a
    # model that hasn't seen the new prompt yet -- costs no retry.
    assert result["patch_reason"] == ""


def test_invalid_json_retries_once_then_falls_back_without_raising(monkeypatch):
    llm = _patch(monkeypatch, _FakeLLM(["not json", "still not json"]))
    result = extract_patch(_state("asdkjasd"))

    assert llm.call_count == 2
    assert result == {
        "patch": [],
        "intent": "general_question",
        "extraction_failed": True,
        "patch_reason": "",
        "pending_clarify_day": None,
    }


def test_invalid_first_response_recovers_on_retry(monkeypatch):
    llm = _patch(
        monkeypatch,
        _FakeLLM(["not json", _payload("general_question", [])]),
    )
    result = extract_patch(_state("chào bạn"))

    assert llm.call_count == 2
    assert result == {
        "patch": [],
        "intent": "general_question",
        "extraction_failed": False,
        "patch_reason": "",
        "pending_clarify_day": None,
    }


def test_no_human_message_short_circuits_without_calling_the_llm(monkeypatch):
    def _unreachable(**_kwargs):
        raise AssertionError("no human message -> the LLM must never be called")

    monkeypatch.setattr(extract_patch_module, "get_reasoning_llm", _unreachable)
    state = initial_graph_state("t1")
    state["messages"] = [AIMessage(content="a stale reply from a previous turn")]

    result = extract_patch(state)

    assert result == {
        "patch": [],
        "intent": "general_question",
        "extraction_failed": True,
        "patch_reason": "",
        "pending_clarify_day": None,
    }


# --- patch_reason (Phase 16): why extractor's own account of an empty ------
# patch, threaded through non-strictly. `intent`/`changes` keep today's
# strict validation (see the Structural validation section below); only
# `reason` falls open on anything it doesn't recognize.


def test_the_prompt_defines_both_reason_values_not_just_the_schema_key(monkeypatch):
    """The schema line alone gives the model an enum with no semantics, and
    every other test here simulates the response rather than producing it --
    so nothing else would notice the rule going missing. `missing_value` is
    what the routing branch keys on, and mislabeling it as `no_change`
    silently reverts the turn to the behavior this field exists to fix."""
    llm = _FakeLLM([_payload("update_itinerary", [], reason="missing_value")])
    _patch(monkeypatch, llm)
    extract_patch(_state("đổi theme ngày 1"))

    prompt = llm.prompts[0]
    assert "explains an EMPTY changes list" in prompt
    assert "ignored when changes is non-empty" in prompt
    assert "never says what to change it TO" in prompt
    assert "redo work from facts already known" in prompt


def test_missing_value_reason_on_an_under_specified_edit(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("update_itinerary", [], reason="missing_value")]))
    result = extract_patch(_state("đổi theme ngày 1"))

    assert result["patch"] == []
    assert result["patch_reason"] == "missing_value"


def test_no_change_reason_on_a_rerun_request(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("hotel_search", [], reason="no_change")]))
    result = extract_patch(_state("tìm lại khách sạn"))

    assert result["patch_reason"] == "no_change"


def test_unrecognized_reason_value_falls_open(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("general_question", [], reason="banana")]))
    result = extract_patch(_state("chào bạn"))

    assert result["patch_reason"] == ""


def test_wrong_type_reason_falls_open_without_raising(monkeypatch):
    """A list isn't just "not one of the two labels" -- it's unhashable, so
    a naive `reason in _PATCH_REASONS` would raise TypeError instead of
    falling open."""
    _patch(monkeypatch, _FakeLLM([_payload("general_question", [], reason=["missing_value"])]))
    result = extract_patch(_state("chào bạn"))

    assert result["patch_reason"] == ""


def test_reason_is_carried_even_when_changes_is_non_empty(monkeypatch):
    """`extract_patch` doesn't suppress `reason` itself when a real change
    is present -- `routing.is_incomplete_edit` is what ignores it in that
    case, via its own `patch` guard. This is that guard's precondition, so
    it runs through the whole node: the change has to survive the day-scope
    rewrite and grounding to be there for the guard to see."""
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("update_trip", [{"path": "people", "operation": "set", "value": 4}], reason="missing_value")]
        ),
    )
    result = extract_patch(_state("4 người nhé"))

    assert result["intent"] == "update_trip"
    assert result["patch"] == [{"path": "people", "operation": "set", "value": 4}]
    assert result["patch_reason"] == "missing_value"


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
    assert result == {
        "patch": [],
        "intent": "general_question",
        "extraction_failed": False,
        "patch_reason": "",
        "pending_clarify_day": None,
    }


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

    # preferences.themes is a label list; daily_preferences.<day>.theme is
    # free text (_validate_daily_theme) -- the rewrite joins the list so
    # the change survives that validator instead of being silently rejected.
    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": "thiên nhiên"}]


def test_first_day_ordinal_phrase_resolves_to_day_1(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    result = extract_patch(_state("Ngày đầu tôi muốn đi biển"))

    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": "biển"}]


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

    assert result["patch"] == [{"path": "daily_preferences.3.theme", "operation": "set", "value": "biển"}]


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


def test_multiple_themes_in_a_day_scoped_message_join_into_one_string(monkeypatch):
    """Without joining, `_validate_daily_theme` (a string-only validator)
    would reject this outright and the theme would never apply -- silently,
    with no error surfaced to the user."""
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển", "ẩm thực"]}])]
        ),
    )
    result = extract_patch(_state("Ngày 2 tôi muốn biển và ẩm thực"))

    assert result["patch"] == [{"path": "daily_preferences.2.theme", "operation": "set", "value": "biển, ẩm thực"}]


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


# --- pending_clarify_day: the clarify-turn anchor (Phase 16) ---------------
#
# `_pending_slots` anchors a short reply during intake; nothing analogous
# existed for `intake_qa`'s post-intake clarify question until this field.
# Write side: `extract_patch` persists the day THIS turn was about whenever
# it is itself heading into the clarify branch. Read side: the very next
# call falls back to it when the new message names no day of its own.


def test_a_day_scoped_missing_value_turn_persists_that_day(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("update_itinerary", [], reason="missing_value")]))
    result = extract_patch(_state("đổi theme ngày 1"))

    assert result["patch"] == []
    assert result["pending_clarify_day"] == 1


def test_no_day_mentioned_persists_nothing(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("update_itinerary", [], reason="missing_value")]))
    result = extract_patch(_state("đổi theme"))

    assert result["pending_clarify_day"] is None


def test_reason_no_change_persists_nothing_even_with_a_day_mentioned(monkeypatch):
    """`lên lịch lại ngày 1` clears guard 1 (`update_itinerary`) and even
    names a day, but `reason: "no_change"` means this was never a clarify
    turn -- persisting a day here would misattribute an unrelated later
    reply to day 1."""
    _patch(monkeypatch, _FakeLLM([_payload("update_itinerary", [], reason="no_change")]))
    result = extract_patch(_state("lên lịch lại ngày 1"))

    assert result["pending_clarify_day"] is None


def test_excluded_intent_persists_nothing_even_with_missing_value_and_a_day(monkeypatch):
    """Guard 1's exclusion applies here too: a `hotel_search` turn never
    feeds the clarify branch, so it must never seed its anchor either."""
    _patch(monkeypatch, _FakeLLM([_payload("hotel_search", [], reason="missing_value")]))
    result = extract_patch(_state("đổi khách sạn ngày 1"))

    assert result["pending_clarify_day"] is None


def test_a_complete_edit_persists_nothing(monkeypatch):
    """`changes` non-empty means nothing was left to clarify -- the
    `reason`-ignored-when-changes-exist rule applies to the anchor too."""
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("update_itinerary", [{"path": "daily_preferences.1.theme", "operation": "set", "value": "biển"}])]
        ),
    )
    result = extract_patch(_state("ngày 1 biển"))

    assert result["pending_clarify_day"] is None


def test_carried_over_day_rewrites_a_bare_followup_reply(monkeypatch):
    """The read side: this message names no day of its own, so the day
    carried over from the previous turn's clarify question is what
    `_rewrite_day_scope` uses -- the fix for the finding Phase 2's own test
    plan anticipated (a bare "biển" landing trip-wide instead of on the day
    that was actually asked about)."""
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    # `pending_clarify_day` lives on graph state, not `travel_state` -- set
    # it directly, matching how `extract_patch` reads it.
    state = _state("biển")
    state["pending_clarify_day"] = 1

    result = extract_patch(state)

    assert result["patch"] == [{"path": "daily_preferences.1.theme", "operation": "set", "value": "biển"}]
    # Consumed, not left to leak into a third, unrelated turn.
    assert result["pending_clarify_day"] is None


def test_this_messages_own_day_mention_outranks_the_carried_over_one(monkeypatch):
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_itinerary", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    state = _state("ngày 2 biển")
    state["pending_clarify_day"] = 1

    result = extract_patch(state)

    assert result["patch"] == [{"path": "daily_preferences.2.theme", "operation": "set", "value": "biển"}]
    assert result["pending_clarify_day"] is None


def test_no_carried_over_day_and_no_message_day_leaves_the_change_trip_wide(monkeypatch):
    """No anchor to fall back on (first turn, or the anchor already
    expired) -- the pre-existing, unmodified behavior."""
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    result = extract_patch(_state("biển"))

    assert result["patch"] == [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}]


def test_an_unrelated_empty_missing_value_turn_does_not_renew_the_carried_day(monkeypatch):
    """The write side persists THIS message's own day mention, never the
    effective (fallback-inclusive) one -- otherwise any later empty,
    `missing_value`, included-intent turn about something else entirely
    (a budget edit with no amount, here) would silently re-arm the old
    anchor for a THIRD turn that never mentioned any day at all."""
    _patch(monkeypatch, _FakeLLM([_payload("update_trip", [], reason="missing_value")]))
    state = _state("đổi ngân sách")
    state["pending_clarify_day"] = 1

    result = extract_patch(state)

    assert result["pending_clarify_day"] is None


def test_carried_day_is_not_consumed_while_a_slot_is_still_missing(monkeypatch):
    """The read side is gated on `missing_slots` too: a day named mid-intake
    must not anchor a LATER intake reply that has nothing to do with it --
    `missing_slots` here is the value `ask_slot` left at the end of the
    PREVIOUS turn (`load_context` preserves it), the same signal
    `_pending_slots` above already relies on."""
    _patch(
        monkeypatch,
        _FakeLLM([_payload("update_trip", [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}])]),
    )
    state = _state("biển")
    state["pending_clarify_day"] = 1
    state["missing_slots"] = ["destination"]

    result = extract_patch(state)

    assert result["patch"] == [{"path": "preferences.themes", "operation": "set", "value": ["biển"]}]


def test_a_multi_day_missing_value_turn_persists_nothing(monkeypatch):
    """One int can't carry two days -- guessing day 1 while silently
    dropping day 2 from a follow-up would be worse than the follow-up
    simply landing trip-wide, so a multi-day mention isn't persisted at
    all."""
    _patch(monkeypatch, _FakeLLM([_payload("update_itinerary", [], reason="missing_value")]))
    result = extract_patch(_state("đổi theme ngày 1 và ngày 2"))

    assert result["pending_clarify_day"] is None


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


def test_sea_view_is_added_as_a_canonical_hotel_amenity(monkeypatch):
    """Bug fix: a compound request ("view biển ... và có bao bữa sáng") used
    to be able to lose the sea-view half if the extractor only emitted the
    other amenity -- breakfast already had this rescue, sea view didn't."""
    _patch(
        monkeypatch,
        _FakeLLM(
            [_payload("hotel_search", [{"path": "hotel_preferences.amenities", "operation": "append", "value": "breakfast"}])]
        ),
    )

    result = extract_patch(_state("Tôi muốn phòng có view biển lãng mạn và có bao bữa sáng"))

    assert result["patch"] == [
        {"path": "hotel_preferences.amenities", "operation": "append", "value": "breakfast"},
        {"path": "hotel_preferences.amenities", "operation": "append", "value": "sea_view"},
    ]


def test_negated_sea_view_is_not_added(monkeypatch):
    _patch(monkeypatch, _FakeLLM([_payload("hotel_search", [])]))

    result = extract_patch(_state("Không cần view biển cũng được"))

    assert result["patch"] == []


def test_explicit_date_range_overrides_whatever_the_llm_extracted(monkeypatch):
    """Bug fix: compose-intake-message.ts always sends this exact "từ ngày
    D/M/Y đến ngày D/M/Y" template for the date-range picker. A picked
    10-13/09/2026 range (3 nights) used to be able to come back echoed as
    10-12 (2 nights) if the model mis-copied the checkout date out of the
    sentence -- this makes the parse deterministic instead of trusting the
    model, using the LLM's (here deliberately wrong) end date to prove the
    override actually wins."""
    _patch(
        monkeypatch,
        _FakeLLM(
            [
                _payload(
                    "update_trip",
                    [
                        {"path": "dates.start", "operation": "set", "value": "10/9/2026"},
                        {"path": "dates.end", "operation": "set", "value": "12/9/2026"},  # wrong on purpose
                    ],
                )
            ]
        ),
    )

    result = extract_patch(
        _state("Tôi muốn đi Đà Nẵng từ ngày 10/09/2026 đến ngày 13/09/2026 cho 4 người.")
    )

    assert result["patch"] == [
        {"path": "dates.start", "operation": "set", "value": "10/09/2026"},
        {"path": "dates.end", "operation": "set", "value": "13/09/2026"},
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
