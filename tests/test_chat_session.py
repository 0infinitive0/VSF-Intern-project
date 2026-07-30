from __future__ import annotations

import os

import pytest

import src.services.chat_session as chat_session_module
import src.services.trip_intake as trip_intake_module
from src.cli.trip_builder_svc import CURRENT_TRIP_PLAN_FILE, PENDING_HOTEL_SELECTION_FILE, SESSION_DATA_DIR
from src.services.chat_session import ChatSession, process_chat_turn
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_edit_planner import TripEditPlan, TripEditPlanError
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
    _mock_intake_extraction(monkeypatch, {"2 người": {"people_count": 2}})

    session = _session(intake_state=TripIntakeState(destination="Đà Nẵng", duration="3 ngày"))
    reply = process_chat_turn(session, "2 người")

    # Trip intake completes the moment destination/duration/people are all known —
    # there is no dedicated preferences question — so the same turn immediately
    # starts the guided hotel-preference flow.
    assert session.intake_state.is_complete
    assert session.hotel_pref_state.stage == "pending_budget"
    assert "1." in reply


def test_process_chat_turn_calls_recommend_hotels_right_after_budget_resolved(monkeypatch):
    """The guided hotel-preference flow is budget-only now (no amenity question),
    so a single resolved budget reply completes it and the same turn immediately
    calls recommend_hotels."""
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
        ),
        hotel_pref_state=HotelPreferenceState(),
    )

    reply = process_chat_turn(session, "4 triệu")

    assert reply == "here is a list"
    assert session.hotel_pref_state.is_complete
    assert session.hotel_pref_state.target_price == 4_000_000
    assert captured["args"]["destination"] == "Đà Nẵng"
    assert captured["args"]["target_price"] == "4000000.0"


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


