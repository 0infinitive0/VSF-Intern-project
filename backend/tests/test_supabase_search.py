from __future__ import annotations

from pathlib import Path

import pytest

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


def test_hotel_search_amenity_payload_migration_returns_catalog_labels():
    migration = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrations"
        / "20260814_add_amenity_details_to_match_hotels_with_rooms.sql"
    ).read_text(encoding="utf-8")

    assert '"amenities" jsonb' in migration
    assert "jsonb_build_object" in migration
    assert "'label_vi'" in migration
    assert "'label_en'" in migration
    assert "WITH ORDINALITY" in migration


def test_database_schema_uses_shared_catalog_for_hotel_search_amenities():
    schema = (Path(__file__).resolve().parents[1] / "scripts" / "database_schema.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE amenity_catalog" in schema
    assert "CREATE TABLE hotel_amenity_catalog" not in schema
    assert '"amenities" jsonb' in schema.lower()
    assert "CREATE FUNCTION public.match_hotels_with_rooms" in schema
    assert schema.count("embedding vector(1024)") >= 2


def test_legacy_hotel_amenity_catalog_drop_migration_requires_a_complete_copy():
    migration = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrations"
        / "20260814_drop_legacy_hotel_amenity_catalog.sql"
    ).read_text(encoding="utf-8")

    assert "legacy rows are missing from public.amenity_catalog" in migration
    assert "DROP TABLE IF EXISTS public.hotel_amenity_catalog" in migration


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


def test_search_hotels_forwards_excluded_hotel_ids_as_rpc_param(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])
    excluded_ids = ["9a6c6e89-328f-4d49-b171-2f1beef7ea01", "d1227682-d9f3-42c1-8848-9bd592a7b781"]

    search_hotels_with_rooms(
        "Hotel in Đà Nẵng for 2 people",
        match_count=5,
        use_llm_filter=False,
        exclude_hotel_ids=excluded_ids,
    )

    assert client.captured_params is not None
    assert client.captured_params["filter_exclude_hotel_ids"] == excluded_ids


def test_search_hotels_falls_back_when_live_rpc_lacks_exclusion_parameter(monkeypatch):
    excluded_id = "9a6c6e89-328f-4d49-b171-2f1beef7ea01"
    fresh_id = "d1227682-d9f3-42c1-8848-9bd592a7b781"
    rpc_calls = []

    def fake_execute_rpc(_name, params):
        rpc_calls.append(params.copy())
        if len(rpc_calls) == 1:
            raise RuntimeError("PGRST202: missing filter_exclude_hotel_ids")
        return [{"id": excluded_id}, {"id": fresh_id}]

    _patch_client_and_embeddings(monkeypatch, data=[])
    monkeypatch.setattr(supabase_search_module, "_execute_rpc", fake_execute_rpc)

    results = search_hotels_with_rooms(
        "Hotel in Da Nang",
        match_count=1,
        use_llm_filter=False,
        exclude_hotel_ids=[excluded_id],
    )

    assert [hotel["id"] for hotel in results] == [fresh_id]
    assert rpc_calls[0]["filter_exclude_hotel_ids"] == [excluded_id]
    assert "filter_exclude_hotel_ids" not in rpc_calls[1]
    assert rpc_calls[1]["match_count"] == 2


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


def test_search_attractions_forwards_only_valid_excluded_ids(monkeypatch):
    client = _patch_client_and_embeddings(monkeypatch, data=[])
    excluded_id = "9a6c6e89-328f-4d49-b171-2f1beef7ea01"

    supabase_search_module.search_attractions(
        "museum",
        use_llm_filter=False,
        exclude_attraction_ids=[excluded_id, "not-a-uuid", excluded_id],
    )

    assert client.captured_params["filter_exclude_attraction_ids"] == [excluded_id]


