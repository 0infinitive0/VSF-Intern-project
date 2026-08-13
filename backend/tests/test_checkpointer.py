"""Checkpointer wiring: injection from SessionRegistry down to build_trip_agent,
event-triggered pruning, and the startup orphan sweep's SQL aggregate.

Live-Postgres tests (table creation + restart durability against a real
database) are opt-in only, gated behind RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS=1
-- a plain `pytest tests/` run must never require or mutate a real database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

import src.agents.graph as graph_module
import src.agents.session as session_module
import src.main as main_module
from src.agents.session import SessionRegistry, create_chat_session
from src.config import Settings
from src.main import _require_checkpointer_database_url


class _FakeCheckpointer:
    """Records delete_thread calls without touching a real database."""

    def __init__(self) -> None:
        self.deleted_thread_ids: list[str] = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted_thread_ids.append(thread_id)


class _RaisingCheckpointer(_FakeCheckpointer):
    def delete_thread(self, thread_id: str) -> None:
        raise RuntimeError("boom")


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.executed_with: tuple | None = None

    def execute(self, query, params) -> None:
        self.executed_with = (query, params)

    def fetchall(self) -> list[dict]:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class _FakePool:
    """Stands in for psycopg_pool.ConnectionPool: `.connection()` yields a
    connection whose `.cursor()` returns canned rows for the sweep query."""

    def __init__(self, rows: list[dict]) -> None:
        self._cursor = _FakeCursor(rows)

    def connection(self):
        return _FakeConnection(self._cursor)


# ---------------------------------------------------------------------------
# Postgres DSN requirement
# ---------------------------------------------------------------------------


def test_require_checkpointer_database_url_passes_through_when_set():
    settings = Settings(checkpointer_database_url="postgresql://user:pw@pooler.example.com:5432/postgres")

    assert _require_checkpointer_database_url(settings) == "postgresql://user:pw@pooler.example.com:5432/postgres"


def test_require_checkpointer_database_url_raises_when_unset():
    settings = Settings(checkpointer_database_url="")

    with pytest.raises(RuntimeError, match="CHECKPOINTER_DATABASE_URL"):
        _require_checkpointer_database_url(settings)


# ---------------------------------------------------------------------------
# build_trip_agent: injected checkpointer vs. default fallback
# ---------------------------------------------------------------------------


def test_build_trip_agent_passes_injected_checkpointer_to_create_react_agent(monkeypatch):
    captured = {}

    def _fake_create_react_agent(llm, tools, *, state_schema, checkpointer, prompt):
        captured["checkpointer"] = checkpointer
        return object()

    monkeypatch.setattr(graph_module, "get_llm", lambda **_kwargs: object())
    monkeypatch.setattr(graph_module, "create_react_agent", _fake_create_react_agent)

    session = _stub_session()
    fake_checkpointer = _FakeCheckpointer()

    graph_module.build_trip_agent(session, checkpointer=fake_checkpointer)

    assert captured["checkpointer"] is fake_checkpointer


def test_build_trip_agent_falls_back_to_fresh_memory_saver_when_no_checkpointer_injected(monkeypatch):
    captured = {}

    def _fake_create_react_agent(llm, tools, *, state_schema, checkpointer, prompt):
        captured["checkpointer"] = checkpointer
        return object()

    monkeypatch.setattr(graph_module, "get_llm", lambda **_kwargs: object())
    monkeypatch.setattr(graph_module, "create_react_agent", _fake_create_react_agent)

    graph_module.build_trip_agent(_stub_session())

    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(captured["checkpointer"], MemorySaver)


def _stub_session():
    from src.agents.session import TripSession

    return TripSession(
        session_id="stub-session",
        agent=None,
        config={"configurable": {"thread_id": "stub-session"}},
        persist_hook=None,
    )


# ---------------------------------------------------------------------------
# create_chat_session forwards checkpointer through
# ---------------------------------------------------------------------------


def test_create_chat_session_forwards_checkpointer_to_build_trip_agent(monkeypatch):
    captured = {}

    def _fake_build_trip_agent(session, **kwargs):
        captured["checkpointer"] = kwargs.get("checkpointer")
        return object(), object()

    monkeypatch.setattr(session_module, "build_trip_agent", _fake_build_trip_agent)
    fake_checkpointer = _FakeCheckpointer()

    create_chat_session("session-id", checkpointer=fake_checkpointer)

    assert captured["checkpointer"] is fake_checkpointer


# ---------------------------------------------------------------------------
# SessionRegistry: injection + threading through create/get/resolve
# ---------------------------------------------------------------------------


def test_session_registry_threads_checkpointer_through_create(monkeypatch):
    captured = []
    monkeypatch.setattr(
        session_module,
        "build_trip_agent",
        lambda session, **kwargs: captured.append(kwargs.get("checkpointer")) or (object(), object()),
    )
    fake_checkpointer = _FakeCheckpointer()

    registry = SessionRegistry(checkpointer=fake_checkpointer)
    registry.create()

    assert captured == [fake_checkpointer]


def test_session_registry_threads_checkpointer_through_resolve(monkeypatch):
    captured = []
    monkeypatch.setattr(
        session_module,
        "build_trip_agent",
        lambda session, **kwargs: captured.append(kwargs.get("checkpointer")) or (object(), object()),
    )
    fake_checkpointer = _FakeCheckpointer()

    registry = SessionRegistry(checkpointer=fake_checkpointer)
    registry.resolve("new-session-id")

    assert captured == [fake_checkpointer]


def test_session_registry_set_checkpointer_applies_to_later_sessions(monkeypatch):
    captured = []
    monkeypatch.setattr(
        session_module,
        "build_trip_agent",
        lambda session, **kwargs: captured.append(kwargs.get("checkpointer")) or (object(), object()),
    )
    fake_checkpointer = _FakeCheckpointer()

    registry = SessionRegistry()  # constructed with no checkpointer, like the module-level `registry`
    registry.set_checkpointer(fake_checkpointer)
    registry.create()

    assert captured == [fake_checkpointer]


def test_session_registry_defaults_to_no_checkpointer(monkeypatch):
    captured = []
    monkeypatch.setattr(
        session_module,
        "build_trip_agent",
        lambda session, **kwargs: captured.append(kwargs.get("checkpointer")) or (object(), object()),
    )

    registry = SessionRegistry()
    registry.create()

    assert captured == [None]


# ---------------------------------------------------------------------------
# Pruning: evict_expired / drop delete checkpoints for pruned session_ids
# ---------------------------------------------------------------------------


def test_evict_expired_prunes_checkpoints_for_expired_sessions(monkeypatch):
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    fake_checkpointer = _FakeCheckpointer()
    registry = SessionRegistry(ttl_seconds=0, checkpointer=fake_checkpointer)
    session = registry.create()
    session.last_seen_at -= 10  # force past the zero-second TTL

    evicted = registry.evict_expired()

    assert evicted == 1
    assert fake_checkpointer.deleted_thread_ids == [session.session_id]


def test_evict_expired_is_a_noop_pruning_without_a_checkpointer(monkeypatch):
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    registry = SessionRegistry(ttl_seconds=0)
    session = registry.create()
    session.last_seen_at -= 10

    evicted = registry.evict_expired()  # must not raise with no checkpointer set

    assert evicted == 1


def test_evict_expired_survives_checkpointer_delete_failure(monkeypatch):
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    raising_checkpointer = _RaisingCheckpointer()
    registry = SessionRegistry(ttl_seconds=0, checkpointer=raising_checkpointer)
    session = registry.create()
    session.last_seen_at -= 10

    evicted = registry.evict_expired()  # delete_thread raising must not break eviction

    assert evicted == 1


def test_drop_prunes_checkpoint_for_the_dropped_session(monkeypatch):
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    fake_checkpointer = _FakeCheckpointer()
    registry = SessionRegistry(checkpointer=fake_checkpointer)
    session = registry.create()

    registry.drop(session.session_id)

    assert fake_checkpointer.deleted_thread_ids == [session.session_id]


def test_evict_expired_does_not_prune_a_session_recreated_after_unlock(monkeypatch):
    """A concurrent get()/resolve() can recreate the same session_id between
    evict_expired releasing the registry lock and pruning running -- pruning
    must re-check membership and skip ids that came back, or it destroys a
    live session's checkpoints out from under it."""
    monkeypatch.setattr(session_module, "build_trip_agent", lambda session, **_kwargs: (object(), object()))
    fake_checkpointer = _FakeCheckpointer()
    registry = SessionRegistry(ttl_seconds=0, checkpointer=fake_checkpointer)
    session = registry.create()
    session.last_seen_at -= 10
    session_id = session.session_id

    original_prune = registry._prune_checkpoints

    def _recreate_then_prune(session_ids):
        # Simulate another thread's resolve() recreating the session between
        # the lock releasing and pruning running.
        registry._sessions[session_id] = session
        original_prune(session_ids)

    monkeypatch.setattr(registry, "_prune_checkpoints", _recreate_then_prune)

    registry.evict_expired()

    assert fake_checkpointer.deleted_thread_ids == []
    assert session_id in registry._sessions


