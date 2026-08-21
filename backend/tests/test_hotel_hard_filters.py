"""Phase 8 (260812-0927-langgraph-orchestration-state-patch-and-interrupts):
`select_hotel_candidates`'s new hard filters — `required_amenities`
(AND semantics), `min_star_rating`, `min_review_score` — and the
gym/spa/restaurant taxonomy additions. `test_hotel_selection.py` keeps the
pre-existing coverage (ranking, budget, radius forwarding); this file is
scoped to what Phase 8 added.
"""

from __future__ import annotations

import pytest

import src.services.hotel_selection as hotel_selection_module
from src.services.hotel_selection import (
    NoHotelsMatchAmenities,
    NoHotelsMatchRating,
    hotel_matches_amenity_tag,
    is_hotel_amenity_tag,
    select_hotel_candidates,
)


class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def execute(self) -> _FakeResult:
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, *_args, **_kwargs) -> _FakeTable:
        return self

    def in_(self, _column: str, ids) -> _FakeQuery:
        id_set = {str(value) for value in ids}
        return _FakeQuery([row for row in self._rows if str(row.get("id")) in id_set])


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeTable:
        return _FakeTable(self._rows)


def _hotel_row(
    id_: str,
    *,
    amenities: list[str] | None = None,
    star_rating: float | None = 4,
    review_score: float | None = 8.0,
) -> dict:
    return {
        "id": id_,
        "destination_id": "dest-1",
        "name": f"Hotel {id_}",
        "star_rating": star_rating,
        "description": "desc",
        "coordinates": "16.05,108.2",
        "amenities": amenities or [],
        "amenity_groups": {},
        "review_score": review_score,
        "review_count": 10,
        "address": None,
        "area_name": None,
        "lowest_price": 1_000_000,
        "currency": "VND",
        "image_url": None,
    }


def _wire(monkeypatch, rows: list[dict], *, search_kwargs_capture: dict | None = None):
    def fake_search_hotels_with_rooms(**kwargs):
        if search_kwargs_capture is not None:
            search_kwargs_capture.update(kwargs)
        return [{"id": row["id"], "similarity": 0.7} for row in rows]

    monkeypatch.setattr(hotel_selection_module, "search_hotels_with_rooms", fake_search_hotels_with_rooms)
    monkeypatch.setattr(hotel_selection_module, "_get_supabase_client", lambda: _FakeSupabaseClient(rows))


# --- required_amenities: hard filter, AND semantics ------------------------


def test_required_amenities_excludes_hotels_missing_the_tag(monkeypatch):
    rows = [_hotel_row("has-pool", amenities=["pool"]), _hotel_row("no-pool", amenities=["wifi"])]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", required_amenities=("pool",))

    assert [data["id"] for data, _ in options] == ["has-pool"]


def test_required_amenities_and_semantics_requires_every_tag(monkeypatch):
    rows = [
        _hotel_row("both", amenities=["gym", "pool"]),
        _hotel_row("gym-only", amenities=["gym"]),
        _hotel_row("pool-only", amenities=["pool"]),
    ]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", required_amenities=("gym", "pool"))

    assert [data["id"] for data, _ in options] == ["both"]


def test_multiple_required_amenities_relax_to_best_partial_matches(monkeypatch):
    # No hotel has gym at all; two of three have pool. Dropping "gym" alone
    # would unlock 2 results; dropping "pool" alone unlocks 0 (still no
    # gym-having hotel exists) -- "gym" is the real binding constraint.
    rows = [
        _hotel_row("pool-1", amenities=["pool"]),
        _hotel_row("pool-2", amenities=["pool"]),
        _hotel_row("neither", amenities=["wifi"]),
    ]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates(
        "Đà Nẵng", "dest-1", "2 người", required_amenities=("gym", "pool")
    )

    assert [data["id"] for data, _ in options] == ["pool-1", "pool-2"]
    assert all(data["amenity_match"]["missing"] == ["gym"] for data, _ in options)
    assert all(data["amenity_match"]["relaxed"] == ["gym"] for data, _ in options)


def test_single_required_amenity_with_zero_results_still_raises(monkeypatch):
    _wire(monkeypatch, [_hotel_row("no-gym", amenities=["wifi"])])

    with pytest.raises(NoHotelsMatchAmenities):
        select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", required_amenities=("gym",))


def test_excluded_amenity_removes_matching_hotels(monkeypatch):
    rows = [
        _hotel_row("pool", amenities=["swimming_pool"]),
        _hotel_row("quiet", amenities=["wifi"]),
    ]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates(
        "Đà Nẵng", "dest-1", "2 người", excluded_amenities=("swimming_pool",)
    )

    assert [data["id"] for data, _ in options] == ["quiet"]


def test_general_parent_matches_a_specific_descendant(monkeypatch):
    rows = [_hotel_row("free", amenities=["free_parking"])]
    _wire(monkeypatch, rows)
    monkeypatch.setattr(
        hotel_selection_module,
        "expand_amenity_descendants",
        lambda ids, scope="hotel": {"parking": frozenset({"parking", "free_parking"})},
    )

    options = select_hotel_candidates(
        "Đà Nẵng", "dest-1", "2 người", required_amenities=("parking",)
    )

    assert [data["id"] for data, _ in options] == ["free"]


