import uuid

import pytest

import src.api.routes as routes_module
import src.services.chat_session as chat_session_module
from src.services.chat_session import ChatSession


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    # planner_chat's underlying process_chat_turn reads/writes
    # current_trip_plan.json / pending_hotel_selection.json relative to cwd.
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _fake_planner_agent(monkeypatch):
    # Real create_planner_agent() needs a live LLM; the state-machine logic under
    # test (intake -> hotel prefs) never touches session.agent, so a stub suffices.
    def _fake_create_chat_session(thread_id):
        return ChatSession(agent=object(), config={"configurable": {"thread_id": thread_id}})

    monkeypatch.setattr(routes_module, "create_chat_session", _fake_create_chat_session)
    monkeypatch.setattr(chat_session_module, "_get_destination_names", lambda: ("Đà Nẵng",))


@pytest.mark.asyncio
async def test_planner_chat_preserves_state_across_turns_with_same_session_id(client):
    session_id = str(uuid.uuid4())

    first = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": session_id, "message": "Tôi muốn đi Đà Nẵng"},
    )
    assert first.status_code == 200
    assert "bao lâu" in first.json()["reply"].lower()

    second = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": session_id, "message": "3 ngày"},
    )
    assert second.status_code == 200
    assert "bao nhiêu người" in second.json()["reply"].lower()


@pytest.mark.asyncio
async def test_planner_chat_empty_message_rejected(client):
    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": str(uuid.uuid4()), "message": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
