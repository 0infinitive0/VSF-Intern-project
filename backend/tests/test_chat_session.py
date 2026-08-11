from __future__ import annotations

import pytest

import src.agents.session as session_module
import src.services.trip_intake as trip_intake_module
from src.agents.session import TripSession, TurnResult, execute_trip_edit_request, process_chat_turn
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_edit_planner import EditOperation, TripEditPlan, TripEditPlanError
from src.services.trip_intake import DestinationOption, TripIntakeState, TripPreferenceUpdate


def test_frontend_hotel_selection_reopens_archived_options_as_a_change():
    archived = {
        "mode": "new_trip",
        "destination": "Hồ Chí Minh",
        "options": [{"id": "hotel-2", "name": "Khách sạn mới"}],
    }
    session = _session(trip_data={"itineraries": [{"status": "Draft"}], "hotel_selection_options": archived})

    pending = session_module._pending_hotel_selection_for_frontend(session)

    assert pending is not archived
    assert pending["mode"] == "change_hotel"
    assert pending["options"] == archived["options"]
    assert session.pending_hotel_selection is None


@pytest.fixture(autouse=True)
def _no_live_supervisor(monkeypatch):
    """These are unit tests of the deterministic `decide_route_by_rules`
    cascade, predating the LLM supervisor (Phase 3). Force every
    `process_chat_turn` call here through the regex fallback, the same way
    `TRIP_SUPERVISOR_ROUTER=0` would in production — otherwise, whenever a
    real Ollama happens to be reachable, a live, unstubbed LLM would decide
    routing non-deterministically for tests that were never written to
    exercise it."""
    monkeypatch.setattr(session_module, "decide_route_by_llm", lambda session, user_input: None)


class _FakeTool:
    def __init__(self, invoke_fn):
        self._invoke_fn = invoke_fn

    def invoke(self, args):
        return self._invoke_fn(args)


def _never_called(name):
    def _raise(_args):
        raise AssertionError(f"{name} not stubbed for this test")

    return _FakeTool(_raise)


class _FakeTools:
    """Default no-op tools bundle for tests that never reach a real tool call
    (they exercise the deterministic branches of process_chat_turn instead)."""

    def __init__(self):
        self.recommend_hotels = _never_called("recommend_hotels")
        self.select_hotel = _never_called("select_hotel")
        self.finalize_trip_plan = _never_called("finalize_trip_plan")
        self.modify_trip_plan = _never_called("modify_trip_plan")


def _session(**overrides) -> TripSession:
    defaults = dict(
        session_id="test",
        agent=object(),
        config={"configurable": {"thread_id": "test"}},
        tools=_FakeTools(),
    )
    defaults.update(overrides)
    return TripSession(**defaults)


def _mock_intake_extraction(monkeypatch, responses: dict[str, dict]) -> None:
    """`TripIntakeState.with_message()` now calls the LLM. Monkeypatch the
    thin extraction call (not `with_message` itself) so these process_chat_turn
    orchestration tests stay deterministic and make zero network calls."""

    def fake(message, known_facts, destination_names, model=None):
        return responses.get(message, {})

    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", fake)


def test_process_chat_turn_routes_to_select_hotel_when_pending_selection_exists():
    session = _session(pending_hotel_selection={"mode": "new_trip", "options": []})

    captured = {}

    def _fake_invoke(args):
        captured["args"] = args
        # The real select_hotel clears pending_hotel_selection once it resolves a
        # hotel, and process_chat_turn keys off exactly that to tell success from
        # failure.
        session.pending_hotel_selection = None
        return "picked"

    session.tools.select_hotel = _FakeTool(_fake_invoke)

    reply = process_chat_turn(session, "1").text

    assert reply == "picked"
    assert captured["args"] == {"selection": "1"}
    assert session.initial_plan_complete is True


def test_process_chat_turn_routes_to_finalize_when_finalization_request(monkeypatch):
    session = _session(trip_data={})

    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)
    session.tools.finalize_trip_plan = _FakeTool(lambda args: "finalized")

    reply = process_chat_turn(session, "chốt lịch trình").text

    assert reply == "finalized"
    assert session.initial_plan_complete is True


