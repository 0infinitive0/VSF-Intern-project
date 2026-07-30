from __future__ import annotations

import src.services.hotel_selection as hotel_selection_module
from src.services.hotel_selection import (
    HotelPreferenceState,
    _parse_free_text_budget,
    fetch_hotel_by_id,
    hotel_matches_amenity_tag,
    lookup_sea_view_hotel_ids,
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


# ---- _parse_free_text_budget ----------------------------------------------------------


def test_parse_free_text_budget_million_phrasing():
    assert _parse_free_text_budget("4 triệu") == 4_000_000
    assert _parse_free_text_budget("khoảng 4tr thôi") == 4_000_000


def test_parse_free_text_budget_thousand_phrasing():
    assert _parse_free_text_budget("500 nghìn") == 500_000
    assert _parse_free_text_budget("500k") == 500_000


def test_parse_free_text_budget_qualitative_phrases():
    assert _parse_free_text_budget("tôi muốn khách sạn sang trọng") == 3_500_000
    assert _parse_free_text_budget("tiết kiệm thôi") == 500_000
    assert _parse_free_text_budget("tầm trung là được") == 1_500_000


def test_parse_free_text_budget_unrelated_text_returns_none():
    assert _parse_free_text_budget("trời hôm nay đẹp quá") is None


# ---- HotelPreferenceState ---------------------------------------------------------------


def test_hotel_preference_state_starts_pending_budget():
    state = HotelPreferenceState()

    assert state.stage == "pending_budget"
    assert not state.is_complete
    assert "1." in state.next_question()


def test_hotel_preference_state_rejects_unparseable_budget_and_reprompts():
    state = HotelPreferenceState()

    next_state = state.with_message("trời đẹp quá")

    assert next_state.stage == "pending_budget"
    assert next_state == state


def test_hotel_preference_state_accepts_free_text_price_without_reprompt():
    """The concrete case reported: the menu suggests 3 tiers but the user just
    types a custom amount — must resolve immediately, never re-ask."""
    state = HotelPreferenceState()

    next_state = state.with_message("4 triệu")

    assert next_state.is_complete
    assert next_state.target_price == 4_000_000


def test_hotel_preference_state_numbered_tier_pick():
    state = HotelPreferenceState()

    next_state = state.with_message("2")

    assert next_state.is_complete
    assert next_state.target_price == 1_500_000


def test_hotel_preference_state_skip_budget():
    state = HotelPreferenceState()

    next_state = state.with_message("4")

    assert next_state.is_complete
    assert next_state.target_price is None


def test_hotel_preference_state_full_walk_and_tool_arguments():
    state = HotelPreferenceState()
    state = state.with_message("4 triệu")

    assert state.is_complete
    assert state.tool_arguments() == {"target_price": "4000000.0"}


def test_hotel_preference_state_tool_arguments_raises_before_complete():
    state = HotelPreferenceState()

    try:
        state.tool_arguments()
    except ValueError:
        pass
    else:
        raise AssertionError("tool_arguments() should raise before is_complete")


# ---- hotel_matches_amenity_tag -----------------------------------------------------------


def test_hotel_matches_amenity_tag_non_smoking_requires_negation():
    smoking_area_only = {"amenities": ["Khu vực hút thuốc"]}
    non_smoking = {"amenities": ["Phòng không hút thuốc"]}

    assert hotel_matches_amenity_tag(smoking_area_only, "non_smoking") is False
    assert hotel_matches_amenity_tag(non_smoking, "non_smoking") is True


def test_hotel_matches_amenity_tag_pool_and_family():
    assert hotel_matches_amenity_tag({"amenities": ["Hồ bơi ngoài trời"]}, "pool") is True
    assert hotel_matches_amenity_tag({"amenities": ["Phòng gia đình"]}, "family") is True
    assert hotel_matches_amenity_tag({"amenities": ["Wifi"]}, "pool") is False


def test_hotel_matches_amenity_tag_breakfast_reads_covered_meals_not_amenities():
    # amenities text mentions breakfast-like words, but covered_meals doesn't list it —
    # must NOT independently re-derive from amenities text.
    data = {"amenities": ["Nhà hàng phục vụ bữa sáng"], "covered_meals": []}
    assert hotel_matches_amenity_tag(data, "breakfast") is False

    data_covered = {"amenities": [], "covered_meals": ["breakfast"]}
    assert hotel_matches_amenity_tag(data_covered, "breakfast") is True


def test_hotel_matches_amenity_tag_sea_view_uses_only_the_passed_id_set():
    data = {"id": "hotel-1", "amenities": ["Nhìn ra biển tuyệt đẹp"]}

    # amenities text mentions "biển" but id isn't in the resolved set -> no match
    assert hotel_matches_amenity_tag(data, "sea_view", frozenset()) is False
    assert hotel_matches_amenity_tag(data, "sea_view", frozenset({"hotel-1"})) is True


def test_hotel_matches_amenity_tag_missing_data_and_unknown_tag_return_false():
    assert hotel_matches_amenity_tag({}, "pool") is False
    assert hotel_matches_amenity_tag({"amenities": ["Hồ bơi"]}, "not_a_real_tag") is False


# ---- lookup_sea_view_hotel_ids (mocked Supabase, reusing the existing fake) --------------


def test_lookup_sea_view_hotel_ids_empty_input_skips_query(monkeypatch):
    called = []
    monkeypatch.setattr(
        hotel_selection_module,
        "_get_supabase_client",
        lambda: called.append(True) or _FakeSupabaseClient([]),
    )

    assert lookup_sea_view_hotel_ids([]) == frozenset()
    assert called == []


def test_lookup_sea_view_hotel_ids_matches_case_and_diacritic_insensitive(monkeypatch):
    room_rows = [
        {"id": "hotel-1", "hotel_id": "hotel-1", "view": "Nhìn ra biển"},
        {"id": "hotel-2", "hotel_id": "hotel-2", "view": "Nhìn ra thành phố"},
        {"id": "hotel-3", "hotel_id": "hotel-3", "view": "Nhìn ra vườn, Nhìn ra biển"},
    ]
    monkeypatch.setattr(
        hotel_selection_module, "_get_supabase_client", lambda: _FakeSupabaseClient(room_rows)
    )

    result = lookup_sea_view_hotel_ids(["hotel-1", "hotel-2", "hotel-3"])

    assert result == frozenset({"hotel-1", "hotel-3"})


def test_lookup_sea_view_hotel_ids_fails_open_on_error(monkeypatch):
    def _raise():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(hotel_selection_module, "_get_supabase_client", _raise)

    assert lookup_sea_view_hotel_ids(["hotel-1"]) == frozenset()


# ---- rank_hotel_candidates: preference bonuses and backward compatibility ---------------


def test_rank_hotel_candidates_no_preferences_matches_no_kwargs_call():
    options = [_option("a", "A", similarity=0.3), _option("b", "B", similarity=0.8)]

    ranked_no_kwargs = rank_hotel_candidates(list(options))
    ranked_default_kwargs = rank_hotel_candidates(
        list(options), target_price=None, amenity_prefs=(), sea_view_hotel_ids=frozenset()
    )

    ids_no_kwargs = [data["id"] for data, _c in ranked_no_kwargs]
    ids_default_kwargs = [data["id"] for data, _c in ranked_default_kwargs]
    assert ids_no_kwargs == ids_default_kwargs == ["b", "a"]


def test_rank_hotel_candidates_budget_bonus_flips_a_near_tie():
    # B's much higher similarity (0.75 vs 0.50) wins the baseline despite A's cheaper
    # price already earning A the max relative price_score in this 2-hotel batch —
    # isolates the NEW target_price-closeness bonus from the pre-existing relative
    # price_score term, which is already baked into the baseline for both calls.
    cheap = _option("a", "A", similarity=0.50, lowest_price=1_000_000)
    pricier_better_match = _option("b", "B", similarity=0.75, lowest_price=5_000_000)

    baseline = rank_hotel_candidates([cheap, pricier_better_match])
    assert baseline[0][0]["id"] == "b"

    boosted = rank_hotel_candidates([cheap, pricier_better_match], target_price=1_000_000)
    assert boosted[0][0]["id"] == "a"


def test_rank_hotel_candidates_amenity_bonus_flips_a_near_tie():
    matches_amenity = _option("a", "A", similarity=0.55)
    matches_amenity[0]["amenities"] = ["Phòng không hút thuốc"]
    no_match = _option("b", "B", similarity=0.58)
    no_match[0]["amenities"] = []

    baseline = rank_hotel_candidates([matches_amenity, no_match])
    assert baseline[0][0]["id"] == "b"

    boosted = rank_hotel_candidates([matches_amenity, no_match], amenity_prefs=("non_smoking",))
    assert boosted[0][0]["id"] == "a"


def test_rank_hotel_candidates_never_penalizes_missing_data():
    bare = _option("bare", "Bare Hotel", similarity=0.5)

    ranked = rank_hotel_candidates(
        [bare],
        target_price=1_000_000,
        amenity_prefs=("sea_view", "non_smoking", "pool", "breakfast", "family"),
    )

    data, _candidate = ranked[0]
    assert data["recommendation_score"] == 0.55 * 0.5  # only the similarity term contributes


def test_rank_hotel_candidates_amenity_bonus_scales_with_match_count():
    two_tags = _option("two", "Two", similarity=0.5)
    two_tags[0]["amenities"] = ["Hồ bơi", "Phòng gia đình"]
    zero_tags = _option("zero", "Zero", similarity=0.5)
    zero_tags[0]["amenities"] = []

    ranked = rank_hotel_candidates(
        [two_tags, zero_tags], amenity_prefs=("pool", "family")
    )
    scores = {data["id"]: data["recommendation_score"] for data, _c in ranked}

    assert round(scores["two"] - scores["zero"], 6) == round(2 * 0.03, 6)
