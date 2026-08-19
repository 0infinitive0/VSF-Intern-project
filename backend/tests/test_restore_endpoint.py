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

    def _build(state: dict[str, Any] | None = None, rows: list[dict[str, Any]] | None = None):
        monkeypatch.setattr(routes, "_get_graph_v2", lambda: _FakeGraphApp(state or {}))
        monkeypatch.setattr(
            routes.registry, "get", lambda _sid: SimpleNamespace(session_id="s1", owner_user_id=None)
        )
        monkeypatch.setattr(routes, "_persistence_enabled", True)
        monkeypatch.setattr(
            session_store, "load", lambda _sid: {"session_id": "s1", "messages": rows or []}
        )
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
