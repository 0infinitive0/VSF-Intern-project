"""Contract tests for the dedicated no-LLM hotel-list expansion entry point."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from langgraph.types import Command

import src.api.routes as routes
from src.models.schemas import HotelPreferenceToggleRequest


class _FakeGraph:
    def __init__(self, state: dict | None = None) -> None:
        self.command: Command | None = None
        self.state = state or {"travel_state": {}}

    def get_state(self, _config):
        return SimpleNamespace(values=self.state)

    def invoke(self, command: Command, *, config):
        self.command = command
        return {"response": {"session_id": config["configurable"]["thread_id"]}}


def test_expand_reenters_hotel_node_with_only_the_display_command(monkeypatch):
    app = _FakeGraph()
    monkeypatch.setattr(routes, "_get_graph_v2", lambda: app)
    monkeypatch.setattr(routes, "_persist_turn", lambda *_args: None)
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
    monkeypatch.setattr(routes, "_persist_turn", lambda *_args: None)
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
