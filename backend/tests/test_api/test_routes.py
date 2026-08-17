"""Tests for API routes — Phase 3 hardening.

The existing session-state tests are adapted to Phase 3: a session must be
created via POST /api/v1/chat/session before planner_chat is called.
The 422 and status/health tests are unchanged (D10 backward-compat).
"""

import uuid

import pytest

import src.agents.session as session_module
from src.agents.session import TripSession
from src.config import get_settings


@pytest.fixture(autouse=True)
def _auth_not_required_by_default(monkeypatch):
    """Pin AUTH_REQUIRED=false for this module's baseline, explicitly rather
    than relying on config.py's default: Settings reads backend/.env
    directly (env_file=".env"), so on a dev machine that has since flipped
    AUTH_REQUIRED=true there for real, an un-pinned test would silently
    inherit that and 401 on every request below that sends no token —
    same class of bug already documented in test_jwt_verifier.py's
    test_no_supabase_url_configured_raises. Most tests here exercise
    business logic (session lifecycle, hotel flows, planner turns) that is
    orthogonal to the auth rollout flag; the handful that specifically test
    ownership/AUTH_REQUIRED behavior use the auth_override fixture below or
    set the env var themselves.
    """
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
            owner_user_id=kwargs.get("owner_user_id"),
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


# ---------------------------------------------------------------------------
# Ownership / cross-user isolation (plan 260814-supabase-auth-and-per-user-history)
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_override():
    """Overrides the get_current_user dependency for the app under test.

    Call with a user id to simulate an authenticated caller, or with None to
    simulate no/an invalid token (AUTH_REQUIRED defaults to False, so that is
    "anonymous", not "rejected" — see src/auth/dependencies.py). Always
    cleared after the test, pass or fail.
    """
    from src.auth import AuthenticatedUser, get_current_user
    from src.main import app

    def _set(user_id: str | None):
        if user_id is None:
            app.dependency_overrides.pop(get_current_user, None)
            return
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id=user_id, email=f"{user_id}@example.com", is_anonymous=False
        )

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_create_session_stamps_the_caller_as_owner(client, auth_override):
    import src.api.routes as _routes

    auth_override("user-a")
    response = await client.post("/api/v1/chat/session")
    session_id = response.json()["session_id"]

    session = _routes.registry.get(session_id)
    assert session.owner_user_id == "user-a"


@pytest.mark.asyncio
async def test_a_session_created_with_no_caller_identity_has_no_owner(client, auth_override):
    """AUTH_REQUIRED=False (the default) must not regress today's behavior:
    a caller sending no token still gets a working, unowned session."""
    import src.api.routes as _routes

    auth_override(None)
    response = await client.post("/api/v1/chat/session")
    session_id = response.json()["session_id"]

    session = _routes.registry.get(session_id)
    assert session.owner_user_id is None


@pytest.mark.asyncio
async def test_the_owning_user_can_reach_their_own_session(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_different_authenticated_user_gets_404_not_someone_elses_session(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_cannot_reach_someone_elses_session_either(client, auth_override):
    """The security fix does not depend on AUTH_REQUIRED being on: a caller
    with no identity at all must be just as unable to reach an owned session
    as a caller authenticated as someone else."""
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override(None)
    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_planner_chat_also_enforces_ownership(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.post(
        "/api/v1/planner_chat", json={"session_id": session_id, "message": "hello"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_is_a_silent_noop_for_a_different_owner(client, auth_override):
    """Preserves the existing '204 either way' contract (never leaks
    existence via status code) while still not actually deleting a session
    that belongs to someone else."""
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.delete(f"/api/v1/chat/{session_id}")
    assert response.status_code == 204
    assert _routes.registry.get(session_id) is not None

    auth_override("user-a")
    response = await client.delete(f"/api/v1/chat/{session_id}")
    assert response.status_code == 204
    assert _routes.registry.get(session_id) is None
