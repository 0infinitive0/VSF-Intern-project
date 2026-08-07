"""test_chat_stream.py — Phase 1: SSE transport & contract.

Covers POST /api/v1/planner_chat/stream with process_chat_turn mocked (no
Supabase / Ollama / LLM calls):

  - unknown session → plain 404 (not an SSE stream)
  - frame order: `: open` → `phase: received` → `final`, exactly one terminal
    frame per stream
  - `final` data matches the POST /planner_chat body on the same scenario
    (both endpoints must share build_chat_response)
  - turn exceptions → `error` frame (not `final`), stream still terminates
  - log_api_io middleware: old POST path keeps full input+output logging;
    streaming path logs input + passthrough marker, never buffered output

All assertions run through the real ASGI app including middleware.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import src.agents.session as session_module
import src.api.routes as routes_module
from src.agents.session import SessionRegistry, TripSession, TurnResult
from src.api.streaming import emit_phase

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_chat_flow.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Đà Nẵng", "Nha Trang", "Hội An"),
    )


@pytest.fixture()
def fresh_registry(monkeypatch):
    """Fresh registry with stubbed session factory (no LLM)."""

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


def _mock_turn(monkeypatch, result: TurnResult) -> None:
    def _fake_turn(*_a, **_kw):
        # Mirrors the real process_chat_turn's first action (session.py) so
        # frame-order assertions against a mocked turn still see the
        # `received` phase the stream endpoint's emitting_to() context
        # depends on.
        emit_phase("received")
        return result

    monkeypatch.setattr(routes_module, "process_chat_turn", _fake_turn)
    monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _session(client) -> str:
    resp = await client.post("/api/v1/chat/session")
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse complete SSE frames into (event, data) pairs.

    Comment frames (': open', ': heartbeat') are skipped — they carry no
    event/data lines.
    """
    frames: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        if all(line.startswith(":") for line in lines):
            continue  # comment frame
        event = next(line.removeprefix("event:").strip() for line in lines if line.startswith("event:"))
        data_line = next(line.removeprefix("data:").strip() for line in lines if line.startswith("data:"))
        frames.append((event, json.loads(data_line)))
    return frames


# ---------------------------------------------------------------------------
# Stream endpoint behaviour
# ---------------------------------------------------------------------------


class TestStreamEndpoint:
    @pytest.mark.asyncio
    async def test_unknown_session_returns_plain_404(self, client, fresh_registry):
        import uuid

        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": str(uuid.uuid4()), "message": "test"},
        )
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")

    @pytest.mark.asyncio
    async def test_frame_order_and_single_terminal_frame(
        self, client, fresh_registry, monkeypatch
    ):
        sid = await _session(client)
        _mock_turn(monkeypatch, TurnResult(text="Xin chào! Bạn đi bao nhiêu ngày?", tool=None))

        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid, "message": "Đà Nẵng"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"

        # First frame must be the `: open` comment — forces proxies to flush.
        assert resp.text.startswith(": open\n\n")

        frames = _parse_sse(resp.text)
        events = [event for event, _ in frames]
        assert events == ["phase", "final"]

        phase = frames[0][1]
        assert phase["key"] == "received"
        assert "at" in phase

        final = frames[1][1]
        for key in (
            "session_id",
            "reply",
            "suggestions",
            "stage",
            "hotel_options",
            "trip_plan",
            "intake",
            "requires_stay_dates",
        ):
            assert key in final, f"final frame missing PlannerChatResponse key {key!r}"
        assert final["reply"] == "Xin chào! Bạn đi bao nhiêu ngày?"

    @pytest.mark.asyncio
    async def test_final_matches_post_body_on_same_scenario(
        self, client, fresh_registry, monkeypatch
    ):
        """`final` of the stream must equal the POST body (minus session_id,
        which differs because the two calls use two sessions)."""
        _mock_turn(monkeypatch, TurnResult(text="Chào bạn!", tool=None))

        sid_post = await _session(client)
        resp_post = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": sid_post, "message": "hello"},
        )
        assert resp_post.status_code == 200

        sid_stream = await _session(client)
        resp_stream = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid_stream, "message": "hello"},
        )
        assert resp_stream.status_code == 200

        frames = _parse_sse(resp_stream.text)
        (final_event, final_data), *_ = [f for f in frames if f[0] == "final"]
        assert final_event == "final"

        post_data = resp_post.json()
        final_data.pop("session_id")
        post_data.pop("session_id")
        assert final_data == post_data

    @pytest.mark.asyncio
    async def test_turn_exception_emits_error_frame_not_final(
        self, client, fresh_registry, monkeypatch
    ):
        def _boom(*a, **kw):
            raise RuntimeError("synthetic failure")

        monkeypatch.setattr(routes_module, "process_chat_turn", _boom)
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])

        sid = await _session(client)
        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid, "message": "hello"},
        )
        assert resp.status_code == 200  # stream opened before the failure

        frames = _parse_sse(resp.text)
        events = [event for event, _ in frames]
        assert "final" not in events
        assert events[-1] == "error"
        detail = frames[-1][1]["detail"]
        # Sanitized: no internal exception text leaks into the frame.
        assert "synthetic" not in detail
        assert detail == "Đã xảy ra lỗi máy chủ. Vui lòng thử lại."

    @pytest.mark.asyncio
    async def test_error_frame_is_terminal(self, client, fresh_registry, monkeypatch):
        """Exactly one terminal frame after the first event, stream ends."""
        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(routes_module, "process_chat_turn", _boom)

        sid = await _session(client)
        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid, "message": "x"},
        )
        frames = _parse_sse(resp.text)
        terminal = [e for e, _ in frames if e in ("final", "error")]
        assert terminal == ["error"]
        assert frames[-1][0] == "error"


# ---------------------------------------------------------------------------
# Middleware: logging behaviour preserved for non-streaming paths
# ---------------------------------------------------------------------------


class TestMiddlewareStreamingBypass:
    @pytest.mark.asyncio
    async def test_old_post_keeps_full_input_and_output_logging(
        self, client, fresh_registry, monkeypatch, capsys
    ):
        """POST /planner_chat must still log input AND output as before —
        the early-exit must not change any other endpoint's logging."""
        sid = await _session(client)
        _mock_turn(monkeypatch, TurnResult(text="log check", tool=None))

        capsys.readouterr()  # discard session-creation logs
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": sid, "message": "hello log"},
        )
        assert resp.status_code == 200

        out = capsys.readouterr().out
        assert "[API INPUT] POST /api/v1/planner_chat" in out
        assert "[API OUTPUT] POST /api/v1/planner_chat" in out
        # The output line carries the response payload (i.e. was buffered as before).
        assert "log check" in out

    @pytest.mark.asyncio
    async def test_stream_path_logs_input_and_passthrough_not_buffered_output(
        self, client, fresh_registry, monkeypatch, capsys
    ):
        sid = await _session(client)
        _mock_turn(monkeypatch, TurnResult(text="stream body must not be logged", tool=None))

        capsys.readouterr()
        resp = await client.post(
            "/api/v1/planner_chat/stream",
            json={"session_id": sid, "message": "hello stream"},
        )
        assert resp.status_code == 200

        out = capsys.readouterr().out
        assert "[API INPUT] POST /api/v1/planner_chat/stream" in out
        assert "[API STREAM] POST /api/v1/planner_chat/stream" in out
        # Buffering would print the reply text via the [API OUTPUT] line.
        assert "[API OUTPUT] POST /api/v1/planner_chat/stream" not in out
        assert "stream body must not be logged" not in out
