"""The graph plane's own write path to `sessions` + `chat_messages`.

The legacy cascade (`process_chat_turn` -> `persist_hook` -> `session_store
.upsert`) was removed with the graph cutover, and nothing took over its
side effects: every chat turn ran, answered, and left no trace in the
database. `list_sessions` inner-joins `chat_messages`, so a session with no
message row never reaches the history rail at all — the failure was total
and completely silent.

`persist_graph_session` reads `TravelGraphState` directly instead of
resurrecting the `TripSession.state` mirror, which is why it writes a v3
`context_data` shape rather than reusing v2's (see plan QĐ-1). These tests
pin the three things that can go wrong quietly: the wrong shape on disk,
the wrong messages in the transcript, and a database outage taking a chat
turn down with it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.services import session_store


class _FakeQuery:
    """Chainable no-op stand-in for postgrest's builder."""

    def __init__(self, recorder: dict[str, Any], table: str) -> None:
        self._recorder = recorder
        self._table = table
        self._payload: Any = None

    def upsert(self, payload, **_kwargs):
        self._payload = payload
        self._recorder.setdefault("upserts", []).append((self._table, payload))
        return self

    def insert(self, payload, **_kwargs):
        self._recorder.setdefault("inserts", []).append((self._table, payload))
        return self

    def update(self, payload, **_kwargs):
        self._recorder.setdefault("updates", []).append((self._table, payload))
        return self

    def delete(self, **_kwargs):
        self._recorder.setdefault("deletes", []).append(self._table)
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _FakeSupabase:
    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}

    def rpc(self, name: str, params: dict[str, Any]):
        self.calls.setdefault("rpc", []).append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))

    def table(self, name: str):
        return _FakeQuery(self.calls, name)

    # -- assertions helpers --------------------------------------------
    @property
    def context(self) -> dict[str, Any]:
        return self.calls["rpc"][0][1]["p_context_data"]

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self.calls["rpc"][0][1]["p_messages"]


@pytest.fixture
def fake_supabase(monkeypatch: pytest.MonkeyPatch) -> _FakeSupabase:
    client = _FakeSupabase()
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: client)
    return client


def _session(session_id: str = "sess-1", owner: str | None = "user-1"):
    """Only the two attributes persist_graph_session is allowed to read."""
    return SimpleNamespace(session_id=session_id, owner_user_id=owner)


def _travel_state() -> dict[str, Any]:
    return {
        "destination": {"presence": "set", "value": "Đà Nẵng"},
        "people": {"presence": "set", "value": 2},
        "dates.start": {"presence": "set", "value": "2026-08-10"},
    }


def _graph_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "session_id": "sess-1",
        "language": "vi",
        "travel_state": _travel_state(),
        "trip_data": {
            "destination": "Đà Nẵng",
            "duration_days": 4,
            "hotel": {"id": "h-1", "name": "Mường Thanh", "image_url": "https://img/1.jpg"},
            "itineraries": [{"id": "it-1", "hotel_id": "h-1", "status": "Draft", "duration_days": 4}],
        },
        "messages": [
            HumanMessage(content="đi đà nẵng 4 ngày"),
            AIMessage(content="Bạn đi mấy người?", additional_kwargs={"emitted_by": "respond"}),
        ],
    }
    state.update(overrides)
    return state


