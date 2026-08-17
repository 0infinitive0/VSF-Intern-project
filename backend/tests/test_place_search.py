"""Regression coverage for the radius-filter patch described in
plans/reports/debug-260817-0857-match-attractions-radius-filter.md.

The deployed `match_attractions` RPC's distance predicate always evaluates to
NULL once root_latitude/root_longitude/max_radius_km are all supplied, which
discarded every row. `search_attraction_candidates_tiered` now fetches one
broad, threshold-only pool (see test_supabase_search.py) and enforces the
(radius, threshold) tier cascade itself, in Python, against hydrated
coordinates -- these tests cover that cascade.
"""

from __future__ import annotations

import pytest

import src.services.place_search as place_search_module
from src.services.place_search import search_attraction_candidates_tiered
from src.services.trip_scheduler import PlaceCandidate

# Real coordinates from the diagnosed hotel (LOVE HOME-peaceful Nera Apart, Hue)
# in the linked debug report -- not synthetic, so tier math matches production.
HOTEL = PlaceCandidate(id="hotel-1", name="Test Hotel", coordinates="16.463584369906,107.616792805241")


def _row(place_id: str, similarity: float, coordinates: str | None) -> dict:
    return {
        "id": place_id,
        "name": place_id,
        "category": "Attraction",
        "coordinates": coordinates,
        "similarity": similarity,
        "description": "desc",
    }


def _stub_rpc_and_hydrate(monkeypatch, rows: list[dict]) -> None:
    monkeypatch.setattr(place_search_module, "rpc_search_attractions_tiered", lambda *a, **k: rows)
    monkeypatch.setattr(place_search_module, "hydrate_records", lambda *a, **k: rows)


def test_tiered_search_requires_hotel_coordinates():
    hotel_without_coords = PlaceCandidate(id="hotel-2", name="No Coords Hotel", coordinates=None)
    with pytest.raises(ValueError, match="hotel with coordinates is required"):
        search_attraction_candidates_tiered("museum", "destination-id", hotel_without_coords, required_count=3)


def test_tiered_search_filters_out_of_radius_candidates_via_haversine(monkeypatch):
    """A far-away candidate must not survive just because the RPC no longer
    filters by distance -- this is the exact bug the patch fixes."""
    near = _row("near", 0.5, "16.470,107.620")  # ~0.8km from the hotel
    far = _row("far", 0.9, "21.028,105.854")  # Hanoi, ~600km away -- outside every tier

    _stub_rpc_and_hydrate(monkeypatch, [near, far])

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=5)

    assert [c.id for c in results] == ["near"]


def test_tiered_search_assigns_the_tightest_tier_a_candidate_qualifies_for(monkeypatch):
    tight = _row("tight", 0.5, "16.470,107.620")  # ~0.8km, sim 0.50 -> tier 1 (3km, >0.40)
    loose = _row("loose", 0.30, "16.520,107.660")  # ~7.7km, sim 0.30 -> only tier 4 (12km, >0.25)

    _stub_rpc_and_hydrate(monkeypatch, [tight, loose])

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=5)

    tiers_by_id = {c.id: c.retrieval_tier for c in results}
    assert tiers_by_id == {"tight": 1, "loose": 4}


def test_tiered_search_stops_once_required_count_is_met(monkeypatch):
    rows = [_row(f"p{i}", 0.5, "16.470,107.620") for i in range(5)]  # all tier-1 eligible

    _stub_rpc_and_hydrate(monkeypatch, rows)

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=2)

    assert len(results) == 2
    assert all(c.retrieval_tier == 1 for c in results)


def test_tiered_search_drops_candidates_with_unparseable_coordinates(monkeypatch):
    good = _row("good", 0.5, "16.470,107.620")
    broken = _row("broken", 0.9, None)

    _stub_rpc_and_hydrate(monkeypatch, [good, broken])

    results = search_attraction_candidates_tiered("museum", "destination-id", HOTEL, required_count=5)

    assert [c.id for c in results] == ["good"]