def test_process_chat_turn_asks_missing_intake_question(monkeypatch):
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(monkeypatch, {"Tôi muốn đi Đà Nẵng": {"destination": "Đà Nẵng"}})

    session = _session()
    reply = process_chat_turn(session, "Tôi muốn đi Đà Nẵng").text

    assert "bao lâu" in reply.lower()
    assert session.intake_state.destination == "Đà Nẵng"


def test_process_chat_turn_asks_budget_question_right_after_intake_completes(monkeypatch):
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ())
    _mock_intake_extraction(monkeypatch, {"2 người": {"people_count": 2}})

    session = _session(intake_state=TripIntakeState(destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10"))
    reply = process_chat_turn(session, "2 người").text

    # Trip intake completes the moment destination/duration/people are all known —
    # there is no dedicated preferences question — so the same turn immediately
    # starts the guided hotel-preference flow.
    assert session.intake_state.is_complete
    assert session.hotel_pref_state.stage == "pending_budget"
    assert "1." in reply


def test_process_chat_turn_collects_dates_from_frontend_after_hotel_price(monkeypatch):
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(
        monkeypatch,
        {
            "Đà Nẵng": {"destination": "Đà Nẵng"},
            "2 người": {"people_count": 2},
        },
    )
    captured = {}
    session = _session()

    def recommend(args):
        captured["arguments"] = args
        return "hotel options"

    session.tools.recommend_hotels = _FakeTool(recommend)

    assert "bao nhiêu người" in process_chat_turn(session, "Đà Nẵng").text.casefold()
    assert "1." in process_chat_turn(session, "2 người").text
    assert "biểu mẫu" in process_chat_turn(session, "4 triệu").text.casefold()

    reply = process_chat_turn(session, "", stay_dates=("2026-08-10", "2026-08-13"))

    assert reply.text == "hotel options"
    assert captured["arguments"]["start_date"] == "2026-08-10"
    assert captured["arguments"]["end_date"] == "2026-08-13"
    assert captured["arguments"]["duration"] == "3 ngày"


def test_process_chat_turn_calls_recommend_hotels_right_after_budget_resolved():
    """The guided hotel-preference flow is budget-only now (no amenity question),
    so a single resolved budget reply completes it and the same turn immediately
    calls recommend_hotels."""
    captured = {}

    def _fake_invoke(args):
        captured["args"] = args
        return "here is a list"

    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            start_date="2026-08-10",
            people="2 người",
        ),
        hotel_pref_state=HotelPreferenceState(),
    )
    session.tools.recommend_hotels = _FakeTool(_fake_invoke)

    reply = process_chat_turn(session, "4 triệu").text

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
    reply = process_chat_turn(session, "đổi khách sạn khác").text

    assert reply == "Đã cập nhật lịch trình."