# ---------------------------------------------------------------------------
# Startup orphan sweep: SQL aggregate, not PostgresSaver.list()
# ---------------------------------------------------------------------------


def test_find_orphaned_thread_ids_queries_checkpoints_grouped_by_thread(monkeypatch):
    pool = _FakePool(rows=[{"thread_id": "old-1"}, {"thread_id": "old-2"}])
    cutoff = datetime.now(UTC) - timedelta(hours=2)

    thread_ids = main_module._find_orphaned_thread_ids(pool, cutoff, limit=1000)

    assert thread_ids == ["old-1", "old-2"]
    query, params = pool._cursor.executed_with
    assert "GROUP BY thread_id" in query
    assert "checkpoints" in query
    assert params == (cutoff, 1000)


def test_sweep_orphaned_checkpoints_deletes_each_found_thread(monkeypatch):
    pool = _FakePool(rows=[{"thread_id": "old-1"}, {"thread_id": "old-2"}])
    checkpointer = _FakeCheckpointer()

    main_module._sweep_orphaned_checkpoints(pool, checkpointer, max_age_seconds=3600)

    assert checkpointer.deleted_thread_ids == ["old-1", "old-2"]


def test_sweep_orphaned_checkpoints_survives_delete_failure(monkeypatch):
    pool = _FakePool(rows=[{"thread_id": "old-1"}])
    checkpointer = _RaisingCheckpointer()

    main_module._sweep_orphaned_checkpoints(pool, checkpointer, max_age_seconds=3600)  # must not raise


