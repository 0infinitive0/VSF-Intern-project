"""test_phase_events.py — Phase 2: turn-progress instrumentation (plan 260806-1602).

Guards the anti-fake-progress rule from phase-02: every `phase` key fires at a
real code position, per-branch key sets are exact (both presence AND absence),
`emit_phase` never raises and is a free no-op on the plain POST path, and the
ContextVar cannot leak between turns on a reused thread.

No Supabase / Ollama / LLM calls: branch internals are exercised via
state-level doubles or module-level patches.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.agents.session as session_module
import src.api.routes as routes_module
import src.services.routing as routing_module
import src.services.trip_planner as trip_planner_module
from src.agents.session import SessionRegistry, TripSession, TurnResult
from src.api.streaming import _current_emitter, emit_phase, emitting_to

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Capture:
    """Drop-in TurnEmitter double recording events into a list (no queue)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event: str, **data) -> None:
        self.events.append((event, data))

    def keys(self) -> list[str]:
        return [data["key"] for event, data in self.events if event == "phase"]


def _make_session() -> TripSession:
    session = TripSession(
        session_id="phase-test",
        agent=MagicMock(),
        config={"configurable": {"thread_id": "phase-test"}},
    )
    tools = MagicMock()
    tools.select_hotel = MagicMock()
    tools.finalize_trip_plan = MagicMock()
    tools.recommend_hotels = MagicMock()
    session.tools = tools
    return session


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Đà Nẵng", "Nha Trang", "Hội An"),
    )


def _router_flag(monkeypatch, on: bool) -> None:
    monkeypatch.setattr(
        session_module,
        "get_settings",
        lambda: SimpleNamespace(trip_supervisor_router=on),
    )


# ---------------------------------------------------------------------------
# process_chat_turn: received / routing / route_decided
# ---------------------------------------------------------------------------


class TestTurnLevelKeys:
    def test_received_and_route_decided_emitted(self, monkeypatch):
        _router_flag(monkeypatch, on=False)
        monkeypatch.setattr(
            session_module, "_run_intake", lambda s, u, stream=False: TurnResult(text="q?", tool=None)
        )
        cap = _Capture()
        with emitting_to(cap):
            session_module.process_chat_turn(_make_session(), "Đà Nẵng")
        keys = cap.keys()
        assert keys[0] == "received"
        assert "route_decided" in keys
        # flag off → no LLM supervisor call → `routing` must NOT fire.
        assert "routing" not in keys
        # intake-turn must not claim work it didn't do:
        assert "hotel_search" not in keys
        assert "itinerary_build" not in keys
        assert "persisting" not in keys

    def test_route_decided_carries_label(self, monkeypatch):
        _router_flag(monkeypatch, on=False)
        monkeypatch.setattr(
            session_module, "_run_intake", lambda s, u, stream=False: TurnResult(text="q?", tool=None)
        )
        cap = _Capture()
        with emitting_to(cap):
            session_module.process_chat_turn(_make_session(), "Đà Nẵng")
        decided = [data for event, data in cap.events if data.get("key") == "route_decided"]
        assert decided and isinstance(decided[0].get("route"), str) and decided[0]["route"]

    def test_routing_only_when_supervisor_flag_on(self, monkeypatch):
        _router_flag(monkeypatch, on=True)
        # Stub the supervisor LLM so nothing external is called; the
        # deterministic fallback/validation machinery decides the final label.
        monkeypatch.setattr(session_module, "decide_route_by_llm", lambda s, u: None)
        monkeypatch.setattr(
            session_module, "_run_intake", lambda s, u, stream=False: TurnResult(text="q?", tool=None)
        )
        cap = _Capture()
        with emitting_to(cap):
            session_module.process_chat_turn(_make_session(), "Đà Nẵng")
        assert "routing" in cap.keys()


# ---------------------------------------------------------------------------
# Branch-level keys
# ---------------------------------------------------------------------------


