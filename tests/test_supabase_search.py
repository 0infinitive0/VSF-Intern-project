from __future__ import annotations

import src.services.supabase_search as supabase_search_module
from src.services.supabase_search import search_hotels_with_rooms


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeSupabaseClient:
    """Captures the RPC call params so tests can assert on what was actually requested
    without a real Supabase connection."""

    def __init__(self, data):
        self._data = data
        self.captured_params: dict | None = None

    def rpc(self, name, params):
        self.captured_params = params
        return self

    def execute(self):
        return _FakeResponse(self._data)


class _FakeEmbeddings:
    def embed_query(self, text):
        return [0.0]


def _patch_client_and_embeddings(monkeypatch, data):
    client = _FakeSupabaseClient(data)
    monkeypatch.setattr(supabase_search_module, "get_supabase_client", lambda: client)
    monkeypatch.setattr(supabase_search_module, "get_embeddings", lambda: _FakeEmbeddings())
    return client


def test_search_hotels_forwards_min_and_max_price_as_rpc_params(monkeypatch):
    """min_price/max_price must reach match_hotels_with_rooms as filter_min_price/
    filter_max_price RPC params — the RPC filters by lowest_price directly in SQL (see
    scripts/migrations/20260730_add_price_filter_to_match_hotels_with_rooms.sql), so the
    returned rows are already in range; no client-side price filtering happens here."""
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    search_hotels_with_rooms(
        "Hotel in Đà Nẵng for 2 người people",
        match_count=5,
        use_llm_filter=False,
        min_price=800_000,
        max_price=2_500_000,
    )

    assert client.captured_params is not None
    assert client.captured_params["filter_min_price"] == 800_000
    assert client.captured_params["filter_max_price"] == 2_500_000
    assert client.captured_params["match_count"] == 5


def test_search_hotels_omits_price_params_when_not_given(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    search_hotels_with_rooms(
        "Hotel in Đà Nẵng for 2 người people",
        match_count=5,
        use_llm_filter=False,
    )

    assert client.captured_params is not None
    assert "filter_min_price" not in client.captured_params
    assert "filter_max_price" not in client.captured_params


def test_search_hotels_forwards_complete_stay_dates_as_rpc_params(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    search_hotels_with_rooms(
        "Hotel in Đà Nẵng for 2 people",
        match_count=5,
        use_llm_filter=False,
        start_date="2026-08-10",
        end_date="2026-08-12",
    )

    assert client.captured_params is not None
    assert client.captured_params["filter_start_date"] == "2026-08-10"
    assert client.captured_params["filter_end_date"] == "2026-08-12"


def test_search_hotels_rejects_incomplete_or_non_positive_stay_dates(monkeypatch):
    _patch_client_and_embeddings(monkeypatch, data=[])

    with pytest.raises(ValueError, match="stay_dates_must_be_provided_together"):
        search_hotels_with_rooms("Hotel", use_llm_filter=False, start_date="2026-08-10")

    with pytest.raises(ValueError, match="end_date_must_be_after_start_date"):
        search_hotels_with_rooms(
            "Hotel", use_llm_filter=False, start_date="2026-08-10", end_date="2026-08-10"
        )


def test_search_hotels_returns_rpc_rows_as_is_when_no_star_filter(monkeypatch):
    """Price is enforced by the RPC itself now, so with no star_rating filter active,
    search_hotels_with_rooms should return exactly what the RPC gave back — no
    client-side re-filtering or oversampling."""
    data = [
        {"id": "a", "lowest_price": 200_000},
        {"id": "b", "lowest_price": 8_000_000},
    ]
    _patch_client_and_embeddings(monkeypatch, data)

    results = search_hotels_with_rooms(
        "Hotel in Đà Nẵng for 2 người people",
        match_count=5,
        use_llm_filter=False,
        min_price=800_000,
        max_price=2_500_000,
    )

    assert [r["id"] for r in results] == ["a", "b"]


def test_search_hotels_still_filters_by_star_rating(monkeypatch):
    """star_rating is still checked client-side (the RPC doesn't accept it), with a
    modest oversample just for that filter."""
    data = [
        {"id": "low", "star_rating": 2},
        {"id": "high", "star_rating": 5},
    ]
    client = _patch_client_and_embeddings(monkeypatch, data)

    filters_result = {"min_star_rating": 4, "clean_query": "Hotel in Đà Nẵng for 2 người people"}
    monkeypatch.setattr(supabase_search_module, "extract_search_filters", lambda *a, **k: filters_result)

    results = search_hotels_with_rooms(
        "khách sạn 4 sao ở Đà Nẵng",
        match_count=5,
        use_llm_filter=True,
    )

    assert [r["id"] for r in results] == ["high"]
    assert client.captured_params["match_count"] == 15


import pytest


def test_search_hotels_forwards_radius_params(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    search_hotels_with_rooms(
        "Hotel in Đà Nẵng",
        match_count=5,
        use_llm_filter=False,
        root_latitude=10.7758,
        root_longitude=106.7009,
        max_radius_km=5.0,
    )

    assert client.captured_params is not None
    assert client.captured_params["root_latitude"] == 10.7758
    assert client.captured_params["root_longitude"] == 106.7009
    assert client.captured_params["max_radius_km"] == 5.0


def test_search_attractions_forwards_radius_params(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    supabase_search_module.search_attractions(
        "Biển đẹp",
        match_count=5,
        use_llm_filter=False,
        root_latitude=10.7758,
        root_longitude=106.7009,
        max_radius_km=5.0,
    )

    assert client.captured_params is not None
    assert client.captured_params["root_latitude"] == 10.7758
    assert client.captured_params["root_longitude"] == 106.7009
    assert client.captured_params["max_radius_km"] == 5.0


def test_search_omits_radius_params_when_none(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])

    supabase_search_module.search_attractions(
        "Biển đẹp",
        match_count=5,
        use_llm_filter=False,
    )

    assert client.captured_params is not None
    assert "root_latitude" not in client.captured_params
    assert "root_longitude" not in client.captured_params
    assert "max_radius_km" not in client.captured_params


def test_radius_filter_validation_errors():
    with pytest.raises(ValueError, match="radius_filter_requires_latitude_longitude_and_radius"):
        supabase_search_module.validate_radius_filter(root_latitude=10.0, root_longitude=106.0)

    with pytest.raises(ValueError, match="invalid_parameter_type_for_radius_filter"):
        supabase_search_module.validate_radius_filter(root_latitude=True, root_longitude=106.0, max_radius_km=5.0)

    with pytest.raises(ValueError, match="root_latitude_out_of_range"):
        supabase_search_module.validate_radius_filter(root_latitude=95.0, root_longitude=106.0, max_radius_km=5.0)

    with pytest.raises(ValueError, match="root_longitude_out_of_range"):
        supabase_search_module.validate_radius_filter(root_latitude=10.0, root_longitude=190.0, max_radius_km=5.0)

    with pytest.raises(ValueError, match="max_radius_km_must_be_finite_and_non_negative"):
        supabase_search_module.validate_radius_filter(root_latitude=10.0, root_longitude=106.0, max_radius_km=-2.0)

    with pytest.raises(ValueError, match="radius_filter_parameters_must_be_finite"):
        supabase_search_module.validate_radius_filter(root_latitude=float("nan"), root_longitude=106.0, max_radius_km=5.0)