def test_sweep_orphaned_checkpoints_is_a_noop_when_nothing_is_stale():
    pool = _FakePool(rows=[])
    checkpointer = _FakeCheckpointer()

    main_module._sweep_orphaned_checkpoints(pool, checkpointer, max_age_seconds=3600)

    assert checkpointer.deleted_thread_ids == []


# ---------------------------------------------------------------------------
# lifespan(): the only place the two branches above actually get wired up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_memory_backend_injects_nothing_into_registry(monkeypatch):
    fresh_registry = SessionRegistry()
    monkeypatch.setattr(main_module, "registry", fresh_registry)
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(checkpointer_backend="memory"))

    async with main_module.lifespan(main_module.app):
        # No injection in the memory branch: build_trip_agent's own
        # checkpointer=None fallback is what preserves pre-existing behavior.
        assert fresh_registry._checkpointer is None


@pytest.mark.asyncio
async def test_lifespan_postgres_backend_without_dsn_fails_fast(monkeypatch):
    fresh_registry = SessionRegistry()
    monkeypatch.setattr(main_module, "registry", fresh_registry)
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: Settings(checkpointer_backend="postgres", checkpointer_database_url=""),
    )

    with pytest.raises(RuntimeError, match="CHECKPOINTER_DATABASE_URL"):
        async with main_module.lifespan(main_module.app):
            pass  # pragma: no cover -- must raise before yielding


# ---------------------------------------------------------------------------
# Live Postgres (opt-in only -- see module docstring)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS") != "1",
    reason="Opt-in only: set RUN_LIVE_POSTGRES_CHECKPOINTER_TESTS=1 and CHECKPOINTER_DATABASE_URL "
    "to run against a real Postgres instance (a local `postgres:16` container works).",
)
def test_postgres_checkpointer_survives_a_simulated_restart():
    from langgraph.checkpoint.postgres import PostgresSaver

    from src.config import get_settings

    conn_string = _require_checkpointer_database_url(get_settings())
    thread_id = "test-checkpointer-restart-durability"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

    try:
        with PostgresSaver.from_conn_string(conn_string) as checkpointer:
            checkpointer.setup()
            checkpoint = {
                "v": 1,
                "ts": "2026-08-12T00:00:00+00:00",
                "id": "test-checkpoint-1",
                "channel_values": {"messages": []},
                "channel_versions": {},
                "versions_seen": {},
                "updated_channels": [],
            }
            checkpointer.put(config, checkpoint, {"source": "update", "step": 1, "parents": {}}, {})

        # Simulate a process restart: a fresh PostgresSaver instance, same DB.
        with PostgresSaver.from_conn_string(conn_string) as restarted_checkpointer:
            tuple_ = restarted_checkpointer.get_tuple(config)
            assert tuple_ is not None
            assert tuple_.checkpoint["id"] == "test-checkpoint-1"
    finally:
        with PostgresSaver.from_conn_string(conn_string) as cleanup_checkpointer:
            cleanup_checkpointer.delete_thread(thread_id)
