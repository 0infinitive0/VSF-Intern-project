from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.api.routes as routes
import src.services.place_details as place_details
from src.models.schemas import HotelDetailPayload


class FakeQuery:
    """Ignores every filter for `execute()`'s canned response (as before)
    -- but now records the calls made against each table so a test can
    assert what filtering the real code actually asked for, not just what
    data it returned. Needed to catch the class of bug where a query-level
    `.eq("sold_out", False)` strips a row before it ever reaches Python's
    own (correct) freshest-row-then-sold_out logic -- a fake that silently
    ignores filters can't tell the two apart otherwise."""

    def __init__(self, client, table):
        self.client, self.table = client, table

    def _record(self, method, *args):
        self.client.calls.setdefault(self.table, []).append((method, args))
        return self

    def select(self, *args):
        return self._record("select", *args)

    def eq(self, *args):
        return self._record("eq", *args)

    def gte(self, *args):
        return self._record("gte", *args)

    def lt(self, *args):
        return self._record("lt", *args)

    def in_(self, *args):
        return self._record("in_", *args)

    def limit(self, *args):
        return self._record("limit", *args)

    def execute(self):
        self.client.queries.append(self.table)
        result = self.client.responses[self.table]
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(data=result)


class FakeClient:
    def __init__(self, responses):
        self.responses, self.queries = responses, []
        self.rpc_calls: list[tuple[str, dict]] = []
        self.calls: dict[str, list[tuple[str, tuple]]] = {}

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self.responses["rpc"][params["p_room_id"]]))


def _hotel():
    return {"id": "hotel-1", "name": "Real Hotel", "lowest_price": 999999}


def _room():
    return {"id": "room-1", "name": "Ocean Room", "images": []}


def test_hotel_detail_selects_matching_room_price_and_never_uses_hotel_lowest_price(monkeypatch):
    client = FakeClient({
        "hotels": [_hotel()], "rooms": [_room()],
        "room_prices": [
            # Stale sold_out snapshot from an earlier crawl -- superseded by
            # the fresher, available snapshot below (freshest-by-crawled_at
            # wins regardless of which one is sold_out; see _average_price's
            # docstring). The freshest row (2026-08-02) is the one that
            # decides both price AND availability for the night.
            {"room_id": "room-1", "price": 1, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": True, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1250000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": False, "crawled_at": "2026-08-02T00:00:00"},
        ],
        "rpc": {"room-1": 9},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 3))

    assert client.queries == ["hotels", "rooms", "room_prices"]
    assert result["rooms"][0]["price"]["amount"] == 1250000
    assert result["rooms"][0]["price"]["package_details"] is None


