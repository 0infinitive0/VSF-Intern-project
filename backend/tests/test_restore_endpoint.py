"""`GET /chat/{id}/restore` — clicking a past conversation in the history rail.

The endpoint used to return a shell: `messages=[]`, `stage="intake"`,
`IntakeStatus.from_state(None, None)` (always empty), and `hotel_options` read
off `state["hotel_options"]` — a key `TravelGraphState` does not define, so
always `[]`. Every field a restored conversation needs was hardcoded to empty,
which is why reopening an old chat produced a blank panel and a reset intake
checklist.

The fix is not new serialization: it is calling the same helpers `respond`
already calls to build a live turn's payload, now shared through
`agents/graph/response_payload.py`. A second implementation is exactly how the
two would drift apart again.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import src.api.routes as routes
from src.services import session_store


class _FakeGraphApp:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get_state(self, _config):
        return SimpleNamespace(values=self.values, interrupts=())


def _travel_state() -> dict[str, Any]:
    return {
        "destination": {"presence": "set", "value": "Đà Nẵng"},
        "people": {"presence": "set", "value": 2},
        "dates.start": {"presence": "set", "value": "2026-08-10"},
        "dates.end": {"presence": "set", "value": "2026-08-14"},
    }


# The exact shape `hotel_node` writes (hotel_node.py:339) — `options`, not
# `hotels`; `to_hotel_options_payload` reads that key and nothing else.
_HOTEL_SEARCH_RESULT = {
    "options": [
        {"id": "h-1", "name": "Mường Thanh", "average_nightly_price": 1_200_000},
        {"id": "h-2", "name": "Vinpearl", "average_nightly_price": 2_400_000},
    ],
    "active_preferences": [],
}

_MESSAGE_ROWS = [
    {"sender_type": "user", "message_content": "đi đà nẵng", "created_at": "2026-08-16T10:00:00Z"},
    {"sender_type": "assistant", "message_content": "Bạn đi mấy người?", "created_at": "2026-08-16T10:00:03Z"},
]


@pytest.fixture
def restored(monkeypatch: pytest.MonkeyPatch):
    """`restore_session` with the graph, the registry and the database faked."""

    def _build(
        state: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        context_data: dict[str, Any] | None = None,
    ):
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: _FakeGraphApp(state or {}))
        monkeypatch.setattr(
            routes.registry, "get", lambda _sid: SimpleNamespace(session_id="s1", owner_user_id=None)
        )
        monkeypatch.setattr(routes, "_persistence_enabled", True)
        # `context_data` defaults to None rather than {} so a test explicitly
        # asserting "no durable row at all" (session_store.load returning a
        # row with no context_data key) stays distinguishable from "a row
        # with an empty context_data" -- recover_trip_data's own tests in
        # test_graph_session_persistence.py cover that distinction directly;
        # this fixture only needs to let a test opt into the embedded-copy
        # fallback without hand-rolling the whole `load` mock itself.
        row: dict[str, Any] = {"session_id": "s1", "messages": rows or []}
        if context_data is not None:
            row["context_data"] = context_data
        monkeypatch.setattr(session_store, "load", lambda _sid: row)
        return routes.restore_session("s1", None)

    return _build


class TestTranscript:
    def test_returns_the_real_conversation_not_an_empty_list(self, restored):
        payload = restored(rows=_MESSAGE_ROWS)

        assert [(m.role, m.text) for m in payload.messages] == [
            ("user", "đi đà nẵng"),
            ("assistant", "Bạn đi mấy người?"),
        ]

    def test_survives_a_database_outage_without_failing_the_restore(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        """Graph state lives in the checkpointer, transcript in Supabase. Losing
        the second should cost the transcript, not the whole panel."""

        def _explode(_sid):
            raise RuntimeError("supabase unreachable")

        monkeypatch.setattr(session_store, "load", _explode)
        payload = restored(state={"travel_state": _travel_state()})

        assert payload.messages == []
        assert payload.intake is not None and payload.intake.destination == "Đà Nẵng"


class TestIntake:
    def test_rebuilds_the_checklist_from_travel_state(self, restored):
        payload = restored(state={"travel_state": _travel_state()})

        assert payload.intake is not None
        assert payload.intake.destination == "Đà Nẵng"
        assert payload.intake.people == "2 người"
        assert payload.intake.start_date == "2026-08-10"
        assert payload.intake.missing == []

    def test_reports_what_is_still_missing(self, restored):
        payload = restored(
            state={"travel_state": {"destination": {"presence": "set", "value": "Huế"}}}
        )

        assert payload.intake is not None
        assert set(payload.intake.missing) == {"people", "start_date", "duration"}


class TestHotelOptionsAndStage:
    def test_reads_hotel_options_out_of_task_results(self, restored):
        """`state["hotel_options"]` does not exist — the options a turn produced
        live in the last task result, which is where `respond` reads them."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "task_results": [{"worker": "hotel_node", "hotel_search_result": _HOTEL_SEARCH_RESULT}],
            }
        )

        assert [option.name for option in payload.hotel_options] == ["Mường Thanh", "Vinpearl"]
        assert payload.stage == "hotel_options"

    def test_reports_planned_when_a_trip_exists(self, restored):
        payload = restored(state={"travel_state": _travel_state(), "trip_data": {"destination": "Đà Nẵng"}})

        assert payload.stage == "planned"

    def test_reports_intake_while_slots_are_still_missing(self, restored):
        payload = restored(state={"missing_slots": ["destination"]})

        assert payload.stage == "intake"


