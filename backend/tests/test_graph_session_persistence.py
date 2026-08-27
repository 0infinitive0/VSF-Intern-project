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

    def test_also_embeds_a_full_trip_data_copy(self, fake_supabase: _FakeSupabase):
        """Second, independent durable copy alongside `trip`'s pointer --
        added after a 2026-08-25 incident where the itineraries table's own
        write silently failed and nothing survived the checkpoint's 2h TTL.
        This copy rides the same RPC+upsert path chat_messages already
        proved reliable for that exact session -- recover_trip_data (below)
        is what reads it back."""
        state = _graph_state()
        session_store.persist_graph_session(_session(), state)
        assert fake_supabase.context["trip_data"] == state["trip_data"]

    def test_also_embeds_the_shown_hotel_options_list(self, fake_supabase: _FakeSupabase):
        """Same idea as `trip_data` above, applied to `previous_hotel_options`
        -- the real ranked search-results list, which otherwise lives ONLY in
        the checkpoint (see this function's own doc comment for the two live
        symptoms this fixes: a picked hotel losing its 4 alternatives, and a
        guest who hadn't picked one yet losing the Hotels tab outright)."""
        state = _graph_state(previous_hotel_options=[{"id": "h-1", "name": "Mường Thanh"}])
        session_store.persist_graph_session(_session(), state)
        assert fake_supabase.context["hotel_options"] == [{"id": "h-1", "name": "Mường Thanh"}]

    def test_hotel_options_embeds_as_an_empty_list_when_none_were_shown(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert fake_supabase.context["hotel_options"] == []


class TestTranscript:
    def test_records_the_user_turn_and_the_reply(self, fake_supabase: _FakeSupabase):
        session_store.persist_graph_session(_session(), _graph_state())
        assert [(m["sender_type"], m["message_content"]) for m in fake_supabase.messages] == [
            ("user", "đi đà nẵng 4 ngày"),
            ("assistant", "Bạn đi mấy người?"),
        ]

    def test_excludes_a_preference_refresh_reply_from_the_durable_transcript(
        self, fake_supabase: _FakeSupabase
    ):
        state = _graph_state(
            messages=[
                HumanMessage(content="tìm khách sạn có hồ bơi"),
                AIMessage(content="Mình tìm được 2 khách sạn phù hợp.", additional_kwargs={"emitted_by": "respond"}),
                AIMessage(
                    content="Mình tìm được 5 khách sạn phù hợp.",
                    additional_kwargs={"emitted_by": "respond", "omit_from_transcript": True},
                ),
            ]
        )

        session_store.persist_graph_session(_session(), state)

        assert [(m["sender_type"], m["message_content"]) for m in fake_supabase.messages] == [
            ("user", "tìm khách sạn có hồ bơi"),
            ("assistant", "Mình tìm được 2 khách sạn phù hợp."),
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


class _FakeItineraryStore:
    """Same shape as test_restore_endpoint.py's / test_turn_runner_checkpoint_
    recovery.py's own stand-ins for `ItineraryStore.from_default()` -- kept
    local rather than shared, matching this file's own established style of
    plain per-module fakes."""

    def __init__(self, trip_data: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._trip_data = trip_data
        self._error = error
        self.calls: list[str] = []

    def load_session_trip_data_by_session(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(session_id)
        if self._error is not None:
            raise self._error
        return self._trip_data


def _patch_itinerary_store(monkeypatch: pytest.MonkeyPatch, fake_store: _FakeItineraryStore) -> None:
    monkeypatch.setattr(
        "src.services.itinerary_store.ItineraryStore.from_default", classmethod(lambda cls: fake_store)
    )


class TestRecoverTripData:
    """The shared fallback restore_session and run_turn both call once a
    session's LangGraph checkpoint is gone. Two independent durable copies,
    tried in order -- see this function's own doc comment (and
    _v3_context's) for why there are two, not one."""

    def test_prefers_the_itineraries_table_when_present(self, monkeypatch: pytest.MonkeyPatch):
        fake_store = _FakeItineraryStore(trip_data={"destination": "Từ itineraries"})
        _patch_itinerary_store(monkeypatch, fake_store)

        assert session_store.recover_trip_data("s1") == {"destination": "Từ itineraries"}
        assert fake_store.calls == ["s1"]

    def test_falls_back_to_the_embedded_context_data_copy(self, monkeypatch: pytest.MonkeyPatch):
        fake_store = _FakeItineraryStore(trip_data=None)
        _patch_itinerary_store(monkeypatch, fake_store)
        monkeypatch.setattr(
            session_store, "load", lambda _sid: {"context_data": {"trip_data": {"destination": "Từ context_data"}}}
        )

        assert session_store.recover_trip_data("s1") == {"destination": "Từ context_data"}

    def test_a_durable_lookup_failure_still_tries_the_embedded_copy(self, monkeypatch: pytest.MonkeyPatch):
        from src.services.itinerary_store import ItineraryStoreError

        fake_store = _FakeItineraryStore(error=ItineraryStoreError("supabase unreachable"))
        _patch_itinerary_store(monkeypatch, fake_store)
        monkeypatch.setattr(
            session_store, "load", lambda _sid: {"context_data": {"trip_data": {"destination": "Từ context_data"}}}
        )

        assert session_store.recover_trip_data("s1") == {"destination": "Từ context_data"}

    def test_returns_none_when_neither_source_has_anything(self, monkeypatch: pytest.MonkeyPatch):
        fake_store = _FakeItineraryStore(trip_data=None)
        _patch_itinerary_store(monkeypatch, fake_store)
        monkeypatch.setattr(session_store, "load", lambda _sid: None)

        assert session_store.recover_trip_data("s1") is None

    def test_returns_none_when_the_session_row_exists_but_never_embedded_trip_data(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A row written before this fix shipped -- context_data has no
        `trip_data` key at all, not just an empty one."""
        fake_store = _FakeItineraryStore(trip_data=None)
        _patch_itinerary_store(monkeypatch, fake_store)
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"trip": {}}})

        assert session_store.recover_trip_data("s1") is None


class TestRecoverHotelOptions:
    """Sibling to TestRecoverTripData for `previous_hotel_options` -- unlike
    `trip_data`, there is no structured-table copy to try first (see
    recover_hotel_options's own doc comment), so the embedded
    `context_data.hotel_options` copy is the only durable source."""

    def test_reads_the_embedded_copy(self, monkeypatch: pytest.MonkeyPatch):
        options = [{"id": "h-1", "name": "Mường Thanh"}]
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"hotel_options": options}})

        assert session_store.recover_hotel_options("s1") == options

    def test_returns_none_when_the_session_row_does_not_exist(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(session_store, "load", lambda _sid: None)

        assert session_store.recover_hotel_options("s1") is None

    def test_returns_none_when_context_data_never_embedded_hotel_options(self, monkeypatch: pytest.MonkeyPatch):
        """A row written before this fix shipped, or one where trip_data got
        embedded but no search had run yet -- context_data has no
        `hotel_options` key at all."""
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"trip_data": {}}})

        assert session_store.recover_hotel_options("s1") is None

    def test_returns_none_for_an_embedded_empty_list_not_just_a_missing_key(self, monkeypatch: pytest.MonkeyPatch):
        """A session that has run turns (so `hotel_options` is present, per
        _v3_context always writing at least `[]`) but never searched --
        `or None` normalizes an explicit `[]` the same as "nothing to
        recover", so callers fall back to hotel_options_from_trip_data
        exactly as they would for a missing key."""
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"hotel_options": []}})

        assert session_store.recover_hotel_options("s1") is None


class TestRecoverTravelState:
    """Sibling to TestRecoverTripData/TestRecoverHotelOptions for
    `travel_state` (destination/dates/party size/preferences) -- same shape
    as recover_hotel_options: no structured-table copy to try first, only
    the embedded `context_data.travel_state` copy."""

    def test_reads_the_embedded_copy(self, monkeypatch: pytest.MonkeyPatch):
        travel_state = {"destination": {"presence": "set", "value": "Đà Nẵng"}}
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"travel_state": travel_state}})

        assert session_store.recover_travel_state("s1") == travel_state

    def test_returns_none_when_the_session_row_does_not_exist(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(session_store, "load", lambda _sid: None)

        assert session_store.recover_travel_state("s1") is None

    def test_returns_none_when_context_data_never_embedded_travel_state(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"trip_data": {}}})

        assert session_store.recover_travel_state("s1") is None

    def test_returns_none_for_an_embedded_empty_dict_not_just_a_missing_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(session_store, "load", lambda _sid: {"context_data": {"travel_state": {}}})

        assert session_store.recover_travel_state("s1") is None