def test_saved_plan_cutoff_asks_for_day_scope_then_bypasses_agent(monkeypatch):
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]}, initial_plan_complete=True)

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

    def _execute(_session, request, plan):
        captured["request"] = request
        captured["plan"] = plan
        return "Đã áp dụng giờ giới hạn."

    monkeypatch.setattr(session_module, "plan_trip_edit", _plan)
    monkeypatch.setattr(session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("recognized saved-plan edits must bypass the LLM agent")

    session.agent = _NeverAgent()

    first_reply = process_chat_turn(session, "buổi tối sau 20h tôi không muốn đi đâu nữa").text
    second_reply = process_chat_turn(session, "tất cả các ngày").text

    assert "ngày nào" in first_reply.casefold()
    assert second_reply == "Đã áp dụng giờ giới hạn."
    assert "tất cả các ngày" in captured["request"]


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

    reply = process_chat_turn(session, "hãy giúp tôi").text

    assert agent.calls == 2
    assert not reply.lstrip().startswith("{")
    assert "mô tả lại" in reply.casefold()


def test_saved_plan_self_selected_breakfast_bypasses_agent(monkeypatch):
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]}, initial_plan_complete=True)

    captured = {}

    def _execute(_session, request, plan):
        captured["args"] = {"modification_request": request, "plan": plan}
        return "Đã để bạn tự chọn bữa sáng."

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, _data: TripEditPlan(decision="apply", summary="Tự chọn bữa sáng", raw_request=request),
    )
    monkeypatch.setattr(session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("recognized saved-plan meal edits must bypass the agent")

    session.agent = _NeverAgent()

    reply = process_chat_turn(session, "tôi muốn tự chọn chỗ ăn sáng").text

    assert reply == "Đã để bạn tự chọn bữa sáng."
    assert captured["args"]["modification_request"] == "tôi muốn tự chọn chỗ ăn sáng"


def test_saved_draft_messages_use_the_edit_planner_before_the_general_agent(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
        initial_plan_complete=True,
    )

    captured = {}
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, data: TripEditPlan(decision="apply", summary="Đổi bữa sáng", raw_request=request),
    )

    def _execute(_session, request, plan):
        captured["result"] = (request, plan)
        return "updated"

    monkeypatch.setattr(session_module, "execute_trip_edit_request", _execute)

    class _NeverAgent:
        def stream(self, *_args, **_kwargs):
            raise AssertionError("saved-plan edit planning must happen before the general agent")

    session.agent = _NeverAgent()

    reply = process_chat_turn(session, "đổi bữa sáng ngày 1").text

    assert reply == "updated"
    assert captured["result"][0] == "đổi bữa sáng ngày 1"


def test_saved_plan_not_edit_decision_falls_through_to_general_agent(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
        initial_plan_complete=True,
    )

    monkeypatch.setattr(
        session_module,
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

    session.agent = _Agent()
    reply = process_chat_turn(session, "gợi ý thêm cho tôi").text

    assert reply == "Đây là câu trả lời chung."


def test_fresh_trip_request_bypasses_saved_draft_edit_planner_failure(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
    )

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("Unterminated string")),
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {"tôi muốn đi chơi hcm": {"destination": "Hồ Chí Minh"}},
    )

    reply = process_chat_turn(session, "tôi muốn đi chơi hcm").text

    assert not reply.startswith("SYSTEM ERROR:")
    assert "bao lâu" in reply.casefold()
    assert session.intake_state.destination == "Hồ Chí Minh"


def test_fresh_trip_intake_keeps_bypassing_the_old_draft_on_followup(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
    )

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(AssertionError("new-trip intake must not return to old-draft editing")),
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {
            "tôi muốn đi chơi hcm": {"destination": "Hồ Chí Minh"},
            "3 ngày": {"duration_days": 3},
            "10/8/2026": {"start_date": "2026-08-10"},
        },
    )

    first_reply = process_chat_turn(session, "tôi muốn đi chơi hcm").text
    second_reply = process_chat_turn(session, "3 ngày").text
    third_reply = process_chat_turn(session, "10/8/2026").text

    assert "bao lâu" in first_reply.casefold()
    assert "ngày nào" in second_reply.casefold()
    assert "bao nhiêu người" in third_reply.casefold()
    assert session.planning_new_trip is True
    assert session.intake_state.duration == "3 ngày"


def test_fresh_session_saved_plan_edit_with_destination_still_fails_closed(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
    )

    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {"thêm điểm ở hcm vào ngày 1": {"destination": "Hồ Chí Minh"}},
    )
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("Unterminated string")),
    )

    reply = process_chat_turn(session, "thêm điểm ở hcm vào ngày 1").text

    assert reply.startswith("SYSTEM ERROR:")


def test_agent_provider_error_is_returned_as_a_safe_reply():
    class _FailingAgent:
        def stream(self, *_args, **_kwargs):
            raise RuntimeError("400: messages/0/content array not in string")

    session = _session(agent=_FailingAgent(), initial_plan_complete=True)

    reply = process_chat_turn(session, "hãy giúp tôi").text

    assert reply.startswith("SYSTEM ERROR:")
    assert "không thể xử lý" in reply.casefold()


