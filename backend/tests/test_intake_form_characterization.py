"""Phase 1 safety-net characterization tests for the intake → hotel-budget →
recommend_hotels sequence (plan 260803-1713-trip-parameters-intake-form).

These lock in TODAY'S behavior before Phase 3's same-turn carry-through fix:

  turn 1  destination   → next intake question        (stage=intake, tool=None)
  turn 2  duration      → next intake question        (stage=intake, tool=None)
  turn 3  start date    → next intake question        (stage=intake, tool=None)
  turn 4  people        → intake complete; BUDGET Q   (stage=intake, tool=None)
  turn 5  budget tier   → recommend_hotels fires      (stage=hotel_options)

The two-turn budget resolution (intake facts finish on turn 4, recommend_hotels
does not fire until turn 5 answers the budget question) is the exact behavior
Phase 3 changes. Assertions here are written to be updated then — the diff is
the point. No production code is edited in this phase.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.agents.session as session_module
import src.services.trip_intake as trip_intake_module
from src.agents.session import TripSession, derive_stage, process_chat_turn, suggestions_for


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Đà Nẵng", "Nha Trang", "Hội An"),
    )
    # Same seam as tests/test_chat_session.py: force the deterministic
    # decide_route_by_rules fallback — no live supervisor LLM, no non-determinism.
    monkeypatch.setattr(session_module, "decide_route_by_llm", lambda session, user_input: None)


@pytest.fixture()
def fresh_session(monkeypatch):
    session = TripSession(
        session_id="char-test-session",
        agent=MagicMock(),
        config={"configurable": {"thread_id": "char-test-session"}},
    )
    tools = MagicMock()
    tools.recommend_hotels = MagicMock(return_value="Đây là các khách sạn phù hợp:")
    tools.select_hotel = MagicMock()
    tools.finalize_trip_plan = MagicMock()
    session.tools = tools
    return session


def _mock_extraction(monkeypatch, responses: dict[str, dict]) -> None:
    """Deterministic LLM extraction: exact message → raw facts dict; anything
    else fails soft to {} (same as a real LLM failure)."""

    def fake(message, known_facts, destination_names, model=None):
        return responses.get(message, {})

    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", fake)


def test_characterizes_full_sequential_intake_two_turn_budget_resolution(monkeypatch, fresh_session):
    """The plan's core diff: intake facts finish one turn before the budget
    question when the budget is answered in a SEPARATE message. recommend_hotels
    only fires on the turn AFTER the budget tier is answered (sequential chat)."""
    _mock_extraction(
        monkeypatch,
        {
            "Tôi đi Đà Nẵng": {"destination": "Đà Nẵng"},
            "3 ngày": {"duration_days": 3},
            "10/08/2026": {"start_date": "2026-08-10"},
            "2 người": {"people_count": 2},
        },
    )

    # Turns 1-3: sequential intake questions, never a tool call.
    for message in ["Tôi đi Đà Nẵng", "3 ngày", "10/08/2026"]:
        result = process_chat_turn(fresh_session, message)
        assert result.tool is None
        assert derive_stage(result) == "intake"
    assert not fresh_session.intake_state.is_complete

    # Turn 4: intake facts complete. The message "2 người" carries no budget
    # signal, so the budget question is deferred to the next turn — two-turn
    # resolution for sequential chat (no regression).
    intake_done_turn = process_chat_turn(fresh_session, "2 người")
    assert intake_done_turn.tool is None
    assert derive_stage(intake_done_turn) == "intake"
    assert fresh_session.intake_state.is_complete
    assert not fresh_session.hotel_pref_state.is_complete
    # The budget-tier suggestion chips are on offer for the next turn.
    chips = suggestions_for(fresh_session)
    assert len(chips) == 4
    assert "Tiết kiệm" in chips[0]["label"]
    assert "Tầm trung" in chips[1]["label"]

    # Turn 5: budget tier answered → recommend_hotels (stage=hotel_options).
    budget_turn = process_chat_turn(fresh_session, "tầm trung")
    assert budget_turn.tool == "recommend_hotels"
    assert derive_stage(budget_turn) == "hotel_options"
    fresh_session.tools.recommend_hotels.invoke.assert_called_once()
    called = fresh_session.tools.recommend_hotels.invoke.call_args[0][0]
    assert called["destination"] == "Đà Nẵng"
    assert called["duration"] == "3 ngày"
    assert called["min_price"] == "800000"
    assert called["max_price"] == "2500000"


def test_combined_message_with_budget_tier_reaches_hotel_options_in_one_turn(
    monkeypatch, fresh_session
):
    """Phase 3's same-turn carry-through: ONE message carrying both the complete
    trip facts AND a budget-tier phrase reaches hotel_options in a single turn
    — no follow-up budget question."""
    _mock_extraction(
        monkeypatch,
        {
            "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026, khách sạn tầm trung": {
                "destination": "Đà Nẵng",
                "duration_days": 3,
                "start_date": "2026-08-10",
                "people_count": 2,
            },
        },
    )

    result = process_chat_turn(fresh_session, "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026, khách sạn tầm trung")

    assert fresh_session.intake_state.is_complete
    assert fresh_session.hotel_pref_state.is_complete
    assert result.tool == "recommend_hotels"
    assert derive_stage(result) == "hotel_options"
    fresh_session.tools.recommend_hotels.invoke.assert_called_once()
    called = fresh_session.tools.recommend_hotels.invoke.call_args[0][0]
    assert called["min_price"] == "800000"
    assert called["max_price"] == "2500000"


def test_real_composed_form_sentence_is_not_hijacked_by_preference_change_gate(
    monkeypatch, fresh_session
):
    """Regression: `composeIntakeMessage()`'s actual template opens with "Tôi
    muốn đi ... trong N ngày ... cho N người" — that combination of "muốn"
    (want) plus the field words "ngày"/"người" satisfies
    `_looks_like_trip_preference_change()`. On a fresh session (nothing
    confirmed yet, `trip_data is None`), the old gate treated that as "user
    wants to CHANGE an already-confirmed fact" and routed the WHOLE first
    submission through `TripPreferenceUpdate` instead of the deterministic
    intake pipeline — a flow that only knows destination/duration/start_date/
    people/preferences and silently drops budget (asks the budget question
    again, ignoring the answer already in the message) plus companions/pace/
    day_rhythm/notes entirely. The gate must not fire on this exact shape
    until the deterministic pipeline (intake facts + budget) has already
    completed once."""
    message = (
        "Tôi muốn đi Đà Nẵng trong 1 ngày từ 2026-08-05 cho 1 người. "
        "Ngân sách khách sạn: tiết kiệm."
    )
    _mock_extraction(
        monkeypatch,
        {
            message: {
                "destination": "Đà Nẵng",
                "duration_days": 1,
                "start_date": "2026-08-05",
                "people_count": 1,
            },
        },
    )

    result = process_chat_turn(fresh_session, message)

    assert fresh_session.intake_state.is_complete
    assert fresh_session.hotel_pref_state.is_complete
    assert result.tool == "recommend_hotels"
    assert derive_stage(result) == "hotel_options"
    called = fresh_session.tools.recommend_hotels.invoke.call_args[0][0]
    assert called["min_price"] == ""
    assert called["max_price"] == "800000"


def test_hotel_preferences_and_intake_context_flow_into_recommend_hotels(
    monkeypatch, fresh_session
):
    """Phase 3: companions/notes populate hotel_preferences and
    pace/day_rhythm/notes populate intake_context on the recommend_hotels call."""
    _mock_extraction(
        monkeypatch,
        {
            "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026, đi cùng gia đình, ăn hải sản, tầm trung": {
                "destination": "Đà Nẵng",
                "duration_days": 3,
                "start_date": "2026-08-10",
                "people_count": 2,
                "companions": "đi cùng gia đình",
                "notes": "ăn hải sản",
            },
        },
    )

    process_chat_turn(
        fresh_session,
        "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026, đi cùng gia đình, ăn hải sản, tầm trung",
    )

    fresh_session.tools.recommend_hotels.invoke.assert_called_once()
    called = fresh_session.tools.recommend_hotels.invoke.call_args[0][0]
    assert "gia đình" in called["hotel_preferences"]
    assert "hải sản" in called["hotel_preferences"]


def test_optional_fields_added_on_the_budget_follow_up_turn_are_not_dropped(
    monkeypatch, fresh_session
):
    """Regression: the form re-renders on the budget follow-up turn pre-filled
    from the latest intake snapshot, and its fields stay editable — a user may
    leave companions/notes blank on the first submission and add them alongside
    the budget answer on the second. Before this fix, `_run_intake` skipped
    `intake_state.with_message()` entirely once trip facts were already
    complete, so anything only supplied on this second turn was silently
    dropped rather than merged in."""
    _mock_extraction(
        monkeypatch,
        {
            "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026": {
                "destination": "Đà Nẵng",
                "duration_days": 3,
                "start_date": "2026-08-10",
                "people_count": 2,
            },
            "Ngân sách khách sạn: tầm trung. Đi cùng: đi cùng gia đình. Ghi chú: cần phòng view biển.": {
                "companions": "đi cùng gia đình",
                "notes": "cần phòng view biển",
            },
        },
    )

    # Turn 1: required facts only — companions/notes left blank.
    turn1 = process_chat_turn(fresh_session, "Đi Đà Nẵng 3 ngày 2 người từ 10/08/2026")
    assert turn1.tool is None
    assert fresh_session.intake_state.is_complete
    assert not fresh_session.hotel_pref_state.is_complete
    assert fresh_session.intake_state.companions is None

    # Turn 2: the re-rendered form's second submission adds companions/notes
    # alongside the budget tier.
    turn2 = process_chat_turn(
        fresh_session,
        "Ngân sách khách sạn: tầm trung. Đi cùng: đi cùng gia đình. Ghi chú: cần phòng view biển.",
    )
    assert turn2.tool == "recommend_hotels"
    assert fresh_session.intake_state.companions == "đi cùng gia đình"
    assert fresh_session.intake_state.notes == "cần phòng view biển"

    called = fresh_session.tools.recommend_hotels.invoke.call_args[0][0]
    assert "gia đình" in called["hotel_preferences"]
    assert "cần phòng view biển" in called["hotel_preferences"]


def test_characterizes_derive_stage_stays_intake_through_budget_question(monkeypatch, fresh_session):
    """derive_stage() must report 'intake' for every turn in the sequence,
    including the hotel-budget question turn — a regression that accidentally
    changes the reported stage is caught here."""
    _mock_extraction(
        monkeypatch,
        {
            "Đà Nẵng, 4 ngày, 2 người, 01/09/2026": {
                "destination": "Đà Nẵng",
                "duration_days": 4,
                "start_date": "2026-09-01",
                "people_count": 2,
            },
        },
    )
    result = process_chat_turn(fresh_session, "Đà Nẵng, 4 ngày, 2 người, 01/09/2026")
    assert result.tool is None
    assert derive_stage(result) == "intake"
    assert fresh_session.intake_state.is_complete
    assert not fresh_session.hotel_pref_state.is_complete

    result = process_chat_turn(fresh_session, "cao cấp")
    assert result.tool == "recommend_hotels"
    assert derive_stage(result) == "hotel_options"


def test_characterizes_chip_generation_pending_hotel_list(monkeypatch, fresh_session):
    """suggestions_for() chips for the pending hotel list case (hotel_options
    turn): one chip per pending option, value = its 1-based ordinal."""
    fresh_session.pending_hotel_selection = {
        "options": [
            {"name": "Fusion Resort"},
            {"name": "Muong Thanh"},
            {"name": "Vinpearl"},
        ]
    }
    chips = suggestions_for(fresh_session)
    assert [c["label"] for c in chips] == [
        "1. Fusion Resort",
        "2. Muong Thanh",
        "3. Vinpearl",
    ]
    assert [c["value"] for c in chips] == ["1", "2", "3"]


def test_characterizes_chip_generation_budget_tier_suggestion(monkeypatch, fresh_session):
    """suggestions_for() chips for the budget-tier-suggestion case (intake
    complete, budget not yet answered): the 4 budget question option labels,
    no other text scanning."""
    fresh_session.intake_state = trip_intake_module.TripIntakeState(
        destination="Đà Nẵng",
        duration="3 ngày",
        start_date="2026-08-10",
        people="2 người",
    )
    chips = suggestions_for(fresh_session)
    assert [c["value"] for c in chips] == ["1", "2", "3", "4"]
    assert "Tiết kiệm" in chips[0]["label"]
    assert "Cao cấp" in chips[2]["label"]


def test_is_complete_excludes_optional_fields(monkeypatch):
    """The optional fields never participate in is_complete — the same
    contract `preferences` already has. Confirms intent; redundant assertions
    are intentionally avoided since tests/test_trip_intake.py already covers
    the preferences case."""
    state = trip_intake_module.TripIntakeState(
        destination="Đà Nẵng",
        duration="3 ngày",
        start_date="2026-08-10",
        people="2 người",
    )
    assert state.is_complete