class TestBranchKeys:
    def test_intake_check_fires_in_intake_only(self):
        session = _make_session()
        state = MagicMock()
        state.destination = None
        state.people = None
        state.with_message.return_value = state
        state.next_question.return_value = "Bạn dự định đi trong bao lâu?"
        session.intake_state = state

        cap = _Capture()
        with emitting_to(cap):
            result = session_module._run_intake(session, "xin chào")

        assert result.tool is None
        keys = cap.keys()
        assert "intake_check" in keys
        assert "hotel_search" not in keys
        # `received` belongs to process_chat_turn, not to branch functions:
        assert "received" not in keys

    def test_hotel_search_fires_before_recommend_invoke(self):
        from src.services.hotel_selection import HotelPreferenceState
        from src.services.trip_intake import TripIntakeState

        session = _make_session()
        session.intake_state = TripIntakeState(
            destination="Đà Nẵng",
            duration="3 ngày",
            start_date="2026-10-12",
            stay_end_date="2026-10-15",
            people="2",
        )
        session.hotel_pref_state = HotelPreferenceState(stage="done")
        session.tools.recommend_hotels.invoke.return_value = "1. Fusion Resort"

        cap = _Capture()
        with emitting_to(cap):
            result = session_module._run_recommend_hotels(session)

        assert result.tool == "recommend_hotels"
        hotel_events = [data for _, data in cap.events if data.get("key") == "hotel_search"]
        assert len(hotel_events) == 1
        assert hotel_events[0]["tool"] == "recommend_hotels"
        assert "itinerary_build" not in cap.keys()
        assert "persisting" not in cap.keys()

    def test_tool_start_and_end_in_agent_loop(self):
        """_run_chat_agent emits tool_start/tool_end next to its existing logs."""

        class _Msg:
            def __init__(self, type_, content="", name=None, tool_calls=None):
                self.type = type_
                self.content = content
                self.name = name
                self.tool_calls = tool_calls or []
                self.id = None

        session = _make_session()
        # stream=False (default) -> stream_mode="values" -> bare event dicts,
        # exactly as before phase-03 (the list/tuple shape only applies when
        # stream=True — see _run_chat_agent's docstring).
        session.agent.stream.return_value = iter(
            [
                {"messages": [_Msg("ai", tool_calls=[{"name": "recommend_hotels"}])]},
                {"messages": [_Msg("tool", content="2 hotels", name="recommend_hotels")]},
                {"messages": [_Msg("ai", content="Đây là 2 khách sạn phù hợp nhé!")]},
            ]
        )
        session.agent.get_state.return_value = MagicMock(values={"messages": []})

        cap = _Capture()
        with emitting_to(cap):
            result = session_module._run_chat_agent(session, "gợi ý khách sạn")

        assert result.text.startswith("Đây là 2 khách sạn")
        keys = cap.keys()
        assert keys == ["tool_start", "tool_end"]
        assert cap.events[0][1]["tool"] == "recommend_hotels"
        assert cap.events[1][1]["tool"] == "recommend_hotels"

    def test_prose_before_a_tool_call_is_reset_not_conflated_with_final_reply(self):
        """Regression: the agent can emit prose ("Let me check...") BEFORE
        deciding to call a tool — that prose has empty tool_calls/
        tool_call_chunks while streaming, so the gate lets it through as
        delta. It must not leak into the SAME delta stream as the real final
        answer that comes after the tool round: a `reset` must fire, and the
        post-reset deltas alone must equal final.reply."""

        class _Msg:
            def __init__(self, type_, content="", name=None, tool_calls=None, tool_call_chunks=None):
                self.type = type_
                self.content = content
                self.name = name
                self.tool_calls = tool_calls or []
                self.tool_call_chunks = tool_call_chunks or []
                self.id = None

        session = _make_session()
        session.agent.stream.return_value = iter(
            [
                ("messages", (_Msg("ai", content="Để mình kiểm tra "), {"langgraph_node": "agent"})),
                ("messages", (_Msg("ai", content="giúp bạn nhé... "), {"langgraph_node": "agent"})),
                ("values", {"messages": [_Msg("ai", tool_calls=[{"name": "recommend_hotels"}])]}),
                ("values", {"messages": [_Msg("tool", content="2 hotels", name="recommend_hotels")]}),
                ("messages", (_Msg("ai", content="Đây là khách sạn phù hợp."), {"langgraph_node": "agent"})),
                ("values", {"messages": [_Msg("ai", content="Đây là khách sạn phù hợp.")]}),
            ]
        )
        session.agent.get_state.return_value = MagicMock(values={"messages": []})

        cap = _Capture()
        with emitting_to(cap):
            result = session_module._run_chat_agent(session, "gợi ý khách sạn", stream=True)

        assert result.text == "Đây là khách sạn phù hợp."
        # The pre-tool-call chatter DID already reach the wire as delta (a
        # stream can't un-send bytes) — `reset` is the signal telling the
        # client to discard everything buffered so far. The invariant that
        # must hold is downstream of the LAST reset: those deltas alone
        # equal final.reply, never anything from before the tool round.
        assert "reset" in [e for e, _ in cap.events]
        reset_index = max(i for i, (e, _) in enumerate(cap.events) if e == "reset")
        deltas_after_reset = [d["text"] for e, d in cap.events[reset_index + 1 :] if e == "delta"]
        assert "".join(deltas_after_reset) == result.text

    def test_compacting_history_only_when_actually_compacting(self, monkeypatch):
        class _Msg:
            def __init__(self, id_, content):
                self.id = id_
                self.type = "ai"
                self.content = content

        fake_llm = MagicMock()
        fake_llm.invoke.return_value = MagicMock(content="tóm tắt")
        monkeypatch.setattr("src.services.llm.get_fast_llm", lambda temperature=0.0: fake_llm)

        session = _make_session()
        session.agent.get_state.return_value = MagicMock(
            values={"messages": [_Msg(f"m{i}", "x" * 6000) for i in range(6)]}
        )

        cap = _Capture()
        with emitting_to(cap):
            session_module._compact_history(session)
        assert cap.keys() == ["compacting_history"]
        fake_llm.invoke.assert_called_once()
        session.agent.update_state.assert_called_once()

        # Below the threshold → early return → key must NOT fire.
        cap2 = _Capture()
        session.agent.get_state.return_value = MagicMock(
            values={"messages": [_Msg("m1", "ngắn gọn")]}
        )
        session.agent.update_state.reset_mock()
        with emitting_to(cap2):
            session_module._compact_history(session)
        assert cap2.keys() == []
        session.agent.update_state.assert_not_called()