def test_tiered_attraction_search_excludes_only_requested_scheduled_ids(monkeypatch):
    excluded_id = "9a6c6e89-328f-4d49-b171-2f1beef7ea01"
    retained_id = "d1227682-d9f3-42c1-8848-9bd592a7b781"
    calls = []
    monkeypatch.setattr(supabase_search_module, "get_embeddings", lambda: _FakeEmbeddings())

    def fake_execute_rpc(_name, params):
        calls.append(params.copy())
        return [{"id": excluded_id}, {"id": retained_id}]

    monkeypatch.setattr(supabase_search_module, "_execute_rpc", fake_execute_rpc)

    results = supabase_search_module.search_attractions_tiered(
        "museum culture",
        required_count=1,
        filter_destination_id="destination-id",
        root_latitude=16.0544,
        root_longitude=108.2022,
        exclude_attraction_ids=[excluded_id],
    )

    assert [result["id"] for result in results] == [retained_id]
    assert calls[0]["filter_exclude_attraction_ids"] == [excluded_id]


def test_attraction_search_falls_back_when_live_rpc_lacks_exclusion_parameter(monkeypatch):
    excluded_id = "9a6c6e89-328f-4d49-b171-2f1beef7ea01"
    retained_id = "d1227682-d9f3-42c1-8848-9bd592a7b781"
    rpc_calls = []

    def fake_execute_rpc(_name, params):
        rpc_calls.append(params.copy())
        if len(rpc_calls) == 1:
            raise RuntimeError("PGRST202: missing filter_exclude_attraction_ids")
        return [{"id": excluded_id}, {"id": retained_id}]

    _patch_client_and_embeddings(monkeypatch, data=[])
    monkeypatch.setattr(supabase_search_module, "_execute_rpc", fake_execute_rpc)

    results = supabase_search_module.search_attractions(
        "museum",
        match_count=1,
        use_llm_filter=False,
        exclude_attraction_ids=[excluded_id],
    )

    assert [attraction["id"] for attraction in results] == [retained_id]
    assert rpc_calls[0]["filter_exclude_attraction_ids"] == [excluded_id]
    assert "filter_exclude_attraction_ids" not in rpc_calls[1]
    assert rpc_calls[1]["match_count"] == 2


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


def test_tiered_attraction_search_reuses_one_embedding_and_stops_after_unique_results(monkeypatch):
    class CountingEmbeddings:
        def __init__(self):
            self.queries = []

        def embed_query(self, text):
            self.queries.append(text)
            return [0.25]

    calls = []
    responses = [
        [{"id": "first"}, {"id": "first"}],
        [{"id": "first"}, {"id": "second"}],
        [{"id": "third"}],
    ]

    def fake_execute_rpc(name, params):
        calls.append((name, params.copy()))
        return responses[len(calls) - 1]

    embeddings = CountingEmbeddings()
    monkeypatch.setattr(supabase_search_module, "get_embeddings", lambda: embeddings)
    monkeypatch.setattr(supabase_search_module, "_execute_rpc", fake_execute_rpc)

    results = supabase_search_module.search_attractions_tiered(
        "museum culture",
        required_count=2,
        filter_destination_id="destination-id",
        root_latitude=16.0544,
        root_longitude=108.2022,
    )

    assert embeddings.queries == ["museum culture"]
    assert [result["id"] for result in results] == ["first", "second"]
    assert [result["retrieval_tier"] for result in results] == [1, 2]
    assert [(params["max_radius_km"], params["match_threshold"]) for _, params in calls] == [
        (3.0, 0.4),
        (3.0, 0.25),
    ]
    assert all(name == "match_attractions" for name, _ in calls)
    assert all(params["filter_destination_id"] == "destination-id" for _, params in calls)
    assert all(params["root_latitude"] == 16.0544 for _, params in calls)
    assert all(params["root_longitude"] == 108.2022 for _, params in calls)


def test_tiered_attraction_search_does_not_expand_radius_when_first_tier_is_sufficient(monkeypatch):
    calls = []
    monkeypatch.setattr(supabase_search_module, "get_embeddings", lambda: _FakeEmbeddings())

    def fake_execute_rpc(_name, params):
        calls.append(params.copy())
        return [{"id": "first"}, {"id": "second"}]

    monkeypatch.setattr(supabase_search_module, "_execute_rpc", fake_execute_rpc)

    results = supabase_search_module.search_attractions_tiered(
        "local activities",
        required_count=2,
        filter_destination_id="destination-id",
        root_latitude=16.0544,
        root_longitude=108.2022,
    )

    assert [result["id"] for result in results] == ["first", "second"]
    assert len(calls) == 1
    assert calls[0]["max_radius_km"] == 3.0

