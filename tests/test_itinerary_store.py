from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import (
    ItineraryStore,
    ItineraryStoreError,
    push_current_trip_plan_to_supabase,
)


class Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class Query:
    def __init__(self, result: Any) -> None:
        self.result = result

    def select(self, *_: object) -> Query:
        return self

    def eq(self, *_: object) -> Query:
        return self

    def order(self, *_: object, **__: object) -> Query:
        return self

    def update(self, *_: object) -> Query:
        return self

    def execute(self) -> Result:
        return Result(self.result)


class FakeSupabase:
    def __init__(self) -> None:
        self.rpc_calls: list[tuple[str, dict[str, object]]] = []
        self.tables: dict[str, Any] = {
            "itineraries": {
                "id": "template-1",
                "destination_id": "destination-1",
                "hotel_id": "hotel-1",
                "duration_days": 1,
                "number_of_adults": 2,
                "number_of_children": 0,
                "day_themes": [{"day_number": 1, "title": "Culture", "query": "culture"}],
                "status": "Finalized",
            },
            "itinerary_items": [
                {
                    "day_number": 1,
                    "order_index": index,
                    "reference_type": "Hotel" if index == 4 else "Attraction",
                    "reference_id": f"place-{index}",
                    "item_kind": "rest" if index == 4 else "attraction",
                }
                for index in range(1, 8)
            ],
            "hotels": {"id": "hotel-1", "coordinates": "16.05,108.2"},
        }

    def rpc(self, name: str, params: dict[str, object]) -> Query:
        self.rpc_calls.append((name, params))
        if name == "match_itineraries":
            return Query([
                {
                    **self.tables["itineraries"],
                    "id": "template-1",
                    "similarity": 0.94,
                }
            ])
        if name == "persist_itinerary_bundle":
            itinerary = params.get("p_itinerary") or {}
            return Query(itinerary.get("id"))
        return Query({"status": "success"})

    def table(self, name: str) -> Query:
        return Query(self.tables[name])


def query() -> ItineraryReuseQuery:
    return ItineraryReuseQuery("destination-1", "Đà Nẵng", 1, 2)


def test_search_passes_hard_filters_and_maps_templates() -> None:
    client = FakeSupabase()
    store = ItineraryStore(client, lambda _: [0.1] * 1024)

    templates = store.search_reusable_itineraries(query(), threshold=0.88)

    assert templates[0].id == "template-1"
    rpc_name, params = client.rpc_calls[0]
    assert rpc_name == "match_itineraries"
    assert params["filter_destination_id"] == "destination-1"
    assert params["filter_duration_days"] == 1
    assert "filter_embedding_version" not in params
    assert len(params["query_embedding"]) == 1024


def test_search_rejects_wrong_embedding_dimension() -> None:
    store = ItineraryStore(FakeSupabase(), lambda _: [0.1] * 3)

    try:
        store.search_reusable_itineraries(query(), threshold=0.88)
    except ItineraryStoreError as exc:
        assert "1024" in str(exc)
    else:
        raise AssertionError("wrong dimension must not call the itinerary search RPC")


def test_persist_replaces_bundle_with_item_kind_contract() -> None:
    client = FakeSupabase()
    store = ItineraryStore(client, lambda _: [0.1] * 1024)
    trip_data = {
        "hotel": {"id": "hotel-1", "destination_id": "destination-1"},
        "itineraries": [{"id": "draft-1", "duration_days": 1, "day_themes": []}],
        "itinerary_items": [{"id": "item-1", "kind": "coffee", "reference_id": "place-1"}],
    }

    store.persist_itinerary_bundle(trip_data)

    rpc_name, params = client.rpc_calls[0]
    assert rpc_name == "persist_itinerary_bundle"
    assert params["p_itinerary"]["destination_id"] == "destination-1"
    assert params["p_itinerary"]["hotel_id"] == "hotel-1"
    assert params["p_items"][0]["item_kind"] == "coffee"


def test_push_current_trip_plan_file_persists_the_complete_bundle() -> None:
    client = FakeSupabase()
    store = ItineraryStore(client, lambda _: [0.1] * 1024)
    trip_data = {
        "hotel": {"id": "hotel-1", "destination_id": "destination-1"},
        "itineraries": [{"id": "draft-1", "duration_days": 1, "day_themes": []}],
        "itinerary_items": [
            {"id": "item-1", "kind": "breakfast", "reference_id": "hotel-1"},
            {"id": "item-2", "kind": "attraction", "reference_id": "place-1"},
        ],
    }

    with TemporaryDirectory() as directory:
        plan_path = Path(directory) / "current_trip_plan.json"
        plan_path.write_text(json.dumps(trip_data), encoding="utf-8")
        itinerary_id = push_current_trip_plan_to_supabase(plan_path, store=store)

    assert itinerary_id == "draft-1"
    rpc_name, params = client.rpc_calls[0]
    assert rpc_name == "persist_itinerary_bundle"
    assert len(params["p_items"]) == 2
    assert params["p_items"][0]["item_kind"] == "breakfast"


def test_push_current_trip_plan_file_reports_invalid_json() -> None:
    with TemporaryDirectory() as directory:
        plan_path = Path(directory) / "current_trip_plan.json"
        plan_path.write_text("{not-json", encoding="utf-8")

        try:
            push_current_trip_plan_to_supabase(
                plan_path,
                store=ItineraryStore(FakeSupabase(), lambda _: [0.1] * 1024),
            )
        except ItineraryStoreError as exc:
            assert "valid JSON" in str(exc)
        else:
            raise AssertionError("invalid current_trip_plan.json must be rejected")


def test_persistence_migration_uses_builtin_uuid_generation() -> None:
    migration = (
        Path(__file__).parents[1] / "scripts/migrations/20260728_add_itinerary_reuse.sql"
    ).read_text(encoding="utf-8")

    assert "gen_random_uuid()" in migration
    assert "uuid_generate_v4()" not in migration


def test_load_bundle_keeps_hotel_and_all_item_rows() -> None:
    store = ItineraryStore(FakeSupabase(), lambda _: [0.1] * 1024)

    bundle = store.load_itinerary_bundle("template-1")

    assert bundle is not None
    assert bundle.hotel["id"] == "hotel-1"
    assert len(bundle.template.items) == 7


def test_finalization_saves_embedding_after_the_atomic_status_transition() -> None:
    client = FakeSupabase()
    store = ItineraryStore(client, lambda _: [0.1] * 1024)
    trip_data = {
        "hotel": {"id": "hotel-1", "destination_id": "destination-1"},
        "itineraries": [{"id": "draft-1", "duration_days": 1, "day_themes": []}],
        "itinerary_items": [{"kind": "rest", "reference_id": "hotel-1"}],
    }

    result = store.finalize_trip_data(trip_data, query())

    assert result["embedding_saved"]
    finalize_name, finalize_params = client.rpc_calls[0]
    assert finalize_name == "finalize_itinerary"
    assert set(finalize_params) == {"p_itinerary_id", "p_summary"}
    assert client.rpc_calls[1][0] == "update_itinerary_embedding"


def test_embedding_refresh_marks_a_finalized_template_ready() -> None:
    client = FakeSupabase()
    store = ItineraryStore(client, lambda _: [0.1] * 1024)

    store.refresh_embedding("template-1", "stable itinerary summary")

    assert client.rpc_calls[0][0] == "update_itinerary_embedding"