# ---------------------------------------------------------------------------
# Service-level keys
# ---------------------------------------------------------------------------


class TestServiceKeys:
    def test_itinerary_build_at_generation_entry(self, monkeypatch):
        monkeypatch.setattr(trip_planner_module, "_build_trip_data", lambda *a, **kw: {"ok": True})
        monkeypatch.setattr(
            trip_planner_module, "format_trip_response_from_json", lambda td, lang: "formatted"
        )

        cap = _Capture()
        with emitting_to(cap):
            result = trip_planner_module._generate_and_save_itinerary(
                "Đà Nẵng", "3 ngày", "2 người", save=lambda trip_data: None
            )
        assert result == "formatted"
        assert cap.keys() == ["itinerary_build"]  # save callback persisted nothing

    def test_persisting_before_first_write_and_not_on_guard_return(self, monkeypatch):
        written: list[str] = []
        monkeypatch.setattr(
            trip_planner_module,
            "get_supabase_client",
            lambda: MagicMock(table=lambda name: written.append(name) or MagicMock()),
        )
        store = MagicMock()
        store.persist_itinerary_bundle = MagicMock(return_value=None)
        monkeypatch.setattr(
            trip_planner_module.ItineraryStore, "from_default", staticmethod(lambda: store)
        )

        cap = _Capture()
        with emitting_to(cap):
            trip_planner_module._persist_itinerary_metadata(
                {"itineraries": [{"id": "it-1", "session_id": "s-1"}]}
            )
        assert cap.keys() == ["persisting"]
        store.persist_itinerary_bundle.assert_called_once()

        guard_trip = {"itineraries": [{"session_id": "s-1"}]}  # dict WITHOUT id
        cap2 = _Capture()
        store.persist_itinerary_bundle.reset_mock()
        with emitting_to(cap2):
            trip_planner_module._persist_itinerary_metadata(guard_trip)
        assert cap2.keys() == []
        store.persist_itinerary_bundle.assert_not_called()

    def test_routing_legs_once_per_recalculation(self, monkeypatch):
        monkeypatch.setattr(
            routing_module.MapboxDirectionsClient,
            "get_route_info_batch",
            staticmethod(
                lambda coords, profile: [
                    {"distance_km": 1.0, "duration_mins": 5.0, "polyline": "x", "profile": profile}
                ]
                * max(0, len(coords) - 1)
            ),
        )
        trip_data = {
            "itinerary_items": [
                {"day_number": 1, "order_index": 1, "coordinates": "16.0544,108.2022"},
                {"day_number": 1, "order_index": 2, "coordinates": "16.0490,108.2493"},
            ]
        }

        cap = _Capture()
        with emitting_to(cap):
            routing_module.recalculate_itinerary_routes(trip_data)
        assert cap.keys() == ["routing_legs"]
        assert cap.events[0][1].get("days") == 1

        # Not a list of items → no work → no key.
        cap2 = _Capture()
        with emitting_to(cap2):
            routing_module.recalculate_itinerary_routes({"itinerary_items": "junk"})
        assert cap2.keys() == []


