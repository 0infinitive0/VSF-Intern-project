from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from postgrest.exceptions import APIError

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


def test_serialize_creates_compact_v2_checkpoint_without_messages_or_full_trip_data():
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

    assert context["schema_version"] == 2
    assert "remaining_steps" not in context
    assert "messages" not in context
    assert "trip_data" not in context
    assert restored["intake"]["destination"] == "Da Nang"
    assert restored["hotel_prefs"]["max_price"] == 2_000_000
    assert restored["trip_data"] is None
    assert context["current_trip"] == {"itinerary_id": None, "hotel_id": None, "status": None}


def test_upsert_uses_existing_chat_message_columns_without_schema_metadata(monkeypatch):
    session = _session()
    session.state["messages"] = [
        HumanMessage(content="Plan a trip", additional_kwargs={"stage": "intake"}),
        AIMessage(content="Where would you like to go?", additional_kwargs={"stage": "intake"}),
    ]
    calls = []

    class FakeRpc:
        def execute(self):
            return SimpleNamespace(data={"ok": True})

    class FakeSupabase:
        def rpc(self, name, params):
            calls.append((name, params))
            return FakeRpc()

    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: FakeSupabase())

    session_store.upsert(session)

    name, params = calls[0]
    assert name == "persist_session_checkpoint"
    assert params["p_context_data"]["schema_version"] == 2
    assert [message["sender_type"] for message in params["p_messages"]] == ["user", "assistant"]
    assert all("turn_id" not in message and "message_index" not in message for message in params["p_messages"])


def test_upsert_falls_back_to_existing_tables_when_checkpoint_rpc_is_not_deployed(monkeypatch):
    session = _session()
    session.state["messages"] = [HumanMessage(content="Plan a trip")]
    calls = []

    class FakeRpc:
        def execute(self):
            raise APIError(
                {
                    "message": "Could not find the function public.persist_session_checkpoint",
                    "code": "PGRST202",
                    "hint": "",
                    "details": "",
                }
            )

    class FakeQuery:
        def __init__(self, table_name):
            self.table_name = table_name

        def upsert(self, data, **kwargs):
            calls.append((self.table_name, "upsert", data, kwargs))
            return self

        def delete(self):
            calls.append((self.table_name, "delete"))
            return self

        def eq(self, key, value):
            calls.append((self.table_name, "eq", key, value))
            return self

        def insert(self, data):
            calls.append((self.table_name, "insert", data))
            return self

        def execute(self):
            return SimpleNamespace(data={"ok": True})

    class FakeSupabase:
        def rpc(self, _name, _params):
            return FakeRpc()

        def table(self, table_name):
            return FakeQuery(table_name)

    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: FakeSupabase())

    session_store.upsert(session)

    assert any(
        call[:2] == ("sessions", "upsert")
        and call[3] == {"on_conflict": "session_id"}
        for call in calls
    )
    assert any(call[:2] == ("chat_messages", "delete") for call in calls)
    insert = next(call for call in calls if call[:2] == ("chat_messages", "insert"))
    assert insert[2][0]["session_id"] == session.session_id


def test_session_checkpoint_migration_replaces_transcript_without_new_chat_columns():
    migration = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrations"
        / "20260811_add_session_checkpoint_persistence.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.persist_session_checkpoint" in migration
    assert "DELETE FROM public.chat_messages" in migration
    assert "INSERT INTO public.chat_messages" in migration
    assert "ON CONFLICT (session_id) DO UPDATE" in migration
    assert "turn_id" not in migration
    assert "message_index" not in migration


def test_registry_rehydrates_only_when_loader_is_enabled(monkeypatch):
    row = {
        "session_id": "persisted-session",
        "context_data": {"intake": {"destination": "Nha Trang"}, "messages": []},
    }
    created = []

    def fake_create(session_id, *, persist_hook=None, **_kwargs):
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


def test_legacy_context_restores_then_rewrites_as_v2_checkpoint():
    session = _session()
    legacy = {
        "intake": {"destination": "Nha Trang"},
        "trip_data": {"itineraries": [{"id": "itinerary-1", "hotel_id": "hotel-1", "status": "Draft"}]},
        "messages": [{"type": "human", "data": {"content": "hello", "additional_kwargs": {}}}],
    }

    session.state = session_store.deserialize(session.session_id, legacy)
    checkpoint = session_store.serialize(session)

    assert session.state["intake"]["destination"] == "Nha Trang"
    assert checkpoint["schema_version"] == 2
    assert checkpoint["current_trip"]["itinerary_id"] == "itinerary-1"
    assert "messages" not in checkpoint


def test_list_sessions_fetches_one_extra_row_for_stable_pagination(monkeypatch):
    rows = [
        {"session_id": f"session-{index:02d}", "context_data": {}, "created_at": "", "updated_at": ""}
        for index in range(11)
    ]

    class FakeQuery:
        def order(self, *_args, **_kwargs):
            return self

        def range(self, start, end):
            assert (start, end) == (10, 20)
            return self

        def execute(self):
            return SimpleNamespace(data=rows)

    class FakeSupabase:
        def table(self, name):
            assert name == "sessions"
            return self

        def select(self, *_args):
            return FakeQuery()

    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: FakeSupabase())

    page = session_store.list_sessions(page=2, page_size=10)

    assert len(page.rows) == 10
    assert page.rows[0]["session_id"] == "session-00"
    assert page.has_more is True


def test_persistence_failure_is_swallowed_and_turn_still_returns(monkeypatch):
    session = _session(persist_hook=session_module.supabase_persist_hook)
    monkeypatch.setattr(session_module, "_process_chat_turn", lambda *_args, **_kwargs: TurnResult("reply", "chat"))
    monkeypatch.setattr(session_store, "upsert", lambda _session: (_ for _ in ()).throw(RuntimeError("db down")))

    result = session_module.process_chat_turn(session, "hello")

    assert result.text == "reply"
    assert [message.content for message in session.state["messages"]] == ["hello", "reply"]


def test_persist_turn_stores_sanitized_assistant_error(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        session_module,
        "_process_chat_turn",
        lambda *_args, **_kwargs: TurnResult("SYSTEM ERROR: secret upstream traceback", "chat"),
    )

    result = session_module.process_chat_turn(session, "hello")

    assert "secret upstream traceback" not in result.text
    assert "secret upstream traceback" not in session.state["messages"][-1].content


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
        lambda page=1, page_size=10: session_store.SessionPage(
            rows=[{"session_id": session.session_id, "context_data": session_store.serialize(session), "created_at": "2026-08-07T00:00:00Z", "updated_at": "2026-08-07T00:00:01Z"}],
            page=page,
            page_size=page_size,
            has_more=True,
        ),
    )

    listed = await client.get("/api/v1/chat/sessions")
    restored = await client.get(f"/api/v1/chat/{session.session_id}/restore")

    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["status"] == "draft"
    assert listed.json()["page_size"] == 10
    assert listed.json()["has_more"] is True
    assert restored.status_code == 200
    assert restored.json()["messages"][0]["text"] == "hello"