def test_unsupported_destination_is_named_not_sent_to_the_edit_planner(monkeypatch):
    """With a saved plan, "đi Hội An" used to fall through to the edit planner and
    come back as "không thể hiểu yêu cầu chỉnh sửa" — telling the user their edit
    was unclear when the real reason is that we have no Hội An data."""
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]})

    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế"))
    monkeypatch.setattr(
        session_module,
        "_llm_extract_intake_facts",
        lambda message, known, names, model=None: {"destination": "Hội An", "duration_days": 2},
    )

    class _NeverPlanner:
        def __call__(self, *_args, **_kwargs):
            raise AssertionError("an unsupported destination must not reach the edit planner")

    monkeypatch.setattr(session_module, "plan_trip_edit", _NeverPlanner())

    reply = process_chat_turn(session, "đi Hội An 2 ngày 2 người").text

    assert "Đà Nẵng" in reply and "Huế" in reply
    assert "chỉnh sửa" not in reply


def test_edit_request_naming_no_place_still_reaches_the_edit_planner(monkeypatch):
    """Guards the fix above from over-firing: "không muốn đi đâu nữa" contains the
    travel word "đi" but names no place, so it is an edit and must stay one."""
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]})

    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế"))
    monkeypatch.setattr(
        session_module,
        "_llm_extract_intake_facts",
        lambda message, known, names, model=None: {"destination": None},
    )
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, data: TripEditPlan(decision="apply", summary="ok", raw_request=request),
    )
    monkeypatch.setattr(
        session_module, "execute_trip_edit_request", lambda _session, request, plan: "Đã áp dụng."
    )

    reply = process_chat_turn(session, "buổi tối sau 20h tôi không muốn đi đâu nữa").text

    assert reply == "Đã áp dụng."


def test_unresolved_hotel_reply_that_is_another_intent_drops_the_pending_list(monkeypatch):
    """A shown hotel list used to swallow every later message: with the selection
    pending, "chốt lịch trình" came back as "mình chưa xác định được khách sạn" and
    there was no way out short of picking a hotel."""
    session = _session(
        pending_hotel_selection={"mode": "new_trip", "options": []},
        trip_data={"itineraries": [{"duration_days": 3}]},
    )

    # Real select_hotel leaves pending_hotel_selection set when it cannot resolve
    # a choice.
    session.tools.select_hotel = _FakeTool(lambda args: "Mình chưa xác định được...")
    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)
    session.tools.finalize_trip_plan = _FakeTool(lambda args: "Đã chốt lịch trình.")

    reply = process_chat_turn(session, "chốt lịch trình này").text

    assert reply == "Đã chốt lịch trình."
    assert session.pending_hotel_selection is None


def test_unresolved_hotel_reply_that_is_a_number_keeps_asking():
    """Guards the fix from over-firing: a bare number is always a pick attempt, so
    an out-of-range "9" must re-ask rather than silently abandon the list."""
    session = _session(pending_hotel_selection={"mode": "new_trip", "options": []})
    session.tools.select_hotel = _FakeTool(lambda args: "Mình chưa xác định được...")

    reply = process_chat_turn(session, "9").text

    assert reply == "Mình chưa xác định được..."
    assert session.pending_hotel_selection is not None


def test_preference_change_replaces_pending_hotel_list_before_selection(monkeypatch):
    message = "đổi thành 5 ngày, 4 người"
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            start_date="2026-08-10",
            people="2 người",
            preferences=("biển",),
        ),
        hotel_pref_state=HotelPreferenceState(stage="done", min_price=800_000, max_price=2_500_000),
        pending_hotel_selection={"mode": "new_trip", "options": [{"name": "Khách sạn cũ"}]},
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(
        monkeypatch,
        {
            message: {
                "changed_fields": ["duration", "people"],
                "duration_days": 5,
                "people_count": 4,
            }
        },
    )
    captured = {}

    def _recommend(args):
        captured.update(args)
        session.pending_hotel_selection = {
            "mode": "new_trip",
            "duration": args["duration"],
            "start_date": args["start_date"],
            "end_date": args["end_date"],
            "people": args["people"],
            "options": [{"name": "Khách sạn mới"}],
        }
        return "Khách sạn mới"

    session.tools.recommend_hotels = _FakeTool(_recommend)
    session.tools.select_hotel = _never_called("select_hotel")

    reply = process_chat_turn(session, message)

    assert reply.text == "Khách sạn mới"
    assert captured["duration"] == "5 ngày"
    assert captured["people"] == "4 người"
    assert captured["start_date"] == "2026-08-10"
    assert captured["end_date"] == "2026-08-15"
    assert captured["min_price"] == "800000"
    assert captured["max_price"] == "2500000"
    assert session.trip_data is None


