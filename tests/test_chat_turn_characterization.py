"""Safety-net characterization tests for process_chat_turn, pinned against its
PUBLIC contract (TurnResult, derive_stage) so Phases 3-5 of
260802-1437-langgraph-full-orchestration-and-durable-state can rewrite the
internal cascade into a StateGraph without silently changing user-visible
behavior.

Reuses the stubbing seams tests/test_chat_session.py already established
(monkeypatch `decide_route_by_llm` to force the deterministic
`decide_route_by_rules` fallback; `_FakeTool`/`_FakeTools` for the four
agent-visible tools) rather than inventing new ones.

The hotel-pick gate invariant test is the most important test in this file:
today the gate is enforced structurally (`generate_full_itinerary` is never
registered with `create_react_agent`), a mechanism that Phase 4 dissolves.
This file pins the INVARIANT instead — no sequence of turns produces
itinerary items while a hotel selection is pending and unresolved — which
survives any implementation. See phase-02's Execution Notes for the
temporarily-broken-guard verification that this test actually has teeth.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict

import pytest

import src.agents.session as session_module
import src.services.trip_intake as trip_intake_module
from src.agents.session import (
    TripSession,
    TurnResult,
    derive_stage,
    process_chat_turn,
)
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_edit_planner import TripEditPlan
from src.services.trip_intake import TripIntakeState


@pytest.fixture(autouse=True)
def _no_live_supervisor(monkeypatch):
    """Force every process_chat_turn call through the deterministic
    decide_route_by_rules fallback — no live LLM, no Supabase, no
    non-determinism. Same seam as tests/test_chat_session.py."""
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
    def __init__(self):
        self.recommend_hotels = _never_called("recommend_hotels")
        self.select_hotel = _never_called("select_hotel")
        self.finalize_trip_plan = _never_called("finalize_trip_plan")
        self.modify_trip_plan = _never_called("modify_trip_plan")


def _session(**overrides) -> TripSession:
    defaults = dict(
        session_id="characterization-test",
        agent=object(),
        config={"configurable": {"thread_id": "characterization-test"}},
        tools=_FakeTools(),
    )
    defaults.update(overrides)
    return TripSession(**defaults)


def _mock_intake_extraction(monkeypatch, responses: dict[str, dict]) -> None:
    def fake(message, known_facts, destination_names, model=None):
        return responses.get(message, {})

    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", fake)


# --- One characterization test per Route -------------------------------------


def test_route_select_hotel(monkeypatch):
    session = _session(
        pending_hotel_selection={"mode": "new_trip", "options": [{"name": "Khách sạn A"}]}
    )

    def _fake_invoke(args):
        assert args == {"selection": "1"}
        session.pending_hotel_selection = None
        return "Đã chọn Khách sạn A cho chuyến đi của bạn."

    session.tools.select_hotel = _FakeTool(_fake_invoke)

    result = process_chat_turn(session, "1")

    assert isinstance(result, TurnResult)
    assert result.tool == "select_hotel"
    assert derive_stage(result) == "planned"
    assert "Khách sạn A" in result.text
    assert session.initial_plan_complete is True


def test_route_finalize(monkeypatch):
    session = _session(trip_data={"itineraries": [{"duration_days": 3}]})
    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)
    session.tools.finalize_trip_plan = _FakeTool(lambda args: "Đã chốt lịch trình của bạn.")

    result = process_chat_turn(session, "chốt lịch trình")

    assert result.tool == "finalize_trip_plan"
    assert derive_stage(result) == "finalized"
    assert "chốt" in result.text.casefold()
    assert session.initial_plan_complete is True


def test_route_new_trip(monkeypatch):
    """A strong 'new trip' signal on top of an existing saved plan bypasses the
    old draft and restarts intake — session.planning_new_trip flips True and
    the old trip_data is left untouched (not deleted), consumed only for
    routing, never for a reply."""
    session = _session(trip_data={"itineraries": [{"duration_days": 3, "status": "Finalized"}]})
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ())
    _mock_intake_extraction(monkeypatch, {})

    result = process_chat_turn(session, "cho tôi một chuyến đi mới")

    assert result.tool is None
    assert derive_stage(result) == "intake"
    assert session.planning_new_trip is True
    assert session.initial_plan_complete is False
    assert session.trip_data is not None  # old plan preserved, just bypassed


def test_route_edit_draft(monkeypatch):
    session = _session(trip_data={"itineraries": [{"duration_days": 3, "status": "Draft"}]})

    monkeypatch.setattr(
        session_module,
        "plan_trip_edit",
        lambda request, _data: TripEditPlan(decision="apply", summary="Đổi ngày 2", raw_request=request),
    )
    monkeypatch.setattr(session_module, "execute_trip_edit_request", lambda _s, request, plan: "Đã đổi ngày 2.")

    result = process_chat_turn(session, "đổi hoạt động ngày 2")

    assert result.tool == "execute_trip_edit_request"
    assert derive_stage(result) == "modified"
    assert "ngày 2" in result.text.casefold()


def test_route_intake(monkeypatch):
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng",))
    _mock_intake_extraction(monkeypatch, {"Tôi muốn đi Đà Nẵng": {"destination": "Đà Nẵng"}})

    session = _session()
    result = process_chat_turn(session, "Tôi muốn đi Đà Nẵng")

    assert result.tool is None
    assert derive_stage(result) == "intake"
    assert "bao lâu" in result.text.casefold()
    assert session.intake_state.destination == "Đà Nẵng"


def test_route_intake_tail_calls_recommend_hotels_and_reports_hotel_options_stage():
    """The intake route's final step (guided hotel-budget question resolved)
    calls recommend_hotels in the same turn — a distinct terminal stage
    ('hotel_options') worth pinning separately from the plain question-asking
    intake turn above."""
    session = _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10", people="2 người"
        ),
        hotel_pref_state=HotelPreferenceState(),
    )
    session.tools.recommend_hotels = _FakeTool(lambda args: "1. Khách sạn A\n2. Khách sạn B")

    result = process_chat_turn(session, "bao nhiêu cũng được")

    assert result.tool == "recommend_hotels"
    assert derive_stage(result) == "hotel_options"
    assert session.hotel_pref_state.is_complete


def test_route_chat(monkeypatch):
    class _FakeMessage:
        def __init__(self, type_, content="", tool_calls=None):
            self.type = type_
            self.content = content
            self.tool_calls = tool_calls or []
            self.name = "some_tool"

    class _FakeAgent:
        def stream(self, *_args, **_kwargs):
            yield {"messages": [_FakeMessage("ai", content="Đang xử lý...", tool_calls=[{"name": "modify_trip_plan"}])]}
            yield {"messages": [_FakeMessage("ai", content="Đây là câu trả lời chung.")]}

    session = _session(agent=_FakeAgent(), initial_plan_complete=True)
    result = process_chat_turn(session, "gợi ý thêm cho tôi")

    assert result.tool == "agent_stream"
    # Today's contract: the chat route's completed turns fall through the
    # unmapped default in _STAGE_MAP -> "intake". Surprising, but that is the
    # existing behavior this phase pins, not a bug this phase fixes.
    assert derive_stage(result) == "intake"
    assert result.text == "Đây là câu trả lời chung."


# --- Hotel-pick gate invariant -------------------------------------------------


def _session_with_pending_hotel_list() -> TripSession:
    """A session that has completed intake + hotel prefs and just received a
    hotel list — pending_hotel_selection is set, trip_data is still None. This
    is the exact state the gate must hold from."""
    return _session(
        intake_state=TripIntakeState(
            destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10", people="2 người"
        ),
        hotel_pref_state=HotelPreferenceState(stage="done"),
        pending_hotel_selection={
            "mode": "new_trip",
            "destination": "Đà Nẵng",
            "duration": "3 ngày",
            "people": "2 người",
            "options": [{"name": "Khách sạn A"}, {"name": "Khách sạn B"}],
        },
    )


def _never_resolves_selection(_args):
    return "Mình chưa xác định được đúng khách sạn bạn muốn chọn."


def _assert_no_itinerary_leaked(session: TripSession) -> None:
    assert session.trip_data is None
    assert session.initial_plan_complete is False


def test_gate_invariant_finalize_attempt_without_hotel_pick_produces_no_itinerary(monkeypatch):
    session = _session_with_pending_hotel_list()
    session.tools.select_hotel = _FakeTool(_never_resolves_selection)
    session.tools.recommend_hotels = _FakeTool(lambda args: "1. Khách sạn A\n2. Khách sạn B")
    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)

    result = process_chat_turn(session, "chốt lịch trình")

    _assert_no_itinerary_leaked(session)
    # Dropped list + no trip_data yet -> re-routes into intake, not finalize.
    assert result.tool != "finalize_trip_plan"


def test_gate_invariant_edit_attempt_without_hotel_pick_produces_no_itinerary():
    session = _session_with_pending_hotel_list()
    session.tools.select_hotel = _FakeTool(_never_resolves_selection)
    session.tools.recommend_hotels = _FakeTool(lambda args: "1. Khách sạn A\n2. Khách sạn B")

    result = process_chat_turn(session, "đổi khách sạn khác đi")

    _assert_no_itinerary_leaked(session)
    assert result.tool != "execute_trip_edit_request"


def test_gate_invariant_neutral_chat_without_hotel_pick_produces_no_itinerary():
    """A message with no finalize/edit/new-trip signal at all is read as a
    (failed) attempt at the hotel pick itself — select_hotel runs, the list
    stays pending, and no itinerary appears either way."""
    session = _session_with_pending_hotel_list()
    session.tools.select_hotel = _FakeTool(_never_resolves_selection)

    result = process_chat_turn(session, "trời hôm nay đẹp quá")

    _assert_no_itinerary_leaked(session)
    assert result.tool == "select_hotel"
    assert session.pending_hotel_selection is not None


# --- Re-route / drop-pending-list ---------------------------------------------


def test_dropped_pending_list_is_handled_for_what_the_message_actually_is(monkeypatch):
    """Pins session.py's re-route behavior (session.py:444-446): a pending
    hotel list must not swallow every later message forever. When the reply
    is clearly not a hotel pick, the list is dropped and the turn is
    re-decided against the message's real intent."""
    session = _session(
        pending_hotel_selection={"mode": "new_trip", "options": []},
        trip_data={"itineraries": [{"duration_days": 3}]},
    )
    session.tools.select_hotel = _FakeTool(lambda args: "Mình chưa xác định được...")
    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)
    session.tools.finalize_trip_plan = _FakeTool(lambda args: "Đã chốt lịch trình.")

    result = process_chat_turn(session, "chốt lịch trình này")

    assert result.tool == "finalize_trip_plan"
    assert derive_stage(result) == "finalized"
    assert session.pending_hotel_selection is None


