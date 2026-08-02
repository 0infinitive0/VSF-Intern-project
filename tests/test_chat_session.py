from __future__ import annotations

import pytest

import src.agents.session as session_module
import src.services.trip_intake as trip_intake_module
from src.agents.session import TripSession, TurnResult, process_chat_turn
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_edit_planner import TripEditPlan, TripEditPlanError
from src.services.trip_intake import TripIntakeState


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

    session = _session(intake_state=TripIntakeState(destination="Đà Nẵng", duration="3 ngày"))
    reply = process_chat_turn(session, "2 người").text

    # Trip intake completes the moment destination/duration/people are all known —
    # there is no dedicated preferences question — so the same turn immediately
    # starts the guided hotel-preference flow.
    assert session.intake_state.is_complete
    assert session.hotel_pref_state.stage == "pending_budget"
    assert "1." in reply


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
        },
    )

    first_reply = process_chat_turn(session, "tôi muốn đi chơi hcm").text
    second_reply = process_chat_turn(session, "3 ngày").text

    assert "bao lâu" in first_reply.casefold()
    assert "bao nhiêu người" in second_reply.casefold()
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


def test_suggestions_are_declared_not_inferred_from_reply_text():
    """Chips must come from state. The model writes numbered prose constantly, and
    scanning replies for "1. ..." turned that prose into buttons that sent a bare
    "1" into turns wanting free text."""
    session = _session(
        intake_state=TripIntakeState(destination="Đà Nẵng", duration="3 ngày", people="2 người"),
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
    assert result.text.startswith("SYSTEM ERROR:")


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
