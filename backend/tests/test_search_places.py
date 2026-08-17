"""Phase 13 (`phase-13-place-search.md`): `search_places` qa_node tool.

Calls the tool's underlying function directly via `.func(...)` (the `@tool`
wrapper's raw callable) with a minimal fake `ToolRuntime` -- avoids needing
a real LangGraph agent executor just to supply `tool_call_id`. `destination`
is a plain string argument (not read from graph state, see
`search_places.py`'s docstring for why), so no `TravelGraphState` scaffolding
is needed either.
"""

from __future__ import annotations

import src.agents.tools.search_places as search_places_module
from src.agents.tools.search_places import search_places
from src.services.search_center import CenterResolution
from src.services.supabase_search import DEFAULT_NEARBY_SEARCH_RADIUS_KM
from src.services.trip_scheduler import PlaceCandidate


class _FakeRuntime:
    tool_call_id = "tc-1"


def _reply(command) -> str:
    return command.update["messages"][0].content


def test_unknown_destination_returns_error_without_searching(monkeypatch):
    monkeypatch.setattr(search_places_module, "_get_destination_id", lambda _name: None)

    def _unreachable(*_a, **_kw):
        raise AssertionError("must not search before destination resolves")

    monkeypatch.setattr(search_places_module, "resolve_center", _unreachable)
    monkeypatch.setattr(search_places_module, "search_attraction_candidates", _unreachable)

    result = search_places.func(
        query="hải sản", destination="Nowhereville", near=None, category=None, limit=10, runtime=_FakeRuntime()
    )
    assert "Nowhereville" in _reply(result)


def test_no_center_asks_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(search_places_module, "_get_destination_id", lambda _name: "dest-1")
    monkeypatch.setattr(
        search_places_module,
        "resolve_center",
        lambda **_kw: CenterResolution(latitude=None, longitude=None, source="unresolved"),
    )

    def _unreachable(*_a, **_kw):
        raise AssertionError("must not search without a resolved center")

    monkeypatch.setattr(search_places_module, "search_attraction_candidates", _unreachable)

    result = search_places.func(
        query="quán cà phê", destination="Đà Nẵng", near=None, category=None, limit=10, runtime=_FakeRuntime()
    )
    reply = _reply(result)
    assert "quán cà phê" in reply
    assert "gần đâu" in reply.lower() or "near" in reply.lower()


def test_resolved_center_searches_and_formats_results(monkeypatch):
    monkeypatch.setattr(search_places_module, "_get_destination_id", lambda _name: "dest-1")
    monkeypatch.setattr(
        search_places_module,
        "resolve_center",
        lambda **_kw: CenterResolution(latitude=16.05, longitude=108.2, source="poi", poi_name="Cầu Rồng"),
    )

    captured: dict = {}

    def _fake_search(query, destination_id, *, match_count, root_latitude, root_longitude, max_radius_km):
        captured.update(
            query=query, destination_id=destination_id, match_count=match_count,
            root_latitude=root_latitude, root_longitude=root_longitude, max_radius_km=max_radius_km,
        )
        return [
            PlaceCandidate(id="a1", name="Nhà hàng Sông Hàn", description="Hải sản"),
            PlaceCandidate(id="a2", name="Quán Ốc Đêm", description=None),
        ]

    monkeypatch.setattr(search_places_module, "search_attraction_candidates", _fake_search)

    result = search_places.func(
        query="hải sản", destination="Đà Nẵng", near="Cầu Rồng", category=None, limit=5, runtime=_FakeRuntime()
    )
    reply = _reply(result)

    # max_radius_km must always accompany a resolved lat/lon: validate_radius_filter
    # requires all three of lat/lon/radius or none of them, and resolution.resolved
    # (checked above the search call) guarantees lat/lon are set here -- omitting
    # radius raised ValueError on every resolved search.
    assert captured == {
        "query": "hải sản", "destination_id": "dest-1", "match_count": 5,
        "root_latitude": 16.05, "root_longitude": 108.2, "max_radius_km": DEFAULT_NEARBY_SEARCH_RADIUS_KM,
    }
    assert "Nhà hàng Sông Hàn" in reply
    assert "Quán Ốc Đêm" in reply


def test_zero_results_reports_no_match(monkeypatch):
    monkeypatch.setattr(search_places_module, "_get_destination_id", lambda _name: "dest-1")
    monkeypatch.setattr(
        search_places_module,
        "resolve_center",
        lambda **_kw: CenterResolution(latitude=16.05, longitude=108.2, source="poi"),
    )
    monkeypatch.setattr(search_places_module, "search_attraction_candidates", lambda *_a, **_kw: [])

    result = search_places.func(
        query="karaoke", destination="Đà Nẵng", near="Cầu Rồng", category=None, limit=5, runtime=_FakeRuntime()
    )
    assert "không tìm thấy" in _reply(result).lower()