def test_duration_change_replaces_existing_hotel_candidates(monkeypatch):
    message = "đi 3 ngày nha"
    pending = {
        "mode": "new_trip",
        "destination": "Hồ Chí Minh",
        "duration": "2 ngày",
        "start_date": "2026-07-01",
        "end_date": "2026-07-03",
        "people": "2 người",
        "options": [{"id": "hotel-1", "name": "Khách sạn đang hiển thị"}],
    }
    session = _session(
        intake_state=TripIntakeState(
            destination="Hồ Chí Minh",
            duration="2 ngày",
            start_date="2026-07-01",
            stay_end_date="2026-07-03",
            people="2 người",
        ),
        hotel_pref_state=HotelPreferenceState(stage="done"),
        pending_hotel_selection=pending,
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Hồ Chí Minh",))
    _mock_intake_extraction(
        monkeypatch,
        {message: {"changed_fields": ["duration"], "duration_days": 3}},
    )
    def _recommend(args):
        session.pending_hotel_selection = {
            "mode": "new_trip",
            "duration": args["duration"],
            "start_date": args["start_date"],
            "end_date": args["end_date"],
            "options": [{"id": "hotel-2", "name": "Khách sạn mới"}],
        }
        return "Danh sách khách sạn mới"

    session.tools.recommend_hotels = _FakeTool(_recommend)
    session.tools.select_hotel = _never_called("select_hotel")

    reply = process_chat_turn(session, message)

    assert reply.text == "Danh sách khách sạn mới"
    assert session.pending_hotel_selection["options"] == [{"id": "hotel-2", "name": "Khách sạn mới"}]
    assert session.pending_hotel_selection["duration"] == "3 ngày"
    assert session.pending_hotel_selection["end_date"] == "2026-07-04"


def test_destination_change_replaces_pending_hotel_list_before_selection(monkeypatch):
    """A city named in a natural destination change must not be treated as a hotel pick."""
    message = "tôi đổi ý rồi, tôi muốn đi tp hcm hơn"
    session = _session(
        intake_state=TripIntakeState(
            destination="Nha Trang",
            duration="2 ngày",
            start_date="2026-07-01",
            people="2 người",
            preferences=("biển", "lịch sử"),
        ),
        hotel_pref_state=HotelPreferenceState(stage="done", min_price=800_000, max_price=2_500_000),
        pending_hotel_selection={"mode": "new_trip", "options": [{"name": "Khách sạn Nha Trang"}]},
    )
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Nha Trang", DestinationOption("Hồ Chí Minh", aliases=("TP HCM",))),
    )
    _mock_intake_extraction(
        monkeypatch,
        {message: {"changed_fields": ["destination"], "destination": "Hồ Chí Minh"}},
    )
    captured = {}

    def _recommend(args):
        captured.update(args)
        session.pending_hotel_selection = {
            "mode": "new_trip",
            "destination": args["destination"],
            "options": [{"name": "Khách sạn Hồ Chí Minh"}],
        }
        return "Danh sách khách sạn Hồ Chí Minh"

    session.tools.recommend_hotels = _FakeTool(_recommend)
    session.tools.select_hotel = _never_called("select_hotel")

    reply = process_chat_turn(session, message)

    assert reply.text.startswith("Danh sách khách sạn Hồ Chí Minh")
    assert reply.tool == "recommend_hotels"
    assert captured["destination"] == "Hồ Chí Minh"
    assert session.intake_state.destination == "Hồ Chí Minh"
    assert session.pending_hotel_selection["options"] == [{"name": "Khách sạn Hồ Chí Minh"}]


