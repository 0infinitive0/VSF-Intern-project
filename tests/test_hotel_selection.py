from __future__ import annotations

import src.services.hotel_selection as hotel_selection_module
from src.services.hotel_selection import (
    fetch_hotel_by_id,
    rank_hotel_candidates,
    resolve_hotel_selection,
    select_hotel_candidates,
)
from src.services.trip_scheduler import PlaceCandidate


def _option(
    id_: str,
    name: str,
    *,
    similarity: float = 0.5,
    star_rating: float | None = None,
    review_score: float | None = None,
    lowest_price: float | None = None,
) -> tuple[dict, PlaceCandidate]:
    data = {
        "id": id_,
        "destination_id": "dest-1",
        "name": name,
        "star_rating": star_rating,
        "description": "desc",
        "coordinates": "16.05,108.2",
        "matched_rooms": [],
        "covered_meals": [],
        "review_score": review_score,
        "review_count": None,
        "address": None,
        "area_name": None,
        "lowest_price": lowest_price,
        "currency": "VND",
        "image_url": None,
        "similarity": similarity,
    }
    candidate = PlaceCandidate.from_mapping({**data, "category": "Hotel"})
    return data, candidate


# ---- rank_hotel_candidates ----------------------------------------------------------


def test_rank_hotel_candidates_empty_returns_empty():
    assert rank_hotel_candidates([]) == []


def test_rank_hotel_candidates_higher_similarity_wins_when_other_factors_equal():
    lower_similarity = _option("a", "Khách sạn A", similarity=0.5, star_rating=4, review_score=8.0, lowest_price=1_000_000)
    higher_similarity = _option("b", "Khách sạn B", similarity=0.9, star_rating=4, review_score=8.0, lowest_price=1_000_000)

    ranked = rank_hotel_candidates([lower_similarity, higher_similarity])

    assert ranked[0][0]["id"] == "b"
    assert ranked[0][0]["rank"] == 1
    assert ranked[1][0]["id"] == "a"
    assert ranked[1][0]["rank"] == 2


def test_rank_hotel_candidates_secondary_factors_can_outweigh_a_moderate_similarity_gap():
    # A wins on similarity alone; B wins on rating + review + price simultaneously.
    # With weights 0.55/0.20/0.15/0.10, sweeping all three secondary axes can still
    # outweigh a moderate (not extreme) similarity gap — this pins that intentional behavior.
    similarity_edge = _option("a", "Khách sạn A", similarity=0.9, star_rating=2, lowest_price=2_000_000)
    all_around_better = _option(
        "b", "Khách sạn B", similarity=0.6, star_rating=5, review_score=9.5, lowest_price=1_000_000
    )

    ranked = rank_hotel_candidates([similarity_edge, all_around_better])

    assert ranked[0][0]["id"] == "b"


def test_rank_hotel_candidates_prefers_cheaper_when_otherwise_tied():
    cheap = _option("cheap", "Cheap Hotel", similarity=0.5, lowest_price=500_000)
    expensive = _option("pricey", "Pricey Hotel", similarity=0.5, lowest_price=5_000_000)

    ranked = rank_hotel_candidates([expensive, cheap])

    assert ranked[0][0]["id"] == "cheap"


def test_rank_hotel_candidates_missing_optional_fields_do_not_crash():
    bare = _option("bare", "Bare Hotel", similarity=0.4)

    ranked = rank_hotel_candidates([bare])

    assert ranked[0][0]["rank"] == 1
    assert ranked[0][0]["recommendation_score"] >= 0.0


def test_rank_hotel_candidates_assigns_sequential_rank():
    options = [_option("a", "A", similarity=0.3), _option("b", "B", similarity=0.8), _option("c", "C", similarity=0.5)]

    ranked = rank_hotel_candidates(options)

    assert [data["rank"] for data, _candidate in ranked] == [1, 2, 3]
    assert [data["id"] for data, _candidate in ranked] == ["b", "c", "a"]


# ---- resolve_hotel_selection ---------------------------------------------------------


def test_resolve_hotel_selection_empty_options_returns_none():
    assert resolve_hotel_selection("1", []) is None


def test_resolve_hotel_selection_by_rank_number():
    options = rank_hotel_candidates(
        [_option("a", "Khách sạn A", similarity=0.9), _option("b", "Khách sạn B", similarity=0.4)]
    )

    resolved = resolve_hotel_selection("1", options)

    assert resolved is not None
    assert resolved[0]["id"] == "a"