def test_saved_plan_cutoff_asks_for_day_scope_then_bypasses_agent(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":3}]}')

    captured = {}

    def _plan(request, _data):
        if "tất cả các ngày" not in request:
            return TripEditPlan(
                decision="clarify",
                summary="Cần biết ngày áp dụng",
                clarification_question="Bạn muốn áp dụng cho ngày nào?",
                raw_request=request,
            )
        return TripEditPlan(decision="apply", summary="Áp dụng giới hạn", raw_request=request)

    def _execute(request, plan):
        captured["request"] = request
        captured["plan"] = plan
        return "Đã áp dụng giờ giới hạn."

    monkeypatch.setattr(chat_session_module, "plan_trip_edit", _plan)
    monkeypatch.setattr(chat_session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("recognized saved-plan edits must bypass the LLM agent")

    session = _session(agent=_NeverAgent(), initial_plan_complete=True)

    first_reply = process_chat_turn(session, "buổi tối sau 20h tôi không muốn đi đâu nữa")
    second_reply = process_chat_turn(session, "tất cả các ngày")

    assert "ngày nào" in first_reply.casefold()
    assert second_reply == "Đã áp dụng giờ giới hạn."
    assert "tất cả các ngày" in captured["request"]
    assert session.pending_trip_change is None


def test_textual_tool_call_json_is_never_returned_to_the_user():
    class _FakeMessage:
        def __init__(self, content):
            self.type = "ai"
            self.content = content
            self.tool_calls = []
            self.name = None

    class _RetryingAgent:
        def __init__(self):
            self.calls = 0

        def stream(self, *_args, **_kwargs):
            self.calls += 1
            content = (
                '{"name":"modify_trip_plan","parameters":{"modification_request":"rác rác"}}'
                if self.calls == 1
                else "Mình chưa hiểu yêu cầu. Bạn mô tả lại giúp mình nhé."
            )
            yield {"messages": [_FakeMessage(content)]}

    agent = _RetryingAgent()
    session = _session(agent=agent, initial_plan_complete=True)

    reply = process_chat_turn(session, "hãy giúp tôi")

    assert agent.calls == 2
    assert not reply.lstrip().startswith("{")
    assert "mô tả lại" in reply.casefold()


def test_saved_plan_self_selected_breakfast_bypasses_agent(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":3}]}')

    captured = {}

    def _execute(request, plan):
        captured["args"] = {"modification_request": request, "plan": plan}
        return "Đã để bạn tự chọn bữa sáng."

    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda request, _data: TripEditPlan(decision="apply", summary="Tự chọn bữa sáng", raw_request=request),
    )
    monkeypatch.setattr(chat_session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("recognized saved-plan meal edits must bypass the agent")

    session = _session(agent=_NeverAgent(), initial_plan_complete=True)

    reply = process_chat_turn(session, "tôi muốn tự chọn chỗ ăn sáng")

    assert reply == "Đã để bạn tự chọn bữa sáng."
    assert captured["args"]["modification_request"] == "tôi muốn tự chọn chỗ ăn sáng"


def test_saved_draft_messages_use_the_edit_planner_before_the_general_agent(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":1,"status":"Draft"}],"itinerary_items":[]}')

    captured = {}
    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda request, data: TripEditPlan(decision="apply", summary="Đổi bữa sáng", raw_request=request),
    )
    def _execute(request, plan):
        captured["result"] = (request, plan)
        return "updated"

    monkeypatch.setattr(chat_session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("saved-plan edit planning must happen before the general agent")

    reply = process_chat_turn(_session(agent=_NeverAgent(), initial_plan_complete=True), "đổi bữa sáng ngày 1")

    assert reply == "updated"
    assert captured["result"][0] == "đổi bữa sáng ngày 1"


def test_saved_plan_not_edit_decision_falls_through_to_general_agent(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":1,"status":"Draft"}],"itinerary_items":[]}')

    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda request, _data: TripEditPlan(decision="not_edit", summary="Câu hỏi chung", raw_request=request),
    )

    class _Message:
        type = "ai"
        tool_calls = []
        content = "Đây là câu trả lời chung."

    class _Agent:
        def stream(self, *_args, **_kwargs):
            yield {"messages": [_Message()]}

    reply = process_chat_turn(_session(agent=_Agent(), initial_plan_complete=True), "gợi ý thêm cho tôi")

    assert reply == "Đây là câu trả lời chung."


def test_fresh_trip_request_bypasses_saved_draft_edit_planner_failure(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":1,"status":"Draft"}],"itinerary_items":[]}')

    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("Unterminated string")),
    )
    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {"tôi muốn đi chơi hcm": {"destination": "Hồ Chí Minh"}},
    )

    session = _session()
    reply = process_chat_turn(session, "tôi muốn đi chơi hcm")

    assert not reply.startswith("SYSTEM ERROR:")
    assert "bao lâu" in reply.casefold()
    assert session.intake_state.destination == "Hồ Chí Minh"


def test_fresh_trip_intake_keeps_bypassing_the_old_draft_on_followup(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":1,"status":"Draft"}],"itinerary_items":[]}')

    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(AssertionError("new-trip intake must not return to old-draft editing")),
    )
    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {
            "tôi muốn đi chơi hcm": {"destination": "Hồ Chí Minh"},
            "3 ngày": {"duration_days": 3},
        },
    )

    session = _session()
    first_reply = process_chat_turn(session, "tôi muốn đi chơi hcm")
    second_reply = process_chat_turn(session, "3 ngày")

    assert "bao lâu" in first_reply.casefold()
    assert "bao nhiêu người" in second_reply.casefold()
    assert session.planning_new_trip is True
    assert session.intake_state.duration == "3 ngày"


def test_fresh_session_saved_plan_edit_with_destination_still_fails_closed(monkeypatch):
    with open(CURRENT_TRIP_PLAN_FILE, "w", encoding="utf-8") as f:
        f.write('{"itineraries":[{"duration_days":1,"status":"Draft"}],"itinerary_items":[]}')

    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {"thêm điểm ở hcm vào ngày 1": {"destination": "Hồ Chí Minh"}},
    )
    monkeypatch.setattr(
        chat_session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("Unterminated string")),
    )

    reply = process_chat_turn(_session(), "thêm điểm ở hcm vào ngày 1")

    assert reply.startswith("SYSTEM ERROR:")


def test_agent_provider_error_is_returned_as_a_safe_reply():
    class _FailingAgent:
        def stream(self, *_args, **_kwargs):
            raise RuntimeError("400: messages/0/content array not in string")

    session = _session(agent=_FailingAgent(), initial_plan_complete=True)

    reply = process_chat_turn(session, "hãy giúp tôi")

    assert reply.startswith("SYSTEM ERROR:")
    assert "không thể xử lý" in reply.casefold()