def test_optional_preference_change_keeps_pending_hotel_list(monkeypatch):
    message = "tôi muốn ưu tiên thiên nhiên"
    pending = {"mode": "new_trip", "options": [{"name": "Khách sạn hiện tại"}]}
    session = _session(
        intake_state=TripIntakeState(
            destination="Nha Trang",
            duration="2 ngày",
            start_date="2026-07-01",
            people="2 người",
            preferences=("biển",),
        ),
        hotel_pref_state=HotelPreferenceState(stage="done", min_price=800_000, max_price=2_500_000),
        pending_hotel_selection=pending,
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Nha Trang",))
    _mock_intake_extraction(
        monkeypatch,
        {message: {"changed_fields": ["preferences"], "preference_labels": ["thiên nhiên"]}},
    )
    session.tools.recommend_hotels = _never_called("recommend_hotels")
    session.tools.select_hotel = _never_called("select_hotel")

    reply = process_chat_turn(session, message)

    assert "đã cập nhật sở thích" in reply.text.casefold()
    assert reply.tool == "recommend_hotels"
    assert session.intake_state.preferences == ("thiên nhiên",)
    assert session.pending_hotel_selection is pending


def test_invalid_vibe_change_clears_stale_list_and_resumes_after_clarification(monkeypatch):
    message = "đổi vibe thành chill không giới hạn"
    clarification = "thiên nhiên"
    combined = f"{message}\nLàm rõ của người dùng: {clarification}"
    pending = {"mode": "new_trip", "options": [{"name": "Khách sạn hiện tại"}]}
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            start_date="2026-08-10",
            people="2 người",
            preferences=("biển",),
        ),
        hotel_pref_state=HotelPreferenceState(stage="done"),
        pending_hotel_selection=pending,
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(
        monkeypatch,
        {
            message: {
                "changed_fields": ["preferences"],
                "preference_labels": [],
            },
            combined: {
                "changed_fields": ["preferences"],
                "preference_labels": ["thiên nhiên"],
            },
        },
    )
    session.tools.select_hotel = _never_called("select_hotel")
    session.tools.recommend_hotels = _FakeTool(
        lambda args: (
            setattr(
                session,
                "pending_hotel_selection",
                {"mode": "new_trip", "preferences_text": args["preferences"], "options": []},
            )
            or "Danh sách mới"
        )
    )

    first_reply = process_chat_turn(session, message)

    assert session.pending_hotel_selection is None

    second_reply = process_chat_turn(session, clarification)

    assert "sở thích" in first_reply.text.casefold()
    assert second_reply.text == "Danh sách mới"
    assert session.pending_hotel_selection["preferences_text"] == "thiên nhiên"
    assert session.pending_trip_preference_request is None


def test_saved_draft_preference_change_prepares_replacement_without_mutating_draft(monkeypatch):
    original = {
        "hotel": {"id": "hotel-old"},
        "itineraries": [
            {
                "id": "trip-old",
                "status": "Draft",
                "destination_id": "dest-1",
                "duration_days": 3,
                "start_date": "2026-08-10",
                "end_date": "2026-08-13",
                "number_of_adults": 2,
                "preferences": ["Đà Nẵng", "biển"],
            }
        ],
        "itinerary_items": [{"id": "old-item"}],
    }
    update = TripPreferenceUpdate.from_raw(
        {
            "changed_fields": ["duration", "people", "preferences"],
            "duration_days": 5,
            "people_count": 4,
            "preference_labels": ["thiên nhiên"],
        }
    )
    session = _session(
        trip_data=original,
        initial_plan_complete=True,
        hotel_pref_state=HotelPreferenceState(stage="done", max_price=3_000_000),
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, data: TripEditPlan(
            decision="apply",
            summary="Đổi sở thích chuyến đi",
            operations=(EditOperation(operation="update_trip_preferences", trip_preferences=update),),
            raw_request=request,
        ),
    )
    captured = {}

    def _recommend(args):
        captured.update(args)
        session.pending_hotel_selection = {
            "mode": "new_trip",
            "destination": args["destination"],
            "duration": args["duration"],
            "start_date": args["start_date"],
            "end_date": args["end_date"],
            "people": args["people"],
            "preferences_text": args["preferences"],
            "options": [{"name": "Khách sạn mới"}],
        }
        return "Khách sạn mới"

    session.tools.recommend_hotels = _FakeTool(_recommend)

    reply = process_chat_turn(session, "đổi thành 5 ngày, 4 người, thích thiên nhiên")

    assert reply.text == "Khách sạn mới"
    assert session.trip_data is original
    assert original["itinerary_items"] == [{"id": "old-item"}]
    assert captured["end_date"] == "2026-08-15"
    assert captured["people"] == "4 người"
    assert captured["preferences"] == "thiên nhiên"
    assert session.pending_hotel_selection["mode"] == "replace_trip_preferences"