def test_hotel_detail_freshest_sold_out_row_hides_price_even_with_older_available_row(monkeypatch):
    """Regression for phase-11's code review finding: sold_out must be
    checked on the FRESHEST row per night, not filtered out before picking
    the freshest -- otherwise an admin's newer sold_out=True write (or a
    genuine OTA recrawl reporting the room now sold out) loses to a stale
    older row that still says available, and the guest sees a price for a
    night that is not actually bookable."""
    client = FakeClient({
        "hotels": [_hotel()], "rooms": [_room()],
        "room_prices": [
            {"room_id": "room-1", "price": 1250000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": True, "crawled_at": "2026-08-02T00:00:00"},
        ],
        "rpc": {"room-1": 9},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 3))

    assert result["rooms"][0]["price"] is None  # "price on request", not the stale 1,250,000
    # The room_prices query itself must not filter sold_out at the DB level
    # -- that would strip the sold_out=True row before _average_price ever
    # saw it, silently reintroducing this exact bug regardless of the fix
    # inside _average_price.
    assert ("eq", ("sold_out", False)) not in client.calls.get("room_prices", [])


def test_hotel_detail_averages_room_price_across_every_night_of_the_stay(monkeypatch):
    """`room_prices` is one row per crawled NIGHT -- a 3-night stay averages
    that room's 3 per-night snapshots, not a single row lookup."""
    client = FakeClient({
        "hotels": [_hotel()], "rooms": [_room()],
        "room_prices": [
            {"room_id": "room-1", "price": 1000000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1200000, "currency": "VND", "check_in_date": "2026-09-02", "check_out_date": "2026-09-03", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1400000, "currency": "VND", "check_in_date": "2026-09-03", "check_out_date": "2026-09-04", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
        ],
        "rpc": {"room-1": 9},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 4))

    assert result["rooms"][0]["price"]["amount"] == 1200000


def test_hotel_detail_price_average_ignores_sold_out_nights_and_re_crawls(monkeypatch):
    """A sold-out night contributes nothing to the average (never averaged in
    as if it had a real price), and a night crawled twice counts once, using
    only its freshest snapshot."""
    client = FakeClient({
        "hotels": [_hotel()], "rooms": [_room()],
        "room_prices": [
            # Night 1: crawled twice -- the stale 900000 must be ignored.
            {"room_id": "room-1", "price": 900000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": False, "crawled_at": "2026-08-01T00:00:00"},
            {"room_id": "room-1", "price": 1000000, "currency": "VND", "check_in_date": "2026-09-01", "check_out_date": "2026-09-02", "sold_out": False, "crawled_at": "2026-08-02T00:00:00"},
            # Night 2: sold out -- excluded from the average entirely.
            {"room_id": "room-1", "price": 5000000, "currency": "VND", "check_in_date": "2026-09-02", "check_out_date": "2026-09-03", "sold_out": True, "crawled_at": "2026-08-01T00:00:00"},
        ],
        "rpc": {"room-1": 9},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 3))

    assert result["rooms"][0]["price"]["amount"] == 1000000


def test_hotel_detail_returns_booking_aware_room_inventory_for_the_requested_stay(monkeypatch):
    client = FakeClient({
        "hotels": [_hotel()],
        "rooms": [{**_room(), "available_room_count": 9}],
        "room_prices": [],
        "rpc": {"room-1": 3},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1", date(2026, 9, 1), date(2026, 9, 3))

    assert result["available_room_count"] == 3
    assert result["rooms"][0]["available_room_count"] == 3
    assert client.rpc_calls == [(
        "get_room_availability",
        {
            "p_room_id": "room-1",
            "p_check_in_date": "2026-09-01",
            "p_check_out_date": "2026-09-03",
        },
    )]


def test_hotel_detail_handles_no_rooms_and_no_matching_price(monkeypatch):
    no_rooms = FakeClient({"hotels": [_hotel()], "rooms": [], "room_prices": [], "rpc": {}})
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: no_rooms)
    assert place_details.get_hotel_detail("hotel-1")["rooms"] == []
    assert no_rooms.queries == ["hotels", "rooms"]

    no_price = FakeClient({"hotels": [_hotel()], "rooms": [_room()], "room_prices": [], "rpc": {"room-1": 9}})
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: no_price)
    assert place_details.get_hotel_detail("hotel-1")["rooms"][0]["price"] is None


def test_hotel_detail_joins_unique_room_amenities_from_the_catalog(monkeypatch):
    from src.services.amenity_catalog import AmenityCatalogEntry

    client = FakeClient({
        "hotels": [_hotel()],
        "rooms": [
            {**_room(), "room_facilities": ["tv", "wifi", "unknown_facility"]},
            {"id": "room-2", "name": "City Room", "room_facilities": ["hair_dryer", "tv"]},
        ],
        "room_prices": [],
        "rpc": {"room-1": 2, "room-2": 1},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)
    monkeypatch.setattr(
        place_details,
        "query_all_approved_amenities_by_ids",
        lambda amenity_ids: [
            AmenityCatalogEntry("tv", "Tivi", ("tv",), label_en="TV", scope="room", category="room_comfort"),
            AmenityCatalogEntry("wifi", "Wi-Fi", ("wifi",), label_en="Wi-Fi", scope="both", category="connectivity"),
            AmenityCatalogEntry("hair_dryer", "Máy sấy tóc", ("hair dryer",), label_en="Hair dryer", scope="room", category="room_comfort"),
        ],
        raising=False,
    )

    result = place_details.get_hotel_detail("hotel-1")

    assert result["room_amenities"] == [
        {"id": "tv", "label_vi": "Tivi", "label_en": "TV", "category": "room_comfort", "icon_key": None},
        {"id": "wifi", "label_vi": "Wi-Fi", "label_en": "Wi-Fi", "category": "connectivity", "icon_key": None},
        {"id": "hair_dryer", "label_vi": "Máy sấy tóc", "label_en": "Hair dryer", "category": "room_comfort", "icon_key": None},
    ]
    assert HotelDetailPayload.model_validate(result).room_amenities[0].id == "tv"


def test_agoda_nearby_attraction_strings_are_normalized_without_coordinates(monkeypatch):
    client = FakeClient({
        "hotels": [{
            **_hotel(),
            "source_platform": "agoda",
            "nearby_attractions": [
                "Dinh Độc Lập - Cách nơi ở 990 m",
                "UBND Thành phố Hồ Chí Minh - cách nơi ở 1.04 km",
            ],
        }],
        "rooms": [],
        "room_prices": [],
        "rpc": {},
    })
    monkeypatch.setattr(place_details, "_get_supabase_client", lambda: client)

    result = place_details.get_hotel_detail("hotel-1")

    assert result["nearby_attractions"] == [
        {
            "name": "Dinh Độc Lập",
            "distance_km": 0.99,
            "distance_text": "Cách nơi ở 990 m",
            "coordinates": None,
        },
        {
            "name": "UBND Thành phố Hồ Chí Minh",
            "distance_km": 1.04,
            "distance_text": "cách nơi ở 1.04 km",
            "coordinates": None,
        },
    ]
    assert HotelDetailPayload.model_validate(result).nearby_attractions[0].coordinates is None


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
async def test_hotel_amenity_catalog_route_returns_all_approved_entries(client, monkeypatch):
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
        },
        {
            "id": "tv",
            "label_vi": "TV",
            "label_en": "TV",
            "category": "room_comfort",
            "icon_key": None,
        },
    ]