# ---------------------------------------------------------------------------
# Plumbing invariants
# ---------------------------------------------------------------------------


class TestPlumbingInvariants:
    def test_emit_phase_is_noop_without_emitter(self):
        # No emitting_to wrapper → plain POST path semantics.
        emit_phase("received")  # must not raise

    def test_emit_phase_swallows_broken_emitters(self):
        class _Boom:
            def emit(self, *a, **kw):
                raise RuntimeError("boom")

        with emitting_to(_Boom()):
            emit_phase("received")  # a broken emitter must never kill a turn

    def test_emitting_to_resets_between_turns(self):
        cap = _Capture()
        with emitting_to(cap):
            emit_phase("received")
        # After the block the contextvar is reset — a reused thread-pool
        # thread must see None for the next, non-streaming task.
        assert _current_emitter.get() is None
        cap2 = _Capture()
        emit_phase("leaked?")  # no-op, goes nowhere
        assert [d["key"] for _, d in cap2.events] == []
        assert [d["key"] for _, d in cap.events] == ["received"]

    def test_emit_carries_opaque_key_and_timestamp(self):
        cap = _Capture()
        with emitting_to(cap):
            emit_phase("hotel_search", tool="recommend_hotels")
        event, data = cap.events[0]
        assert event == "phase"
        assert data["key"] == "hotel_search"
        assert data["tool"] == "recommend_hotels"
        assert isinstance(data["at"], float)


# ---------------------------------------------------------------------------
# End-to-end plumbing through the stream endpoint
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_registry(monkeypatch):
    """Fresh registry with stubbed session factory (mirrors test_chat_stream)."""

    def _stub_create(session_id, **kwargs):
        session = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
        )
        tools = MagicMock()
        tools.select_hotel = MagicMock()
        tools.finalize_trip_plan = MagicMock()
        tools.recommend_hotels = MagicMock()
        session.tools = tools
        return session

    monkeypatch.setattr(session_module, "create_chat_session", _stub_create)
    reg = SessionRegistry(ttl_seconds=3600, cap=50)
    monkeypatch.setattr(routes_module, "registry", reg)
    return reg


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block or all(line.startswith(":") for line in block.splitlines()):
            continue
        lines = block.splitlines()
        event = next(line.removeprefix("event:").strip() for line in lines if line.startswith("event:"))
        data_line = next(line.removeprefix("data:").strip() for line in lines if line.startswith("data:"))
        frames.append((event, json.loads(data_line)))
    return frames


class TestStreamWiring:
    @pytest.mark.asyncio
    async def test_phase_keys_reach_sse_frames(self, client, fresh_registry, monkeypatch):
        """received → route_decided → intake_check as real frames over SSE."""
        _router_flag(monkeypatch, on=False)
        # Real _run_intake on the fresh empty intake state; only the LLM fact
        # extractor is stubbed (returns no facts) so nothing external is called.
        monkeypatch.setattr("src.services.trip_intake._llm_extract_intake_facts", lambda *a, **kw: {})
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])

        resp = await client.post("/api/v1/chat/session")
        sid = resp.json()["session_id"]
        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid, "message": "hello"},
        )
        assert resp.status_code == 200
        frames = _parse_sse(resp.text)
        keys = [data["key"] for event, data in frames if event == "phase"]
        assert keys == ["received", "route_decided", "intake_check"]
        assert frames[-1][0] == "final"
        # Every key carries the opaque-shape fields only (no display text).
        for event, data in frames:
            if event == "phase":
                assert "text" not in data and "label" not in data

    @pytest.mark.asyncio
    async def test_post_turn_sees_no_emitter(self, client, fresh_registry, monkeypatch):
        """POST /planner_chat runs the same code but emit_phase is a pure no-op."""
        _router_flag(monkeypatch, on=False)
        seen: list[object] = []
        real_turn = session_module.process_chat_turn

        def probe(*args, **kwargs):
            seen.append(_current_emitter.get())
            return real_turn(*args, **kwargs)

        monkeypatch.setattr(routes_module, "process_chat_turn", probe)
        monkeypatch.setattr(
            session_module, "_run_intake", lambda s, u, stream=False: TurnResult(text="q?", tool=None)
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])

        resp = await client.post("/api/v1/chat/session")
        sid = resp.json()["session_id"]
        resp = await client.post(
            "/api/v1/planner_chat", json={"session_id": sid, "message": "hello"}
        )
        assert resp.status_code == 200
        assert seen == [None]