def test_preference_replacement_resumes_after_required_budget_question(monkeypatch):
    message = "đổi thành 5 ngày"
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            start_date="2026-08-10",
            people="2 người",
        ),
        hotel_pref_state=HotelPreferenceState(),
        pending_hotel_selection={"mode": "new_trip", "options": [{"name": "Khách sạn cũ"}]},
    )
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(
        monkeypatch,
        {message: {"changed_fields": ["duration"], "duration_days": 5}},
    )
    captured = {}

    def _recommend(args):
        captured.update(args)
        session.pending_hotel_selection = {"mode": "new_trip", "options": [{"name": "Khách sạn mới"}]}
        return "Khách sạn mới"

    session.tools.recommend_hotels = _FakeTool(_recommend)
    session.tools.select_hotel = _never_called("select_hotel")

    first_reply = process_chat_turn(session, message)
    second_reply = process_chat_turn(session, "4 triệu")

    assert "mức giá khách sạn" in first_reply.text.casefold()
    assert second_reply.text == "Khách sạn mới"
    assert captured["end_date"] == "2026-08-15"
    assert captured["max_price"] == "4000000.0"


def test_finalized_trip_rejects_preference_update_before_hotel_search() -> None:
    update = TripPreferenceUpdate.from_raw(
        {"changed_fields": ["duration"], "duration_days": 5}
    )
    session = _session(
        trip_data={"itineraries": [{"status": "Finalized", "duration_days": 3}]},
    )
    plan = TripEditPlan(
        decision="apply",
        summary="Đổi số ngày",
        operations=(EditOperation(operation="update_trip_preferences", trip_preferences=update),),
    )

    reply = execute_trip_edit_request(session, "đổi thành 5 ngày", plan)

    assert "không thể chỉnh sửa" in str(reply).casefold()
    assert session.pending_hotel_selection is None


def test_suggestions_are_declared_not_inferred_from_reply_text():
    """Chips must come from state. The model writes numbered prose constantly, and
    scanning replies for "1. ..." turned that prose into buttons that sent a bare
    "1" into turns wanting free text."""
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10", people="2 người"
        ),
        hotel_pref_state=HotelPreferenceState(),
    )

    chips = session_module.suggestions_for(session)

    assert [chip["value"] for chip in chips] == ["1", "2", "3", "4"]
    assert "Tiết kiệm" in chips[0]["label"]

    # Once the plan is done the turn wants free text — no chips at all.
    session.initial_plan_complete = True
    assert session_module.suggestions_for(session) == []


def test_suggestions_list_hotels_while_a_choice_is_pending():
    session = _session(
        pending_hotel_selection={
            "mode": "new_trip",
            "options": [{"name": "Khách sạn A"}, {"name": "Khách sạn B"}],
        }
    )

    chips = session_module.suggestions_for(session)

    assert chips == [
        {"label": "1. Khách sạn A", "value": "1"},
        {"label": "2. Khách sạn B", "value": "2"},
    ]


# --- Phase 1 contract fix: every return path must be a TurnResult, never a
# bare str (session.py previously leaked str on these three paths). ---


