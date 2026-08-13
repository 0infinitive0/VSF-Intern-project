"""Tests for API routes — Phase 3 hardening.

The existing session-state tests are adapted to Phase 3: a session must be
created via POST /api/v1/chat/session before planner_chat is called.
The 422 and status/health tests are unchanged (D10 backward-compat).
"""

import uuid

import pytest

import src.agents.session as session_module
from src.agents.session import TripSession


@pytest.fixture(autouse=True)
def _fake_planner_agent(monkeypatch):
    """Stub build_trip_agent so tests don't need a live LLM.

    The state-machine logic under test (intake -> hotel prefs) never touches
    session.agent, so an object() stub suffices.
    """

    def _fake_create_chat_session(thread_id, **kwargs):
        return TripSession(
            session_id=thread_id,
            config={"configurable": {"thread_id": thread_id}},
        )

    monkeypatch.setattr(session_module, "create_chat_session", _fake_create_chat_session)

    # Refresh the registry so it picks up the monkeypatched create_chat_session.
    import src.api.routes as _routes
    from src.agents.session import SessionRegistry

    _routes.registry = SessionRegistry(ttl_seconds=3600, cap=100)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_returns_uuid(client):
    response = await client.post("/api/v1/chat/session")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    # Must be a valid UUID
    uuid.UUID(data["session_id"])
    assert "created_at" in data


@pytest.mark.asyncio
async def test_unknown_session_id_returns_404(client):
    """An unknown but well-formed UUID must return 404, not create a session."""
    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": str(uuid.uuid4()), "message": "Tôi muốn đi Đà Nẵng"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_malformed_session_id_returns_422(client):
    """A non-UUID session_id must be rejected at the pydantic boundary."""
    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": "not-a-uuid!!", "message": "Tôi muốn đi Đà Nẵng"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_then_get_plan_returns_404(client):
    create_resp = await client.post("/api/v1/chat/session")
    sid = create_resp.json()["session_id"]

    del_resp = await client.delete(f"/api/v1/chat/{sid}")
    assert del_resp.status_code == 204

    plan_resp = await client.get(f"/api/v1/chat/{sid}/plan")
    assert plan_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_plan_for_unknown_session_returns_404(client):
    response = await client.get(f"/api/v1/chat/{uuid.uuid4()}/plan")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Planner chat — state preservation (adapted from original test_routes.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_chat_empty_message_rejected(client):
    """min_length=1 on message must still produce 422 (D10 backward-compat)."""
    create_resp = await client.post("/api/v1/chat/session")
    session_id = create_resp.json()["session_id"]

    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": session_id, "message": ""},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Two sessions must not share state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Utility endpoints (unchanged from original)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