def test_out_of_range_number_keeps_the_pending_list_instead_of_dropping_it():
    """Guards the re-route fix from over-firing: a bare number is always read
    as a pick attempt, even out of range, so the list must NOT be dropped."""
    session = _session(pending_hotel_selection={"mode": "new_trip", "options": []})
    session.tools.select_hotel = _FakeTool(lambda args: "Mình chưa xác định được...")

    result = process_chat_turn(session, "9")

    assert result.tool == "select_hotel"
    assert result.text == "Mình chưa xác định được..."
    assert session.pending_hotel_selection is not None


# --- TripIntakeState / HotelPreferenceState JSON round-trip -------------------


def test_trip_intake_state_json_round_trip_requires_explicit_tuple_coercion():
    """The one known serialization wrinkle Phase 3 depends on handling: JSON
    has no tuple type, so a naive `TripIntakeState(**json.loads(...))`
    reconstruction silently turns `preferences` into a list and breaks
    equality. This test pins that the wrinkle exists AND that explicit
    coercion fixes it."""
    state = TripIntakeState(
        destination="Đà Nẵng", duration="3 ngày", people="2 người", preferences=("biển", "ẩm thực")
    )

    payload = json.loads(json.dumps(asdict(state)))
    assert payload["preferences"] == ["biển", "ẩm thực"]

    naive_reconstruction = TripIntakeState(**payload)
    assert naive_reconstruction != state  # list != tuple -> dataclass equality fails

    corrected = TripIntakeState(**{**payload, "preferences": tuple(payload["preferences"])})
    assert corrected == state