def test_unsupported_destination_reply_returns_turn_result(monkeypatch):
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]})

    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng", "Huế"))
    monkeypatch.setattr(
        session_module,
        "_llm_extract_intake_facts",
        lambda message, known, names, model=None: {"destination": "Hội An"},
    )

    result = process_chat_turn(session, "đi Hội An 2 ngày 2 người")

    assert isinstance(result, TurnResult)
    assert result.tool is None
    assert "Đà Nẵng" in result.text


def test_saved_trip_edit_planner_failure_returns_turn_result(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
    )

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("Unterminated string")),
    )

    result = process_chat_turn(session, "đổi bữa sáng ngày 1")

    assert isinstance(result, TurnResult)
    assert result.tool is None
    assert not result.text.startswith("SYSTEM ERROR:")
    assert "chưa thể xử lý" in result.text.casefold()


def test_saved_trip_hotel_change_falls_back_when_edit_planner_rejects_request(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
        initial_plan_complete=True,
    )
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("invalid JSON")),
    )
    captured = {}

    def _execute(_session, request, plan):
        captured["request"] = request
        captured["operation"] = plan.operations[0].operation
        _session.pending_hotel_selection = {"mode": "change_hotel", "options": []}
        return "Mình đã tìm danh sách khách sạn phù hợp."

    monkeypatch.setattr(session_module, "execute_trip_edit_request", _execute)

    result = process_chat_turn(session, "Tôi muốn đổi khách sạn")

    assert result.tool == "recommend_hotels"
    assert result.text == "Mình đã tìm danh sách khách sạn phù hợp."
    assert captured == {"request": "Tôi muốn đổi khách sạn", "operation": "change_hotel"}


def test_handle_frontend_hotel_change_skips_the_llm_edit_planner_and_leaves_no_chat_message(monkeypatch):
    """Backs POST /hotels/change (routes.py): the nav-triggered "đổi khách sạn"
    action already knows its intent, so it must never reach plan_trip_edit (an
    LLM call) and must never append a chat message pair — only the business
    state (pending_hotel_selection) changes."""
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
        initial_plan_complete=True,
    )
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not call the LLM edit planner")),
    )
    captured = {}

    def _execute(_session, request, plan):
        captured["request"] = request
        captured["operation"] = plan.operations[0].operation
        _session.pending_hotel_selection = {"mode": "change_hotel", "options": []}
        return "Mình đã tìm danh sách khách sạn phù hợp."

    monkeypatch.setattr(session_module, "execute_trip_edit_request", _execute)

    result = session_module.handle_frontend_hotel_change(session)

    assert result.tool == "execute_trip_edit_request"
    assert result.text == "Mình đã tìm danh sách khách sạn phù hợp."
    assert captured == {"request": "", "operation": "change_hotel"}
    assert session.state["messages"] == []


def test_handle_frontend_hotel_change_without_a_trip_fails_closed():
    session = _session()

    result = session_module.handle_frontend_hotel_change(session)

    assert result.text.startswith("SYSTEM ERROR:")


def test_frontend_trip_information_button_gets_a_clarifying_prompt_when_planner_rejects(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 1, "status": "Draft"}], "itinerary_items": []},
        initial_plan_complete=True,
    )
    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda *_args: (_ for _ in ()).throw(TripEditPlanError("invalid JSON")),
    )

    result = process_chat_turn(session, "Tôi muốn đổi thông tin chuyến đi")

    assert result.tool is None
    assert not result.text.startswith("SYSTEM ERROR:")
    assert "thông tin nào" in result.text.casefold()


def test_saved_trip_edit_clarification_returns_turn_result(monkeypatch):
    session = _session(
        trip_data={"itineraries": [{"duration_days": 3}]}, initial_plan_complete=True
    )

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, _data: TripEditPlan(
            decision="clarify",
            summary="Cần biết ngày áp dụng",
            clarification_question="Bạn muốn áp dụng cho ngày nào?",
            raw_request=request,
        ),
    )

    result = process_chat_turn(session, "buổi tối sau 20h tôi không muốn đi đâu nữa")

    assert isinstance(result, TurnResult)
    assert result.tool is None
    assert result.text == "Bạn muốn áp dụng cho ngày nào?"
