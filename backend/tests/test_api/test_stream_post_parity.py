"""test_stream_post_parity.py — Phase 6 (plan 260806-1602-streaming-chat-messages).

Guards the plan's two most important invariants, on the REAL `process_chat_turn`
and REAL routing (only the LLM supervisor and the four session.tools/agent
boundaries are stubbed — no Supabase/Ollama calls), driven through the actual
HTTP layer:

  1. `final` of the stream endpoint matches the POST endpoint's body
     byte-for-byte, on the SAME scenario, across all four TurnResult-producing
     branches (intake, recommend_hotels, agent chat, finalize).
  2. Concatenated `delta` text equals `final.reply` on the one branch that
     streams tokens (agent chat).

Each branch builds two independent, identically-seeded sessions (one for the
POST call, one for the stream call) via a shared factory function, so the two
calls never share mutable session state.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

import src.agents.session as session_module
import src.api.routes as routes_module
from src.agents.session import SessionRegistry, TripSession
from src.services.hotel_selection import HotelPreferenceState
from src.services.trip_intake import TripIntakeState

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Đà Nẵng", "Nha Trang", "Hội An"),
    )


@pytest.fixture(autouse=True)
def _no_live_supervisor(monkeypatch):
    """Force the deterministic decide_route_by_rules fallback — no live LLM
    supervisor call (same seam as test_chat_turn_characterization.py)."""
    monkeypatch.setattr(session_module, "decide_route_by_llm", lambda session, user_input: None)


def _use_factory(monkeypatch, build_session) -> SessionRegistry:
    """Every POST /chat/session call gets a fresh TripSession from
    `build_session(session_id)` — calling it twice with the two different
    server-generated ids yields two independent but identically-seeded
    sessions for a POST/stream twin comparison."""
    monkeypatch.setattr(session_module, "create_chat_session", lambda session_id, **kw: build_session(session_id))
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


async def _run_both(client, message: str) -> tuple[dict, list[tuple[str, dict]]]:
    """POST first, then stream, each against its own fresh session (same
    build_session factory). Returns (post_body, stream_frames)."""
    sid_post = (await client.post("/api/v1/chat/session")).json()["session_id"]
    resp_post = await client.post(
        "/api/v1/planner_chat", json={"session_id": sid_post, "message": message}
    )
    assert resp_post.status_code == 200, resp_post.text

    sid_stream = (await client.post("/api/v1/chat/session")).json()["session_id"]
    resp_stream = await client.post(
        "/api/v1/planner_chat/stream", json={"session_id": sid_stream, "message": message}
    )
    assert resp_stream.status_code == 200, resp_stream.text

    return resp_post.json(), _parse_sse(resp_stream.text)


def _assert_final_matches_post(post_data: dict, frames: list[tuple[str, dict]]) -> dict:
    finals = [d for e, d in frames if e == "final"]
    assert len(finals) == 1, f"expected exactly one final frame, got {len(finals)}"
    final_data = dict(finals[0])
    final_data.pop("session_id")
    post_copy = dict(post_data)
    post_copy.pop("session_id")
    assert final_data == post_copy
    return final_data


# ---------------------------------------------------------------------------
# Branch 1 — intake (deterministic i18n question, no LLM prose)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_intake_branch(client, monkeypatch):
    def build(session_id: str) -> TripSession:
        session = TripSession(
            session_id=session_id, agent=MagicMock(), config={"configurable": {"thread_id": session_id}}
        )
        session.tools = MagicMock()
        return session

    _use_factory(monkeypatch, build)

    post_data, frames = await _run_both(client, "Đà Nẵng")
    _assert_final_matches_post(post_data, frames)
    assert [e for e, _ in frames if e == "delta"] == []  # no LLM on this branch


# ---------------------------------------------------------------------------
# Branch 2 — recommend_hotels (deterministic tool call, tool-formatted text)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_recommend_hotels_branch(client, monkeypatch):
    def build(session_id: str) -> TripSession:
        session = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
            intake_state=TripIntakeState(
                destination="Đà Nẵng", duration="3 ngày", start_date="2026-10-12",
                stay_end_date="2026-10-15", people="2",
            ),
            hotel_pref_state=HotelPreferenceState(stage="done"),
        )
        tools = MagicMock()
        tools.recommend_hotels.invoke.return_value = "1. Fusion Resort\n2. Muong Thanh"
        session.tools = tools
        return session

    _use_factory(monkeypatch, build)

    post_data, frames = await _run_both(client, "bao nhiêu cũng được")
    _assert_final_matches_post(post_data, frames)
    assert [e for e, _ in frames if e == "delta"] == []


# ---------------------------------------------------------------------------
# Branch 3 — agent chat (agent_stream): the one branch with real token deltas
# ---------------------------------------------------------------------------


class _Msg:
    def __init__(self, type_, content="", name=None, tool_calls=None, tool_call_chunks=None):
        self.type = type_
        self.content = content
        self.name = name
        self.tool_calls = tool_calls or []
        self.tool_call_chunks = tool_call_chunks or []
        self.id = None


REPLY_TEXT = "Đà Nẵng có nhiều bãi biển đẹp và ẩm thực đường phố phong phú."


def _agent_stream_events(*_args, stream_mode=None, **_kwargs):
    """Mimics real langgraph's two response shapes for the SAME underlying
    turn (verified empirically — see _run_chat_agent's docstring):
    stream_mode="values" (stream=False, the plain POST path) yields bare
    "values" event dicts and NEVER any "messages" item — the real agent's
    underlying model call isn't even in streaming mode in that case, so no
    token-level events exist to yield. stream_mode as a list (stream=True)
    yields (mode, payload) tuples for both modes, tokens included."""
    values_event = {"messages": [_Msg("ai", content=REPLY_TEXT)]}
    if stream_mode == "values":
        return iter([values_event])

    words = REPLY_TEXT.split(" ")
    chunks = [w + " " for w in words[:-1]] + [words[-1]]
    events = [("messages", (_Msg("ai", content=c), {"langgraph_node": "agent"})) for c in chunks]
    events.append(("values", values_event))
    return iter(events)


@pytest.mark.asyncio
async def test_parity_agent_chat_branch(client, monkeypatch):
    def build(session_id: str) -> TripSession:
        session = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
            initial_plan_complete=True,
        )
        session.agent.stream.side_effect = _agent_stream_events
        session.agent.get_state.return_value = MagicMock(values={"messages": []})
        session.tools = MagicMock()
        return session

    _use_factory(monkeypatch, build)

    post_data, frames = await _run_both(client, "gợi ý thêm cho tôi")
    final_data = _assert_final_matches_post(post_data, frames)

    deltas = [d["text"] for e, d in frames if e == "delta"]
    assert deltas, "agent chat branch must stream at least one delta"
    assert "".join(deltas) == final_data["reply"] == REPLY_TEXT
    assert "generating" in [d["key"] for e, d in frames if e == "phase"]


# ---------------------------------------------------------------------------
# Branch 4 — finalize (deterministic tool-formatted text via trip_formatter)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_finalize_branch(client, monkeypatch):
    monkeypatch.setattr("src.agents.routing_decision.is_finalization_request", lambda text: True)

    def build(session_id: str) -> TripSession:
        session = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
            trip_data={"itineraries": [{"duration_days": 3}]},
        )
        tools = MagicMock()
        tools.finalize_trip_plan.invoke.return_value = "Đã chốt lịch trình của bạn."
        session.tools = tools
        return session

    _use_factory(monkeypatch, build)

    post_data, frames = await _run_both(client, "chốt lịch trình")
    _assert_final_matches_post(post_data, frames)
    assert [e for e, _ in frames if e == "delta"] == []
    assert "persisting" not in [d["key"] for e, d in frames if e == "phase"]  # mocked tool, no real write