def test_hotel_preference_state_json_round_trip():
    """No tuple fields here, so this one is a plain round-trip with no
    coercion wrinkle — pinned mainly to document the contrast with
    TripIntakeState above."""
    state = HotelPreferenceState(stage="done", target_price=4_000_000.0, min_price=800_000.0, max_price=2_500_000.0)

    payload = json.loads(json.dumps(asdict(state)))
    reconstructed = HotelPreferenceState(**payload)

    assert reconstructed == state


# --- Latency baseline ----------------------------------------------------------


def test_measure_and_write_latency_baseline(monkeypatch):
    """Not a correctness test — runs every route above's turn N times each and
    writes p50/p95 wall time per route to plans/reports/ so Phase 6 has a
    number to compare against. Skipped from the "did it pass" question; its
    job is the side-effect report file."""
    from pathlib import Path

    import src.agents.routing_decision as routing_module

    monkeypatch.setattr(routing_module, "is_finalization_request", lambda text: True)
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ())
    monkeypatch.setattr(trip_intake_module, "_llm_extract_intake_facts", lambda *args, **kwargs: {})

    samples: dict[str, list[float]] = {}

    def _timed(label: str, fn) -> None:
        times = []
        for _ in range(20):
            start = time.perf_counter()
            fn()
            times.append(time.perf_counter() - start)
        samples[label] = times

    def _run_select_hotel():
        session = _session(pending_hotel_selection={"mode": "new_trip", "options": [{"name": "A"}]})
        session.tools.select_hotel = _FakeTool(
            lambda args: (setattr(session, "pending_hotel_selection", None), "ok")[1]
        )
        process_chat_turn(session, "1")

    def _run_finalize():
        session = _session(trip_data={"itineraries": [{"duration_days": 3}]})
        session.tools.finalize_trip_plan = _FakeTool(lambda args: "ok")
        process_chat_turn(session, "chốt lịch trình")

    def _run_intake():
        session = _session()
        process_chat_turn(session, "xin chào")

    def _run_chat():
        class _FakeMessage:
            type = "ai"
            tool_calls = []
            content = "Đây là câu trả lời chung."

        class _FakeAgent:
            def stream(self, *_args, **_kwargs):
                yield {"messages": [_FakeMessage()]}

        session = _session(agent=_FakeAgent(), initial_plan_complete=True)
        process_chat_turn(session, "gợi ý thêm cho tôi")

    _timed("select_hotel", _run_select_hotel)
    _timed("finalize", _run_finalize)
    _timed("intake", _run_intake)
    _timed("chat", _run_chat)

    def _percentile(values: list[float], pct: float) -> float:
        ordered = sorted(values)
        index = min(len(ordered) - 1, int(len(ordered) * pct))
        return ordered[index]

    lines = [
        "# Phase 2 turn-latency baseline (2026-08-02)",
        "",
        "Measured with the LLM/Supabase boundary fully stubbed (see this file's",
        "fixtures) — this is process_chat_turn's own Python overhead, NOT",
        "end-to-end latency including a live model call. It exists so Phase 6 can",
        "re-measure the same way and compare like-for-like; it is not a",
        "production latency figure.",
        "",
        "Conditions: warm interpreter (run inside the full pytest session, not",
        "cold-started), 20 samples per route, local dev machine, no network.",
        "",
        "| Route | p50 (ms) | p95 (ms) |",
        "|---|---|---|",
    ]
    for label, times in samples.items():
        p50 = _percentile(times, 0.50) * 1000
        p95 = _percentile(times, 0.95) * 1000
        lines.append(f"| {label} | {p50:.3f} | {p95:.3f} |")

    report_path = Path(__file__).resolve().parents[1] / "plans" / "reports" / "baseline-260802-turn-latency.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