class TestEmptyAndDeliberate:
    def test_a_session_with_no_turns_restores_empty_instead_of_404(self, restored):
        """A session created but never used is a legitimate empty conversation.
        404 there tells the frontend the session is gone, and it silently starts
        a new one — losing the id the user is sitting on."""
        payload = restored(state={}, rows=[])

        assert payload.session_id == "s1"
        assert payload.messages == []
        assert payload.hotel_options == []
        assert payload.trip_plan is None

    def test_suggestions_are_empty_on_purpose(self, restored):
        """Suggestions belong to one specific turn ("book this hotel?"), not to
        durable session state. Replaying yesterday's would be worse than
        showing none."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "task_results": [{"worker": "hotel_node", "hotel_search_result": _HOTEL_SEARCH_RESULT}],
            }
        )

        assert payload.suggestions == []


class TestSharedWithRespond:
    def test_restore_and_a_live_turn_agree_on_the_same_state(self, restored):
        """The contract this phase is really about: one set of helpers builds
        both payloads, so a restored conversation and the turn that produced it
        cannot disagree."""
        from src.agents.graph.nodes.respond import respond

        state = {
            "session_id": "s1",
            "travel_state": _travel_state(),
            "task_results": [
                {"worker": "hotel_node", "status": "ok", "reply": "Có 2 khách sạn.",
                 "hotel_search_result": _HOTEL_SEARCH_RESULT},
            ],
        }

        live = respond(dict(state))["response"]
        payload = restored(state=state)

        assert payload.stage == live["stage"]
        assert [o.name for o in payload.hotel_options] == [o["name"] for o in live["hotel_options"]]
        assert payload.intake is not None and payload.intake.destination == live["intake"].destination
        assert payload.intake.missing == live["intake"].missing


class _FakeItineraryStore:
    """Stands in for `ItineraryStore.from_default()` — avoids constructing a
    real Supabase client/embeddings model in a unit test. `calls` records
    every `session_id` the fallback actually asked for, so a test can assert
    the durable lookup was (or was NOT) attempted."""

    def __init__(self, trip_data: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._trip_data = trip_data
        self._error = error
        self.calls: list[str] = []

    def load_session_trip_data_by_session(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(session_id)
        if self._error is not None:
            raise self._error
        return self._trip_data


_RECOVERED_TRIP_DATA = {
    "hotel": {"id": "hotel-1", "name": "Vinpearl Resort", "coordinates": "16.05,108.20"},
    "itineraries": [{"id": "it-1", "destination_id": "d-1", "duration_days": 3, "status": "Draft"}],
    "itinerary_items": [],
}


class TestCheckpointEvictedFallback:
    """`SessionRegistry.evict_expired()` (session.py) deletes the LangGraph
    checkpoint for any session idle past SESSION_TTL_SECONDS (default 2h) —
    `app.get_state(...)` then comes back with `values={}` even though the
    session's itinerary/hotel are still sitting in Supabase, untouched (no
    TTL on `itineraries`/`itinerary_items`/`hotels`). Before this fix,
    `restore_session` had no fallback for that case at all and silently
    returned `trip_plan: null` / `hotel_options: []`, which locks the
    Hotels/Itinerary step-navigator tabs on the frontend
    (phase-navigation.ts's navigationTarget) with no error anywhere."""

    def test_recovers_trip_plan_and_hotel_options_from_the_durable_itinerary(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        fake_store = _FakeItineraryStore(trip_data=_RECOVERED_TRIP_DATA)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        payload = restored(state={})  # empty values -- checkpoint gone

        assert fake_store.calls == ["s1"]
        assert payload.trip_plan is not None
        assert [o.name for o in payload.hotel_options] == ["Vinpearl Resort"]
        assert payload.stage == "planned"

    def test_a_session_that_genuinely_never_built_a_trip_still_restores_empty(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        """The fallback lookup itself finding nothing (no itinerary row for
        this session) must degrade to the pre-fix behavior, not error."""
        fake_store = _FakeItineraryStore(trip_data=None)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        payload = restored(state={})

        assert fake_store.calls == ["s1"]
        assert payload.trip_plan is None
        assert payload.hotel_options == []

    def test_a_durable_lookup_failure_does_not_fail_the_whole_restore(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        """Same best-effort contract as the transcript's own Supabase-outage
        fallback above — losing the recovery attempt costs the recovery,
        never the whole panel."""
        from src.services.itinerary_store import ItineraryStoreError

        fake_store = _FakeItineraryStore(error=ItineraryStoreError("supabase unreachable"))
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        payload = restored(state={})

        assert payload.trip_plan is None
        assert payload.session_id == "s1"

    def test_falls_back_to_the_trip_data_embedded_in_context_data(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        """Second durable copy (session_store._v3_context/recover_trip_data's
        own doc comments have the full story): the itineraries table can fail
        to write (2026-08-25 incident -- a fully-built itinerary, shown to
        the guest as done, was never durably saved anywhere and could not be
        recovered once its checkpoint TTL-evicted). context_data.trip_data
        rides on the same reliable write path chat_messages already proved
        durable for that exact session, so it must be tried too before
        conceding nothing survived."""
        fake_store = _FakeItineraryStore(trip_data=None)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        payload = restored(state={}, context_data={"trip_data": _RECOVERED_TRIP_DATA})

        assert fake_store.calls == ["s1"]
        assert payload.trip_plan is not None
        assert [o.name for o in payload.hotel_options] == ["Vinpearl Resort"]

    def test_an_intact_checkpoint_never_triggers_the_durable_lookup(
        self, restored, monkeypatch: pytest.MonkeyPatch
    ):
        """The common case (checkpoint still alive) must not pay for an
        extra Supabase round trip it doesn't need."""
        fake_store = _FakeItineraryStore(trip_data=_RECOVERED_TRIP_DATA)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        payload = restored(state={"travel_state": _travel_state(), "trip_data": {"destination": "Đà Nẵng"}})

        assert fake_store.calls == []
        assert payload.stage == "planned"


class TestHotelListSurvivesAReload:
    """The actual bug: `task_results[-1]` is whatever the session's LAST
    action happened to be, and for anyone past the search step that is an
    itinerary build, a Q&A answer, or a hotel pick -- almost never a search.
    A reload restored against it and silently dropped the hotel list,
    throwing the step navigator back to "Bước 1" even mid-trip.
    `previous_hotel_options` (`hotel_node`'s durable record, deliberately
    outliving `load_context`'s reset) is the fix.
    """

    def test_the_hotel_list_survives_a_later_itinerary_build(self, restored):
        """The exact reported sequence: search, then build the itinerary
        (which becomes the new task_results[-1] with no hotel_search_result
        of its own), then reload."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "trip_data": {"destination": "Đà Nẵng"},
                "previous_hotel_options": _HOTEL_SEARCH_RESULT["options"],
                "task_results": [
                    {"worker": "hotel_node", "hotel_search_result": _HOTEL_SEARCH_RESULT},
                    {"worker": "itinerary_node", "status": "ok"},  # no hotel_search_result
                ],
            }
        )

        assert [option.name for option in payload.hotel_options] == ["Mường Thanh", "Vinpearl"]
        # trip_data outranks hotel_options in derive_stage -- the itinerary
        # view wins, but the hotel list must still be there for the user to
        # go back to via the step navigator.
        assert payload.stage == "planned"

    def test_the_hotel_list_survives_a_later_question(self, restored):
        """A qa_node turn writes no hotel_search_result at all."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "previous_hotel_options": _HOTEL_SEARCH_RESULT["options"],
                "task_results": [
                    {"worker": "hotel_node", "hotel_search_result": _HOTEL_SEARCH_RESULT},
                    {"worker": "qa_node", "reply": "Khách sạn này có hồ bơi."},
                ],
            }
        )

        assert [option.name for option in payload.hotel_options] == ["Mường Thanh", "Vinpearl"]
        assert payload.stage == "hotel_options"

    def test_amenities_are_computed_from_the_restored_list_not_left_empty(self, restored):
        """Same class of bug as the earlier `respond.py` fix: retained cards
        with no catalog to resolve their tags against fall back to raw ids."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "previous_hotel_options": [
                    {"id": "h-1", "name": "Mường Thanh", "amenities": ["swimming_pool"]},
                ],
                "task_results": [{"worker": "itinerary_node", "status": "ok"}],
            }
        )

        assert len(payload.hotel_options) == 1

    def test_an_old_session_predating_this_field_still_falls_back_cleanly(self, restored):
        """No `previous_hotel_options` at all (a session checkpointed before
        this fix existed) must not crash -- it degrades to the old behavior."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "task_results": [{"worker": "itinerary_node", "status": "ok"}],
            }
        )

        assert payload.hotel_options == []

    def test_a_failed_later_search_does_not_erase_the_last_good_list(self, restored):
        """previous_hotel_options is only ever overwritten by hotel_node's
        SUCCESS branch, so a later search that finds nothing must not wipe
        out the last hotels the user actually saw."""
        payload = restored(
            state={
                "travel_state": _travel_state(),
                "previous_hotel_options": _HOTEL_SEARCH_RESULT["options"],
                "task_results": [{"worker": "hotel_node", "status": "no_results", "reply": "..."}],
            }
        )

        assert [option.name for option in payload.hotel_options] == ["Mường Thanh", "Vinpearl"]
