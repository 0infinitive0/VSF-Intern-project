from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.api.routes as routes
import src.services.place_details as place_details


class FakeQuery:
    def __init__(self, client, table):
        self.client, self.table = client, table

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        self.client.queries.append(self.table)
        result = self.client.responses[self.table]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(data=result)


class FakeClient:
    def __init__(self, responses):
        self.responses, self.queries = responses, []

    def table(self, name):
        return FakeQuery(self, name)


def _hotel():
    return {"id": "hotel-1", "name": "Real Hotel", "lowest_price": 999999}


def _room():
    return {"id": "room-1", "name": "Ocean Room", "images": []}


def test_hotel_detail_selects_matching_room_price_and_never_uses_hotel_lowest_price(monkeypatch):
    client = FakeClient({
        "hotels": [_hotel()], "rooms": [_room()],
        "room_prices": [
            {"room_id": "room-1", "price": 1250000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-03", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-03", "sold_out": True, "crawled_at": "2026-08-02T00:00:00"},
        ],
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 3))

    assert client.queries == ["hotels", "rooms", "room_prices"]
    assert result["rooms"][0]["price"]["amount"] == 1250000
    assert result["rooms"][0]["price"]["package_details"] is None


def test_hotel_detail_handles_no_rooms_and_no_matching_price(monkeypatch):
    no_rooms = FakeClient({"hotels": [_hotel()], "rooms": [], "room_prices": []})
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: no_rooms)
    assert place_details.get_hotel_detail("hotel-1")["rooms"] == []
    assert no_rooms.queries == ["hotels", "rooms"]

    no_price = FakeClient({"hotels": [_hotel()], "rooms": [_room()], "room_prices": []})
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: no_price)
    assert place_details.get_hotel_detail("hotel-1")["rooms"][0]["price"] is None


@pytest.mark.asyncio
async def test_detail_routes_found_not_found_invalid_id_and_service_error(client, monkeypatch):
    hotel_id, attraction_id = uuid4(), uuid4()
    monkeypatch.setattr(routes, "get_hotel_detail", lambda *_: {"id": str(hotel_id), "name": "Real Hotel", "rooms": []})
    monkeypatch.setattr(routes, "get_attraction_detail", lambda *_: {"id": str(attraction_id), "name": "Free museum", "ticket_price_adult": 0, "ticket_price_child": None})
    assert (await client.get(f"/api/v1/hotels/{hotel_id}")).json()["name"] == "Real Hotel"
    attraction = await client.get(f"/api/v1/attractions/{attraction_id}")
    assert attraction.json()["ticket_price_adult"] == 0
    assert attraction.json()["ticket_price_child"] is None
    assert (await client.get("/api/v1/hotels/not-a-uuid")).status_code == 422
    assert (await client.get("/api/v1/attractions/not-a-uuid")).status_code == 422

    monkeypatch.setattr(routes, "get_hotel_detail", lambda *_: None)
    monkeypatch.setattr(routes, "get_attraction_detail", lambda *_: None)
    assert (await client.get(f"/api/v1/hotels/{hotel_id}")).status_code == 404
    assert (await client.get(f"/api/v1/attractions/{attraction_id}")).status_code == 404

    def database_failure(*_):
        raise RuntimeError("database is unavailable")

    monkeypatch.setattr(routes, "get_hotel_detail", database_failure)
    assert (await client.get(f"/api/v1/hotels/{hotel_id}")).status_code == 500


@pytest.mark.asyncio
async def test_hotel_amenity_catalog_route_returns_only_approved_hotel_entries(client, monkeypatch):
    from src.services.amenity_catalog import AmenityCatalogEntry

    monkeypatch.setattr(
        routes,
        "query_approved_amenities",
        lambda: [
            AmenityCatalogEntry("wifi", "Wi-Fi", ("wifi",), label_en="Wi-Fi", scope="hotel", category="connectivity", icon_key="wifi"),
            AmenityCatalogEntry("tv", "TV", ("tv",), label_en="TV", scope="room", category="room_comfort"),
        ],
    )

    response = await client.get("/api/v1/hotel-amenities")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "wifi",
            "label_vi": "Wi-Fi",
            "label_en": "Wi-Fi",
            "category": "connectivity",
            "icon_key": "wifi",
        }
    ]
