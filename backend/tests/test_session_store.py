from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import src.agents.session as session_module
import src.api.routes as routes
import src.services.session_store as session_store
from src.agents.session import SessionRegistry, TripSession, TurnResult


def _session(session_id="persisted-session", persist_hook=None):
    return TripSession(
        session_id=session_id,
        agent=object(),
        config={"configurable": {"thread_id": session_id}},
        persist_hook=persist_hook,
    )


def test_serialize_round_trip_preserves_business_state_and_excludes_remaining_steps():
    session = _session()
    session.state.update(
        {
            "intake": {"destination": "Da Nang"},
            "hotel_prefs": {"stage": "done", "max_price": 2_000_000},
            "trip_data": {"destination": "Da Nang", "duration_days": 3},
            "pending_hotel_selection": {"options": [{"id": "hotel-1"}]},
            "remaining_steps": 7,
            "messages": [
                HumanMessage(content="Plan a trip", additional_kwargs={"stage": "intake", "at": "2026-08-07T00:00:00Z"}),
                AIMessage(content="Where would you like to go?", additional_kwargs={"stage": "intake", "at": "2026-08-07T00:00:01Z"}),
            ],
        }
    )

    context = session_store.serialize(session)
    restored = session_store.deserialize(session.session_id, context)

    assert "remaining_steps" not in context
    assert restored["intake"]["destination"] == "Da Nang"
    assert restored["hotel_prefs"]["max_price"] == 2_000_000
    assert restored["trip_data"]["duration_days"] == 3
    assert [message.content for message in restored["messages"]] == ["Plan a trip", "Where would you like to go?"]


def test_registry_rehydrates_only_when_loader_is_enabled(monkeypatch):
    row = {
        "session_id": "persisted-session",
        "context_data": {"intake": {"destination": "Nha Trang"}, "messages": []},
    }
    created = []

    def fake_create(session_id, *, persist_hook=None):
        created.append(session_id)
        return _session(session_id, persist_hook)

    monkeypatch.setattr(session_module, "create_chat_session", fake_create)
    disabled = SessionRegistry()
    assert disabled.get("persisted-session") is None

    enabled = SessionRegistry(load_hook=lambda session_id: row if session_id == "persisted-session" else None)
    restored = enabled.get("persisted-session")
    assert restored is not None
    assert restored.intake_state.destination == "Nha Trang"
    assert created == ["persisted-session"]


def test_persistence_failure_is_swallowed_and_turn_still_returns(monkeypatch):
    session = _session(persist_hook=session_module.supabase_persist_hook)
    monkeypatch.setattr(session_module, "_process_chat_turn", lambda *_args, **_kwargs: TurnResult("reply", "chat"))
    monkeypatch.setattr(session_store, "upsert", lambda _session: (_ for _ in ()).throw(RuntimeError("db down")))

    result = session_module.process_chat_turn(session, "hello")

    assert result.text == "reply"
    assert [message.content for message in session.state["messages"]] == ["hello", "reply"]


def test_drop_deletes_persisted_row_and_swallows_delete_failure():
    deleted = []
    registry = SessionRegistry(delete_hook=lambda session_id: deleted.append(session_id))
    registry._sessions["persisted-session"] = _session()
    registry.drop("persisted-session")
    assert deleted == ["persisted-session"]
    assert registry.get("persisted-session") is None


@pytest.mark.asyncio
async def test_list_and_restore_routes_use_persisted_payload_contract(client, monkeypatch):
    session = _session("persisted-session")
    session.state["messages"] = [
        HumanMessage(content="hello", additional_kwargs={"stage": "intake", "at": "2026-08-07T00:00:00Z"})
    ]
    session.state["reply"] = "welcome"
    monkeypatch.setattr(routes, "_persistence_enabled", True)
    monkeypatch.setattr(routes, "registry", SimpleNamespace(get=lambda session_id: session if session_id == session.session_id else None))
    monkeypatch.setattr(
        session_store,
        "list_sessions",
        lambda: [{"session_id": session.session_id, "context_data": session_store.serialize(session), "created_at": "2026-08-07T00:00:00Z", "updated_at": "2026-08-07T00:00:01Z"}],
    )

    listed = await client.get("/api/v1/chat/sessions")
    restored = await client.get(f"/api/v1/chat/{session.session_id}/restore")

    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "draft"
    assert restored.status_code == 200
    assert restored.json()["messages"][0]["text"] == "hello"
