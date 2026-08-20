"""`ask_slot`'s question rendering, focused on the dates question.

The frontend's date-range widget has always asked for both ends in one step
("intakeDatesQuestion"), while the backend asked for the start date alone —
the user read one question and the extractor was primed for a different one.
`pending_question_slots` is now the single source for both, so these tests
pin the wording to the slots actually pending.

No test here reaches `_render_destination`, which is the one branch that
would hit Supabase for the destination list.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.agents.graph.nodes.ask_slot import ask_slot
from src.agents.graph.state import TravelGraphState, initial_graph_state
from src.domain.travel_state import END_NOT_AFTER_START_REASON

_FUTURE_START = (date.today() + timedelta(days=30)).isoformat()
_ANSWERED = {
    "destination": {"presence": "set", "value": "Đà Nẵng"},
    "people": {"presence": "set", "value": 2},
}


def _state(travel_state: dict, *, language: str = "vi") -> TravelGraphState:
    state = initial_graph_state("t1")
    state["language"] = language
    state["travel_state"] = travel_state
    return state


def test_dates_question_asks_for_both_ends_at_once() -> None:
    result = ask_slot(_state(dict(_ANSWERED)))

    assert result["missing_slots"] == ["dates.start", "dates.end"]
    assert "đi và về" in result["next_question"]


def test_answering_only_the_start_narrows_to_the_end_date_question() -> None:
    """One date alone is a legitimate answer: the other slot stays pending
    and the next question stops asking for the date already given."""
    result = ask_slot(
        _state({**_ANSWERED, "dates.start": {"presence": "set", "value": _FUTURE_START}})
    )

    assert result["missing_slots"] == ["dates.end"]
    assert "kết thúc" in result["next_question"]
    assert "đi và về" not in result["next_question"]


def test_combined_dates_question_is_translated() -> None:
    """Byte-identical to the frontend's own `intakeDatesQuestion` in both
    languages — the whole point is that the two surfaces stop asking
    different things."""
    result = ask_slot(_state(dict(_ANSWERED), language="en"))

    assert result["next_question"] == "When do you plan to depart and return?"


def test_a_same_day_trip_is_explained_not_dumped_as_a_validator_string() -> None:
    """"đi Huế trong 1 ngày" resolves to end == start and is rejected. The reply the
    user saw was the validator's own English sentence — "Dữ liệu chưa hợp lệ: end date
    must be after the trip's start date" — which reads as an internal error and says
    nothing about what to do next."""
    state = _state({**_ANSWERED, "dates.start": {"presence": "set", "value": _FUTURE_START}})
    state["rejected_changes"] = [
        {"path": "dates.end", "reason": f"dates.end: {END_NOT_AFTER_START_REASON}"}
    ]

    reply = ask_slot(state)["next_question"]

    assert END_NOT_AFTER_START_REASON not in reply
    assert "ít nhất 1 đêm" in reply
    assert "kết thúc" in reply  # the question itself still follows the explanation


def test_an_unrecognised_rejection_still_shows_its_reason() -> None:
    """Only the same-day case is special-cased; anything else must keep surfacing
    the reason rather than silently becoming a bare re-ask."""
    state = _state({**_ANSWERED, "dates.start": {"presence": "set", "value": _FUTURE_START}})
    state["rejected_changes"] = [{"path": "dates.end", "reason": "dates.end: expected YYYY-MM-DD"}]

    reply = ask_slot(state)["next_question"]

    assert "expected YYYY-MM-DD" in reply