class TestContextShape:
    def test_writes_schema_version_3(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert fake_supabase.context["schema_version"] == 3

    def test_carries_the_travel_state_verbatim(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert fake_supabase.context["travel_state"] == _travel_state()

    def test_drops_every_word_of_the_dead_plane_vocabulary(self, fake_supabase: _FakeSupabase):
        """v3 exists precisely so `context_data` stops describing a plane that
        no longer runs. A key from that vocabulary reappearing means the writer
        drifted back toward the v2 shape."""
        session_store.persist_graph_session(_session(), _graph_state())
        context = fake_supabase.context
        for dead_key in ("workflow", "current_trip", "pending_hotel_selection", "intake"):
            assert dead_key not in context

    def test_keeps_the_ui_summary_the_history_rail_reads(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        summary = fake_supabase.context["ui_summary"]
        assert summary["destination"] == "Đà Nẵng"
        assert summary["duration_days"] == 4
        assert summary["status"] == "draft"
        assert summary["hotel_name"] == "Mường Thanh"
        assert summary["thumbnail_url"] == "https://img/1.jpg"

    def test_reads_the_destination_out_of_travel_state_when_no_trip_exists(
        self, fake_supabase: _FakeSupabase
    ):
        """The history rail must name the trip from the very first turn, long
        before `trip_data` exists — the destination slot is the only source
        that early."""
        session_store.persist_graph_session(_session(), _graph_state(trip_data={}))
        assert fake_supabase.context["ui_summary"]["destination"] == "Đà Nẵng"

    def test_points_at_the_itinerary_instead_of_copying_it(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert fake_supabase.context["trip"] == {
            "itinerary_id": "it-1",
            "hotel_id": "h-1",
            "status": "Draft",
        }


class TestTranscript:
    def test_records_the_user_turn_and_the_reply(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert [(m["sender_type"], m["message_content"]) for m in fake_supabase.messages] == [
            ("user", "đi đà nẵng 4 ngày"),
            ("assistant", "Bạn đi mấy người?"),
        ]

    def test_excludes_the_react_agent_internals_qa_node_leaves_behind(
        self, fake_supabase: _FakeSupabase
    ):
        """`qa_node`'s ReAct subgraph writes its tool calls and tool results into
        the same `messages` channel. Persisting those would show the user the
        agent's scratchpad as if it were conversation."""
        state = _graph_state(
            messages=[
                HumanMessage(content="khách sạn này có hồ bơi không?"),
                AIMessage(
                    content="",
                    additional_kwargs={"tool_calls": [{"id": "1", "name": "search_hotels"}]},
                ),
                ToolMessage(content='{"rows": [...]}', tool_call_id="1"),
                AIMessage(content="Có, khách sạn có hồ bơi."),  # ReAct's own final answer
                AIMessage(content="Có hồ bơi nhé!", additional_kwargs={"emitted_by": "respond"}),
            ]
        )

        session_store.persist_graph_session(_session(), state)

        assert [(m["sender_type"], m["message_content"]) for m in fake_supabase.messages] == [
            ("user", "khách sạn này có hồ bơi không?"),
            ("assistant", "Có hồ bơi nhé!"),
        ]

    def test_preserves_the_time_each_message_was_actually_sent(self, fake_supabase: _FakeSupabase):
        """Every write re-sends the whole transcript, so a message must carry
        its own timestamp — stamping "now" on all of them collapses the
        conversation to a single instant and destroys the ordering `load()`
        sorts by."""
        state = _graph_state(
            messages=[
                HumanMessage(content="chào", additional_kwargs={"at": "2026-08-16T10:00:00+00:00"}),
                AIMessage(
                    content="Chào bạn!",
                    additional_kwargs={"emitted_by": "respond", "at": "2026-08-16T10:00:02+00:00"},
                ),
            ]
        )

        session_store.persist_graph_session(_session(), state)

        assert [m["created_at"] for m in fake_supabase.messages] == [
            "2026-08-16T10:00:00+00:00",
            "2026-08-16T10:00:02+00:00",
        ]


class TestOwnership:
    def test_stamps_the_owner_so_the_row_reaches_that_users_rail(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(owner="user-42"), _graph_state())
        assert ("sessions", {"user_id": "user-42"}) in fake_supabase.calls["updates"]

    def test_writes_no_owner_for_an_anonymous_session(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(owner=None), _graph_state())
        assert "updates" not in fake_supabase.calls

    def test_refuses_an_unsafe_session_id(self, fake_supabase: _FakeSupabase):
        with pytest.raises(ValueError):
            session_store.persist_graph_session(_session(session_id="../etc/passwd"), _graph_state())


class _FakeGraphApp:
    """Stands in for the compiled graph: no LLM, no checkpointer, but the same
    two calls `_run_turn_via_graph` makes."""

    def __init__(self, final_state: dict[str, Any], result: dict[str, Any] | None = None) -> None:
        self.final_state = final_state
        self.result = result if result is not None else {"response": _RESPONSE}
        self.invocations: list[Any] = []

    def get_state(self, _config):
        return SimpleNamespace(values=self.final_state, interrupts=())

    def invoke(self, payload, config=None):
        self.invocations.append(payload)
        return self.result


_RESPONSE = {"session_id": "sess-1", "reply": "Bạn đi mấy người?", "stage": "intake"}


@pytest.fixture
def wired_turn(monkeypatch: pytest.MonkeyPatch, fake_supabase: _FakeSupabase):
    """`_run_turn_via_graph` with the graph and the database both faked."""
    import src.api.routes as routes

    app = _FakeGraphApp(_graph_state())
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persistence_enabled", True)
    monkeypatch.setattr(routes.registry, "get", lambda _sid: _session())
    return SimpleNamespace(routes=routes, app=app, db=fake_supabase)


class TestRunTurnWiring:
    def test_a_completed_turn_writes_the_session_and_its_transcript(self, wired_turn):
        wired_turn.routes._run_turn_via_graph("sess-1", "đi đà nẵng 4 ngày", "vi")

        assert wired_turn.db.context["schema_version"] == 3
        assert len(wired_turn.db.messages) >= 1

    def test_a_turn_that_pauses_at_an_interrupt_is_persisted_too(self, wired_turn):
        """The user answered something; the graph paused waiting on a
        clarification. That exchange is as real as any other and must survive a
        reload — persisting only completed turns loses it."""
        wired_turn.app.result = {"__interrupt__": [SimpleNamespace(value={"message": "Năm nào?"})]}

        response = wired_turn.routes._run_turn_via_graph("sess-1", "đi ngày 1/7", "vi")

        assert response.reply == "Năm nào?"
        assert wired_turn.db.context["schema_version"] == 3

    def test_persistence_disabled_touches_no_database(self, wired_turn, monkeypatch):
        monkeypatch.setattr(wired_turn.routes, "_persistence_enabled", False)

        wired_turn.routes._run_turn_via_graph("sess-1", "đi đà nẵng", "vi")

        assert wired_turn.db.calls == {}

    def test_a_database_outage_does_not_cost_the_user_their_answer(self, wired_turn, monkeypatch):
        """Best-effort, exactly like the persist hook it replaces: the turn is
        already computed by the time we write, so a failed write must degrade to
        a log line, never a 500."""

        def _explode(*_args, **_kwargs):
            raise RuntimeError("supabase unreachable")

        monkeypatch.setattr(session_store, "persist_graph_session", _explode)

        response = wired_turn.routes._run_turn_via_graph("sess-1", "đi đà nẵng", "vi")

        assert response.reply == "Bạn đi mấy người?"


class TestSummarizeAcrossVersions:
    """The history rail must keep rendering rows written by every writer that
    has ever run, not only the current one."""

    def test_reads_a_v3_row(self):
        row = {
            "session_id": "s3",
            "context_data": {
                "schema_version": 3,
                "travel_state": {},
                "trip": {},
                "ui_summary": {"destination": "Huế", "duration_days": 3, "status": "draft"},
            },
        }
        summary = session_store.summarize(row)
        assert (summary["destination"], summary["duration_days"], summary["status"]) == ("Huế", 3, "draft")

    def test_reads_a_v2_row(self):
        row = {
            "session_id": "s2",
            "context_data": {
                "schema_version": 2,
                "workflow": {},
                "ui_summary": {"destination": "Đà Lạt", "duration_days": 2, "status": "completed"},
            },
        }
        summary = session_store.summarize(row)
        assert (summary["destination"], summary["status"]) == ("Đà Lạt", "completed")

    def test_reads_a_v1_row(self):
        row = {
            "session_id": "s1",
            "context_data": {"intake": {"destination": "Hà Nội"}, "trip_data": {"duration_days": 5}},
        }
        summary = session_store.summarize(row)
        assert (summary["destination"], summary["duration_days"]) == ("Hà Nội", 5)
