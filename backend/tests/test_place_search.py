"""Regression coverage for search_attraction_candidates_tiered's hydration wiring.

match_attractions' radius predicate is fixed at the RPC layer now (a
coordinate-format regex bug, see
plans/reports/debug-260817-0857-match-attractions-radius-filter.md /
scripts/migrations/20260817_fix_match_attractions_radius_regex.sql), so
per-tier distance filtering happens entirely server-side again -- see
test_supabase_search.py's test_tiered_attraction_search_* for that coverage.
This file only covers what search_attraction_candidates_tiered itself still
does: requiring hotel coordinates, forwarding them to the RPC, and hydrating
the RPC's compact rows into PlaceCandidates.
"""

from __future__ import annotations

import pytest

import src.services.place_search as place_search_module
from src.services.place_search import search_attraction_candidates_tiered
from src.services.trip_scheduler import PlaceCandidate

HOTEL = PlaceCandidate(id="hotel-1", name="Test Hotel", coordinates="16.463584369906,107.616792805241")


def test_tiered_search_requires_hotel_coordinates():
    hotel_without_coords = PlaceCandidate(id="hotel-2", name="No Coords Hotel", coordinates=None)
    with pytest.raises(ValueError, match="hotel with coordinates is required"):
        search_attraction_candidates_tiered("museum", "destination-id", hotel_without_coords, required_count=3)


def test_tiered_search_forwards_hotel_coordinates_and_hydrates_rpc_results(monkeypatch):
    captured: dict = {}

    def _fake_rpc(query, *, required_count, filter_destination_id, root_latitude, root_longitude, **kwargs):
        captured.update(
            query=query, required_count=required_count, filter_destination_id=filter_destination_id,
            root_latitude=root_latitude, root_longitude=root_longitude, extra_kwargs=kwargs,
        )
        return [{"id": "attr-1"}]

    def _fake_hydrate(table_name, search_results, _fields):
        captured["hydrate_table"] = table_name
        captured["hydrate_ids"] = [row["id"] for row in search_results]
        return [{"id": "attr-1", "name": "Vincom Plaza Huế", "coordinates": "16.47,107.62"}]

    monkeypatch.setattr(place_search_module, "rpc_search_attractions_tiered", _fake_rpc)
    monkeypatch.setattr(place_search_module, "hydrate_records", _fake_hydrate)

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=5)

    assert captured["query"] == "museum"
    assert captured["required_count"] == 5
    assert captured["filter_destination_id"] == "destination-id"
    assert captured["root_latitude"] == 16.463584369906
    assert captured["root_longitude"] == 107.616792805241
    assert captured["extra_kwargs"] == {}
    assert captured["hydrate_table"] == "attractions"
    assert captured["hydrate_ids"] == ["attr-1"]
    assert [c.id for c in results] == ["attr-1"]
    assert results[0].name == "Vincom Plaza Huế"


def test_tiered_search_forwards_exclude_attraction_ids_only_when_given(monkeypatch):
    captured: dict = {}

    def _fake_rpc(_query, *, required_count, filter_destination_id, root_latitude, root_longitude, **kwargs):
        captured["extra_kwargs"] = kwargs
        return []

    monkeypatch.setattr(place_search_module, "rpc_search_attractions_tiered", _fake_rpc)
    monkeypatch.setattr(place_search_module, "hydrate_records", lambda *a, **k: [])

    search_attraction_candidates_tiered(
        "museum", "destination-id", HOTEL, required_count=5, exclude_attraction_ids=["a", "b"]
    )

    assert captured["extra_kwargs"] == {"exclude_attraction_ids": ["a", "b"]}


def test_tiered_search_drops_candidates_with_unparseable_coordinates(monkeypatch):
    good = {"id": "good", "name": "good", "coordinates": "16.470,107.620"}
    broken = {"id": "broken", "name": "broken", "coordinates": None}

    monkeypatch.setattr(place_search_module, "rpc_search_attractions_tiered", lambda *a, **k: [good, broken])
    monkeypatch.setattr(place_search_module, "hydrate_records", lambda *a, **k: [good, broken])

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=5)

    assert [c.id for c in results] == ["good"]