def test_resolve_hotel_selection_by_rank_out_of_range_returns_none():
    options = rank_hotel_candidates([_option("a", "A", similarity=0.9)])

    assert resolve_hotel_selection("99", options) is None


def test_resolve_hotel_selection_by_name_case_and_diacritic_insensitive():
    options = rank_hotel_candidates([_option("a", "Khách Sạn Biển Xanh", similarity=0.5)])

    resolved = resolve_hotel_selection("khach san bien xanh", options)

    assert resolved is not None
    assert resolved[0]["id"] == "a"


def test_resolve_hotel_selection_ambiguous_name_returns_none():
    options = rank_hotel_candidates(
        [_option("a", "Khách sạn Biển", similarity=0.5), _option("b", "Khách sạn Biển Đông", similarity=0.4)]
    )

    assert resolve_hotel_selection("bien", options) is None


def test_resolve_hotel_selection_no_match_returns_none():
    options = rank_hotel_candidates([_option("a", "Khách sạn A", similarity=0.5)])

    assert resolve_hotel_selection("khong ton tai o day", options) is None


# ---- select_hotel_candidates / fetch_hotel_by_id (mocked Supabase) -------------------


class _FakeQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def execute(self) -> "_FakeResult":
        return _FakeResult(self._rows)


class _FakeResult:
    def __init__(self, data: list[dict]) -> None:
        self.data = data


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def select(self, *_args, **_kwargs) -> "_FakeTable":
        return self

    def in_(self, _column: str, ids) -> _FakeQuery:
        id_set = {str(value) for value in ids}
        matched = [row for row in self._rows if str(row.get("id")) in id_set]
        return _FakeQuery(matched)


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def table(self, _name: str) -> _FakeTable:
        return _FakeTable(self._rows)


_CANONICAL_ROWS = [
    {
        "id": "hotel-1",
        "destination_id": "dest-1",
        "name": "Khách sạn Biển",
        "star_rating": 4,
        "description": "Gần biển",
        "coordinates": "16.05,108.2",
        "amenities": ["wifi", "pool"],
        "amenity_groups": {},
        "review_score": 8.5,
        "review_count": 120,
        "address": "123 Beach Rd",
        "area_name": "Downtown",
        "lowest_price": 1_500_000,
        "currency": "VND",
        "image_url": "http://example.com/x.jpg",
    },
    {
        "id": "hotel-2",
        "destination_id": "dest-2",
        "name": "Khách sạn Khác Điểm Đến",
        "coordinates": "10.0,106.0",
    },
]


def test_select_hotel_candidates_filters_destination_and_hydrates(monkeypatch):
    def fake_search_hotels_with_rooms(*, query, match_count, filter_destination_id):
        assert filter_destination_id == "dest-1"
        return [{"id": "hotel-1", "similarity": 0.77}, {"id": "hotel-2", "similarity": 0.5}]

    monkeypatch.setattr(hotel_selection_module, "search_hotels_with_rooms", fake_search_hotels_with_rooms)
    monkeypatch.setattr(
        hotel_selection_module, "_get_supabase_client", lambda: _FakeSupabaseClient(_CANONICAL_ROWS)
    )

    options = select_hotel_candidates("Đà Nẵng", "dest-1", "2 người")

    assert len(options) == 1
    data, candidate = options[0]
    assert data["id"] == "hotel-1"
    assert data["review_score"] == 8.5
    assert data["lowest_price"] == 1_500_000
    assert candidate.coordinate_pair is not None


def test_fetch_hotel_by_id_respects_destination_filter(monkeypatch):
    monkeypatch.setattr(
        hotel_selection_module, "_get_supabase_client", lambda: _FakeSupabaseClient(_CANONICAL_ROWS)
    )

    assert fetch_hotel_by_id("hotel-1", destination_id="dest-999") is None

    resolved = fetch_hotel_by_id("hotel-1", destination_id="dest-1")
    assert resolved is not None
    data, candidate = resolved
    assert data["id"] == "hotel-1"
    assert candidate.coordinate_pair is not None


def test_fetch_hotel_by_id_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr(hotel_selection_module, "_get_supabase_client", lambda: _FakeSupabaseClient([]))

    assert fetch_hotel_by_id("missing-hotel") is None
