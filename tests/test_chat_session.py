from __future__ import annotations

import os

import pytest

import src.services.chat_session as chat_session_module
import src.services.trip_intake as trip_intake_module
from src.cli.trip_builder_svc import CURRENT_TRIP_PLAN_FILE, PENDING_HOTEL_SELECTION_FILE, SESSION_DATA_DIR
from src.services.chat_session import ChatSession, process_chat_turn
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(SESSION_DATA_DIR, exist_ok=True)


def _session(**overrides) -> ChatSession:
    defaults = dict(agent=object(), config={"configurable": {"thread_id": "test"}})
    defaults.update(overrides)
    return ChatSession(**defaults)


def _mock_intake_extraction(monkeypatch, responses: dict[str, dict]) -> None:
    """`TripIntakeState.with_message()` now calls the LLM. Monkeypatch the
    thin extraction call (not `with_message` itself) so these chat_session
    orchestration tests stay deterministic and make zero network calls,
    exactly like the equivalent helper in tests/test_trip_intake.py."""

    def fake(message, known_facts, destination_names, model=None):
        return responses.get(message, {})

    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", fake)


def test_process_chat_turn_routes_to_select_hotel_when_pending_file_exists(monkeypatch):
    with open(PENDING_HOTEL_SELECTION_FILE, "w", encoding="utf-8") as f:
        f.write('{"mode": "new_trip", "options": []}')

    captured = {}

    def _fake_invoke(args):
        captured["args"] = args
        return "picked"

    monkeypatch.setattr(
        chat_session_module,
        "select_hotel",
        type("Fake", (), {"invoke": staticmethod(_fake_invoke)})(),
    )

    session = _session()
    reply = process_chat_turn(session, "1")

    assert reply == "picked"
    assert captured["args"] == {"selection": "1"}
    assert session.initial_plan_complete is True


def test_process_chat_turn_routes_to_finalize_when_finalization_request(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write("{}")

    monkeypatch.setattr(chat_session_module, "_is_finalization_request", lambda text: True)
    monkeypatch.setattr(
        chat_session_module,
        "finalize_trip_plan",
        type("Fake", (), {"invoke": staticmethod(lambda args: "finalized")})(),
    )

    session = _session()
    reply = process_chat_turn(session, "chốt lịch trình")

    assert reply == "finalized"
    assert session.initial_plan_complete is True


def test_process_chat_turn_asks_missing_intake_question(monkeypatch):
    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(monkeypatch, {"Tôi muốn đi Đà Nẵng": {"destination": "Đà Nẵng"}})

    session = _session()
    reply = process_chat_turn(session, "Tôi muốn đi Đà Nẵng")

    assert "bao lâu" in reply.lower()
    assert session.intake_state.destination == "Đà Nẵng"


def test_process_chat_turn_asks_budget_question_right_after_intake_completes(monkeypatch):
    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ())
    _mock_intake_extraction(
        monkeypatch,
        {"2 người": {"people_count": 2}, "không": {"skip_preferences": True}},
    )

    session = _session(intake_state=TripIntakeState(destination="Đà Nẵng", duration="3 ngày"))
    reply = process_chat_turn(session, "2 người")

    assert "yêu cầu hay lưu ý đặc biệt" in reply
    assert not session.intake_state.is_complete

    reply = process_chat_turn(session, "không")

    # The preference reply completes trip intake and must not also be consumed as
    # the hotel budget; the incoming guided hotel flow starts with its first question.
    assert session.intake_state.is_complete
    assert session.hotel_pref_state.stage == "pending_budget"
    assert "1." in reply


def test_process_chat_turn_asks_amenity_question_after_budget_resolved():
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            people="2 người",
            asked_preferences=True,
        ),
        hotel_pref_state=HotelPreferenceState(),
    )

    reply = process_chat_turn(session, "4 triệu")

    assert session.hotel_pref_state.stage == "pending_amenities"
    assert session.hotel_pref_state.target_price == 4_000_000
    assert "tiện ích" in reply.lower() or "1." in reply


def test_process_chat_turn_calls_recommend_hotels_once_both_states_complete(monkeypatch):
    captured = {}

    def _fake_invoke(args):
        captured["args"] = args
        return "here is a list"

    monkeypatch.setattr(
        chat_session_module,
        "recommend_hotels",
        type("Fake", (), {"invoke": staticmethod(_fake_invoke)})(),
    )

    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            people="2 người",
            asked_preferences=True,
        ),
        hotel_pref_state=HotelPreferenceState(stage="pending_amenities", target_price=1_500_000),
    )

    reply = process_chat_turn(session, "2")

    assert reply == "here is a list"
    assert session.hotel_pref_state.is_complete
    assert captured["args"]["destination"] == "Đà Nẵng"
    assert captured["args"]["target_price"] == "1500000"


def test_process_chat_turn_falls_back_to_agent_once_plan_complete():
    class _FakeMessage:
        def __init__(self, type_, content="", tool_calls=None):
            self.type = type_
            self.content = content
            self.tool_calls = tool_calls or []
            self.name = "some_tool"

    class _FakeAgent:
        def stream(self, *_args, **_kwargs):
            yield {"messages": [_FakeMessage("ai", content="Đang xử lý...", tool_calls=[{"name": "modify_trip_plan"}])]}
            yield {"messages": [_FakeMessage("ai", content="Đã cập nhật lịch trình.")]}

    session = _session(agent=_FakeAgent(), initial_plan_complete=True)
    reply = process_chat_turn(session, "đổi khách sạn khác")

    assert reply == "Đã cập nhật lịch trình."
