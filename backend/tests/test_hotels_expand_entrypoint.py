"""Contract tests for the dedicated no-LLM hotel-list expansion entry point."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

import src.agents.graph.nodes.hotel_node as hotel_node_module
import src.api.routes as routes
import src.services.supabase_search as supabase_search_module
from src.agents.graph.nodes.hotel_node import hotel_node
from src.models.schemas import HotelPreferenceToggleRequest
from src.services.trip_scheduler import PlaceCandidate


class _FakeGraph:
    def __init__(self, state: dict | None = None) -> None:
        self.command: Command | None = None
        self.state = state or {"travel_state": {}}
        self.get_state_calls = 0

    def get_state(self, _config):
        self.get_state_calls += 1
        return SimpleNamespace(values=self.state)

    def invoke(self, command: Command, *, config):
        self.command = command
        return {"response": {"session_id": config["configurable"]["thread_id"]}}


def test_expand_reenters_hotel_node_with_only_the_display_command(monkeypatch):
    app = _FakeGraph()
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persist_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "_response_from_result", lambda _session_id, result: result["response"])

    response = routes._rerun_hotel_search("expand-session", expand_hotel_options=True)

    assert response == {"session_id": "expand-session"}
    assert app.command is not None
    assert app.command.goto == "hotel_node"
    assert app.command.update["expand_hotel_options"] is True
    assert app.command.update["task_results"] == []


def test_preference_toggle_reenters_hotel_node_with_the_patched_state(monkeypatch):
    amenity = {
        "id": "spa",
        "label": "Spa",
        "polarity": "require",
        "source_phrase": "spa",
        "confidence": 1.0,
        "active": True,
    }
    app = _FakeGraph({
        "previous_hotel_search_context": {"destination_id": "nha-trang"},
        "travel_state": {
            "hotel_preferences.amenities": {"presence": "set", "value": [amenity]},
        },
    })
    session = SimpleNamespace(lock=nullcontext())
    monkeypatch.setattr(routes.registry, "evict_expired", lambda: None)
    monkeypatch.setattr(routes, "_owned_session_or_404", lambda *_args: session)
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persist_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "_response_from_result", lambda _session_id, result: result["response"])

    response = routes.toggle_hotel_preference(
        HotelPreferenceToggleRequest(session_id=uuid4(), amenity_id="spa", active=False),
        current_user=None,
    )

    assert response["session_id"]
    assert app.command is not None
    assert app.command.goto == "hotel_node"
    assert app.command.update["travel_state"]["hotel_preferences.amenities"]["value"] == [
        {**amenity, "active": False},
    ]


def test_preference_toggle_refreshes_payload_without_filter_extraction(monkeypatch):
    amenity = {
        "id": "spa",
        "label": "Spa",
        "polarity": "require",
        "source_phrase": "spa",
        "confidence": 1.0,
        "active": True,
    }
    travel_state = {
        "destination": {"presence": "set", "value": "Đà Nẵng"},
        "people": {"presence": "set", "value": 2},
        "dates.start": {"presence": "set", "value": "2099-01-01"},
        "dates.end": {"presence": "set", "value": "2099-01-05"},
        "budget.target": {"presence": "set", "value": 1_000_000},
        "preferences.themes": {"presence": "set", "value": None},
        "hotel_preferences.amenities": {"presence": "set", "value": [amenity]},
    }
    app = _FakeGraph({"previous_hotel_search_context": {"destination_id": "dest-1"}, "travel_state": travel_state})
    session = SimpleNamespace(lock=nullcontext())
    selected_kwargs: list[dict] = []

    def _select(*_args, **kwargs):
        selected_kwargs.append(kwargs)
        hotel = {
            "id": "h1", "destination_id": "dest-1", "name": "Hotel One", "star_rating": 4,
            "coordinates": "16.05,108.2", "matched_rooms": [], "covered_meals": [],
            "review_score": 8.0, "amenities": [], "similarity": 0.7,
        }
        return [(hotel, PlaceCandidate.from_mapping({**hotel, "category": "Hotel"}))]

    def _invoke(command: Command, *, config):
        app.command = command
        result = hotel_node({
            **command.update,
            "session_id": config["configurable"]["thread_id"],
            "language": "vi",
            "messages": [HumanMessage(content="refresh hotels")],
            "pending_tasks": ["hotel_node"],
            "task_results": [],
        })
        options = result["task_results"][-1]["hotel_search_result"]["options"]
        return {"response": {"session_id": config["configurable"]["thread_id"], "hotel_options": options}}

    def _extract_filters_must_not_run(*_args, **_kwargs):
        raise AssertionError("must not extract filters")

    monkeypatch.setattr(routes.registry, "evict_expired", lambda: None)
    monkeypatch.setattr(routes, "_owned_session_or_404", lambda *_args: session)
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persist_turn", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes, "_response_from_result", lambda _session_id, result: result["response"])
    monkeypatch.setattr(hotel_node_module, "_get_destination_id", lambda _destination: "dest-1")
    monkeypatch.setattr(hotel_node_module, "select_hotel_candidates", _select)
    monkeypatch.setattr(hotel_node_module.session_store, "session_has_paid_booking", lambda _session_id: False)
    monkeypatch.setattr(supabase_search_module, "extract_search_filters", _extract_filters_must_not_run)
    monkeypatch.setattr(app, "invoke", _invoke)

    response = routes.toggle_hotel_preference(
        HotelPreferenceToggleRequest(session_id=uuid4(), amenity_id="spa", active=False),
        current_user=None,
    )

    assert [option["id"] for option in response["hotel_options"]] == ["h1"]
    assert [kwargs["use_llm_filter"] for kwargs in selected_kwargs] == [False]


def test_rerun_reuses_snapshot_and_defers_persistence(monkeypatch):
    app = _FakeGraph({"travel_state": {}})
    deferred: list[tuple] = []
    persisted: list[tuple] = []

    class _BackgroundTasks:
        def add_task(self, func, *args, **kwargs):
            deferred.append((func, args, kwargs))

    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persist_turn", lambda *args, **kwargs: persisted.append((args, kwargs)))
    monkeypatch.setattr(routes, "_response_from_result", lambda _session_id, result: result["response"])

    response = routes._rerun_hotel_search(
        "preference-session",
        snapshot_values=app.state,
        background_tasks=_BackgroundTasks(),
    )

    assert response == {"session_id": "preference-session"}
    assert app.get_state_calls == 0
    assert persisted == []
    func, args, kwargs = deferred.pop()
    func(*args, **kwargs)
    assert persisted[0][0][0] == "preference-session"
    assert persisted[0][1] == {}


def test_deferred_persistence_skips_a_superseded_session_write(monkeypatch):
    session = SimpleNamespace(lock=nullcontext(), _persistence_generation=2)
    persisted: list[bool] = []
    monkeypatch.setattr(routes.registry, "get", lambda _session_id: session)

    routes._run_deferred_persist("preference-session", 1, lambda: persisted.append(True))

    assert persisted == []