def test_required_amenities_never_raised_for_callers_that_omit_it(monkeypatch):
    """The four (now five) pre-existing call sites never pass
    `required_amenities` -- this exception must be structurally unreachable
    for them, even when the RPC legitimately returns zero rows."""
    _wire(monkeypatch, [])

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người")

    assert options == []


def test_gym_spa_restaurant_resolve_from_builtin_taxonomy_without_discovery():
    for tag in ("gym", "spa", "restaurant"):
        assert is_hotel_amenity_tag(tag)

    assert hotel_matches_amenity_tag({"amenities": ["gym"]}, "gym")
    assert hotel_matches_amenity_tag({"amenities": ["spa"]}, "spa")
    assert hotel_matches_amenity_tag({"amenities": ["restaurant"]}, "restaurant")
    assert not hotel_matches_amenity_tag({"amenities": ["wifi"]}, "gym")


# --- min_star_rating / min_review_score: hard filter, no silent fallback ---


def test_min_star_rating_excludes_lower_and_missing_ratings(monkeypatch):
    rows = [
        _hotel_row("five-star", star_rating=5),
        _hotel_row("three-star", star_rating=3),
        _hotel_row("unrated", star_rating=None),
    ]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", min_star_rating=4)

    assert [data["id"] for data, _ in options] == ["five-star"]


def test_min_star_rating_zero_results_raises_instead_of_silently_widening(monkeypatch):
    rows = [_hotel_row("three-star", star_rating=3)]
    _wire(monkeypatch, rows)

    with pytest.raises(NoHotelsMatchRating) as excinfo:
        select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", min_star_rating=4)

    assert excinfo.value.min_star_rating == 4
    # The old bug: falling back to `data[:match_count]` (an unfiltered,
    # 3-star result) instead of raising. Confirm no such silent path exists.


def test_min_review_score_is_filterable(monkeypatch):
    rows = [_hotel_row("great", review_score=9.0), _hotel_row("mediocre", review_score=6.0)]
    _wire(monkeypatch, rows)

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", min_review_score=8.0)

    assert [data["id"] for data, _ in options] == ["great"]


def test_rating_filter_runs_before_amenity_filter_so_zero_blames_rating(monkeypatch):
    """When rating alone would already zero out every candidate, the
    diagnostic must name rating, not amenities -- otherwise a request like
    "khách sạn 5 sao có hồ bơi" would misleadingly blame the pool."""
    rows = [_hotel_row("three-star-with-pool", star_rating=3, amenities=["hồ bơi"])]
    _wire(monkeypatch, rows)

    with pytest.raises(NoHotelsMatchRating):
        select_hotel_candidates(
            "Đà Nẵng", "dest-1", "2 người", min_star_rating=5, required_amenities=("pool",)
        )


# --- min_guests: enforced inside the RPC, not app-level -------------------
#
# The real filter (summing `available units * max_guests` across every room
# type at a hotel, so a party that needs multiple rooms/room types is
# accounted for) lives in `match_hotels_with_rooms` itself -- see
# scripts/migrations/20260820_add_guest_capacity_filter_to_match_hotels_with_
# rooms.sql. That SQL logic isn't exercised by these unit tests (`_wire`
# stubs `search_hotels_with_rooms` entirely); what belongs here is only that
# `select_hotel_candidates` forwards `min_guests` through untouched, and
# does NOT lump it in with the app-level hard filters that need overfetching.


def test_min_guests_is_forwarded_to_the_search_rpc(monkeypatch):
    captured: dict = {}
    _wire(monkeypatch, [], search_kwargs_capture=captured)

    select_hotel_candidates("Đà Nẵng", "dest-1", "4", min_guests=4)

    assert captured["min_guests"] == 4


def test_min_guests_omitted_is_not_forwarded(monkeypatch):
    """The pre-existing call sites never pass `min_guests` -- confirm the RPC
    call omits the key entirely (byte-identical request shape), the same
    convention `start_date`/`root_latitude`/etc. already follow here."""
    captured: dict = {}
    _wire(monkeypatch, [], search_kwargs_capture=captured)

    select_hotel_candidates("Đà Nẵng", "dest-1", "2 người")

    assert "min_guests" not in captured


def test_min_guests_alone_does_not_trigger_the_hard_filter_overfetch(monkeypatch):
    """Unlike `required_amenities`/`min_star_rating`/`min_review_score`, capacity
    is filtered by the RPC before its own LIMIT -- `match_count` hotels back
    already satisfy it, so no app-side overfetch-then-reduce is needed."""
    captured: dict = {}
    _wire(monkeypatch, [], search_kwargs_capture=captured)

    select_hotel_candidates("Đà Nẵng", "dest-1", "4", match_count=5, min_guests=4)

    assert captured["match_count"] == 5


def test_hard_filter_overfetches_the_rpc_match_count(monkeypatch):
    captured: dict = {}
    _wire(monkeypatch, [], search_kwargs_capture=captured)

    select_hotel_candidates("Đà Nẵng", "dest-1", "2 người", match_count=5, required_amenities=("pool",))

    assert captured["match_count"] > 5
