"""Tests for admin B1 (Danh sách khách sạn) -- src/api/admin/hotels.py.

Uses a generic in-memory fake for the postgrest-style `.table(...).eq(...)
.execute()` chain (extends the recording-fake pattern already used by
tests/test_booking_service.py) since three tables are queried across these
endpoints (admin_hotel_rows, rooms, bookings, hotels) and the blocking-
booking check joins across them.
"""

from __future__ import annotations

import pytest

from src.api.admin import hotels as hotels_module
from src.auth import AdminUser, require_admin
from src.main import app


class _Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._gte: list[tuple[str, object]] = []
        self._or: str | None = None
        self._start: int | None = None
        self._end: int | None = None
        self.update_payload: dict | None = None
        self._inserted: list[dict] | None = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def in_(self, field, values):
        self._in.append((field, list(values)))
        return self

    def gte(self, field, value):
        self._gte.append((field, value))
        return self

    def or_(self, expr):
        self._or = expr
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def insert(self, payload):
        row = {**payload, "id": payload.get("id") or f"generated-{len(self._rows)}"}
        self._rows.append(row)
        self._inserted = [row]
        return self

    def _matches(self, row) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field, value in self._gte:
            if row.get(field) is None or row.get(field) < value:
                return False
        return True

    def execute(self):
        if self._inserted is not None:
            return _Response(self._inserted, count=len(self._inserted))
        rows = [row for row in self._rows if self._matches(row)]
        total = len(rows)
        if self._start is not None:
            rows = rows[self._start : self._end + 1]
        return _Response(rows, count=total)


class _FakeRpc:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]], rpc_results: dict[str, object] | None = None):
        self._tables = tables
        self.table_calls: list[str] = []
        self.queries: dict[str, list[_FakeQuery]] = {}
        self._rpc_results = rpc_results or {}
        self.rpc_calls: list[tuple[str, dict]] = []

    def table(self, name):
        self.table_calls.append(name)
        query = _FakeQuery(self._tables.get(name, []))
        self.queries.setdefault(name, []).append(query)
        return query

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeRpc(_Response(self._rpc_results.get(name)))


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def no_audit(monkeypatch):
    """Prevents write_audit from making a real Supabase call -- and lets
    tests assert on exactly what it was called with."""
    calls: list[dict] = []
    monkeypatch.setattr(
        hotels_module,
        "write_audit",
        lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}),
    )
    return calls


# ---------------------------------------------------------------------------
# _embedding_state / _row_to_hotel (pure logic, plan's L23 mitigation)
# ---------------------------------------------------------------------------


def test_embedding_state_missing_when_hotel_not_embedded():
    assert hotels_module._embedding_state(False, 0) == "missing"


def test_embedding_state_partial_when_rooms_missing_embedding():
    assert hotels_module._embedding_state(True, 3) == "partial"


def test_embedding_state_embedded_when_fully_embedded():
    assert hotels_module._embedding_state(True, 0) == "embedded"


def test_row_to_hotel_maps_view_row():
    row = {
        "id": "hotel-1",
        "name": "Mường Thanh Grand Đà Nẵng",
        "address": "962 Ngô Quyền, Sơn Trà",
        "city": "Đà Nẵng",
        "star_rating": 4,
        "source_platform": "booking",
        "is_manual": False,
        "is_active": True,
        "room_count": 42,
        "hotel_embedded": True,
        "rooms_missing_embedding": 3,
        "image_url": "https://example.com/hotel.jpg",
    }
    hotel = hotels_module._row_to_hotel(row)
    assert hotel.embedding_state == "partial"
    assert hotel.room_count == 42
    assert hotel.is_manual is False


# ---------------------------------------------------------------------------
# GET /api/v1/admin/hotels
# ---------------------------------------------------------------------------


def _hotel_row(**overrides) -> dict:
    row = {
        "id": "hotel-1",
        "name": "Mường Thanh Grand Đà Nẵng",
        "address": "962 Ngô Quyền, Sơn Trà",
        "city": "Đà Nẵng",
        "star_rating": 4,
        "source_platform": "booking",
        "is_manual": False,
        "is_active": True,
        "room_count": 42,
        "hotel_embedded": True,
        "rooms_missing_embedding": 0,
        "image_url": None,
        "updated_at": "2026-08-20T00:00:00Z",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_list_hotels_returns_items_and_total(client, admin_override, monkeypatch):
    rows = [_hotel_row(id="h1"), _hotel_row(id="h2", is_manual=True, source_platform="manual")]
    fake_client = _FakeClient({"admin_hotel_rows": rows})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert {item["id"] for item in body["items"]} == {"h1", "h2"}


@pytest.mark.asyncio
async def test_list_hotels_applies_search_source_active_and_embedding_filters(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"admin_hotel_rows": [_hotel_row()]})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get(
        "/api/v1/admin/hotels",
        params={"q": "đà nẵng", "source": "manual", "is_active": "true", "embedding": "missing", "page": 2, "page_size": 10},
    )

    assert response.status_code == 200
    query = fake_client.queries["admin_hotel_rows"][0]
    assert query._or == "name.ilike.%đà nẵng%,city.ilike.%đà nẵng%"
    assert ("is_manual", True) in query._eq
    assert ("is_active", True) in query._eq
    assert ("hotel_embedded", False) in query._eq
    assert (query._start, query._end) == (10, 19)


@pytest.mark.asyncio
async def test_list_hotels_csv_format_returns_downloadable_csv(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"admin_hotel_rows": [_hotel_row(name="Khách sạn Ngô Quyền")]})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels", params={"format": "csv"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    # Leading UTF-8 BOM so Excel renders Vietnamese diacritics correctly.
    assert response.text.startswith("﻿")
    assert "Khách sạn Ngô Quyền" in response.text


# ---------------------------------------------------------------------------
# PATCH /api/v1/admin/hotels/{id}/active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_hotel_active_false_succeeds_and_writes_audit_when_no_future_bookings(
    client, admin_override, no_audit, monkeypatch
):
    fake_client = _FakeClient({"rooms": [], "hotels": []})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1/active", json={"is_active": False})

    assert response.status_code == 200
    assert response.json() == {"id": "hotel-1", "is_active": False}
    hotels_update = fake_client.queries["hotels"][0]
    assert hotels_update.update_payload == {"is_active": False}
    assert hotels_update._eq == [("id", "hotel-1")]
    assert len(no_audit) == 1
    assert no_audit[0]["action"] == "hotel.deactivate"
    assert no_audit[0]["entity_id"] == "hotel-1"


@pytest.mark.asyncio
async def test_set_hotel_active_false_blocked_by_future_confirmed_booking(client, admin_override, no_audit, monkeypatch):
    rooms = [{"id": "room-1", "hotel_id": "hotel-1"}]
    bookings = [
        {
            "id": "booking-1",
            "room_id": "room-1",
            "status": "CONFIRMED",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-05",
            "rooms": {"name": "Deluxe King"},
        }
    ]
    fake_client = _FakeClient({"rooms": rooms, "bookings": bookings, "hotels": []})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1/active", json={"is_active": False})

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "hotel_has_future_confirmed_bookings"
    assert body["count"] == 1
    assert body["bookings"] == [{"booking_id": "booking-1", "check_in_date": "2026-09-01", "room_name": "Deluxe King"}]
    # Neither the hotel row nor the audit log should be touched when blocked.
    assert "hotels" not in fake_client.queries
    assert no_audit == []


@pytest.mark.asyncio
async def test_set_hotel_active_true_skips_blocking_check(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient({"hotels": []})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1/active", json={"is_active": True})

    assert response.status_code == 200
    assert "rooms" not in fake_client.table_calls
    assert "bookings" not in fake_client.table_calls
    assert no_audit[0]["action"] == "hotel.activate"


# ---------------------------------------------------------------------------
# POST /api/v1/admin/hotels/bulk-active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_set_hotel_active_reports_updated_and_blocked(client, admin_override, no_audit, monkeypatch):
    rooms = [{"id": "room-1", "hotel_id": "hotel-blocked"}]
    bookings = [
        {
            "id": "booking-1",
            "room_id": "room-1",
            "status": "CONFIRMED",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-05",
            "rooms": {"name": "Deluxe King"},
        }
    ]
    fake_client = _FakeClient({"rooms": rooms, "bookings": bookings, "hotels": []})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post(
        "/api/v1/admin/hotels/bulk-active",
        json={"hotel_ids": ["hotel-blocked", "hotel-free"], "is_active": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 1
    assert body["blocked"] == [{"hotel_id": "hotel-blocked", "count": 1}]
    assert len(no_audit) == 1
    assert no_audit[0]["entity_id"] == "hotel-free"


# ---------------------------------------------------------------------------
# embedding_fields.py -- source of truth for B2/B3's "ảnh hưởng tìm kiếm của
# bot" labels
# ---------------------------------------------------------------------------


def test_b2_rag_labeled_fields_are_a_subset_of_embedding_fields():
    """B2's frontend hardcodes the RAG label on exactly 4 fields (L28: Tên,
    Loại hình, Mô tả, Địa chỉ) -- this is a Python-side literal of that same
    set, not an import of the frontend's source, so it does NOT catch the
    frontend dropping/renaming a label on its own. What it does catch: the
    DAG's TABLE_COLUMNS shrinking below what B2 hardcodes, which is the
    direction that would make the labels actively wrong (claiming a field
    affects the bot's search when it no longer does)."""
    from src.api.admin.embedding_fields import EMBEDDING_FIELDS

    b2_labeled_fields = {"name", "accommodation_type", "description", "address"}
    assert b2_labeled_fields <= set(EMBEDDING_FIELDS)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/hotels/accommodation-types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_accommodation_types_returns_sorted_distinct_values(client, admin_override, monkeypatch):
    rows = [
        {"accommodation_type": "Resort"},
        {"accommodation_type": "hotel"},
        {"accommodation_type": "Resort"},
        {"accommodation_type": None},
    ]
    fake_client = _FakeClient({"hotels": rows})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/accommodation-types")

    assert response.status_code == 200
    assert response.json() == ["Resort", "hotel"]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/hotels (B2 -- phase-08-hotel-create.md)
# ---------------------------------------------------------------------------


def _create_body(**overrides) -> dict:
    body = {
        "name": "Boutique Hoi An Riverside",
        "accommodation_type": "Khách sạn boutique",
        "description": "Một khách sạn boutique ven sông.",
        "star_rating": 4,
        "address": "42 Nguyễn Phúc Chu, phường Minh An",
        "destination_id": "3d97277e-8210-45bf-9842-eea4fd356e9e",
        "city": "Quảng Nam",
        "latitude": 15.87721,
        "longitude": 108.32694,
        "check_in_time": "14:00",
        "check_out_time": "12:00",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_create_hotel_succeeds_with_manual_source_and_null_embedding(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 17})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body())

    assert response.status_code == 201
    body = response.json()
    assert body["source_platform"] == "manual"
    assert body["source_hotel_id"] == 17
    assert body["embedding_state"] == "missing"
    assert body["is_active"] is True

    inserted = fake_client.queries["hotels"][0]._inserted[0]
    assert inserted["source_platform"] == "manual"
    assert inserted["source_hotel_id"] == 17
    assert inserted["embedding"] is None
    assert inserted["is_active"] is True
    assert inserted["coordinates"] == "15.87721, 108.32694"

    assert no_audit[0]["action"] == "hotel.create"
    assert no_audit[0]["entity_id"] == body["id"]


@pytest.mark.asyncio
async def test_create_hotel_ignores_client_supplied_source_platform(client, admin_override, no_audit, monkeypatch):
    """Plan's `source_platform` non-negotiable: a client claiming 'booking'
    must still land as 'manual', or a fake row could enter the ETL
    namespace the pipeline trusts."""
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(source_platform="booking"))

    assert response.status_code == 201
    assert response.json()["source_platform"] == "manual"


@pytest.mark.asyncio
async def test_create_hotel_missing_name_returns_422(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(name=""))

    assert response.status_code == 422
    assert "hotels" not in fake_client.table_calls


@pytest.mark.asyncio
async def test_create_hotel_two_in_a_row_get_increasing_source_hotel_id(client, admin_override, monkeypatch):
    """Each call re-reads the RPC (not a cached/currval value), so two
    successive creates never collide on UNIQUE(source_platform,
    source_hotel_id)."""
    fake_client = _FakeClient({"hotels": []})
    calls = iter([17, 18])
    fake_client.rpc = lambda name, params: _FakeRpc(_Response(next(calls)))  # type: ignore[method-assign]
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    first = await client.post("/api/v1/admin/hotels", json=_create_body())
    second = await client.post("/api/v1/admin/hotels", json=_create_body(name="Khách sạn thứ hai"))

    assert first.json()["source_hotel_id"] == 17
    assert second.json()["source_hotel_id"] == 18
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.asyncio
async def test_create_hotel_without_coordinates_omits_coordinates_field(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(latitude=None, longitude=None))

    assert response.status_code == 201
    inserted = fake_client.queries["hotels"][0]._inserted[0]
    assert "coordinates" not in inserted


@pytest.mark.asyncio
async def test_create_hotel_only_latitude_returns_422(client, admin_override, monkeypatch):
    """Half-filled coordinates would otherwise write no `coordinates` at all
    with no signal to the admin -- must 422 instead."""
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(latitude=15.87721, longitude=None))

    assert response.status_code == 422
    assert "hotels" not in fake_client.table_calls


@pytest.mark.asyncio
async def test_create_hotel_whitespace_only_name_returns_422(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(name="   "))

    assert response.status_code == 422
    assert "hotels" not in fake_client.table_calls


@pytest.mark.asyncio
async def test_create_hotel_accommodation_type_over_column_width_returns_422(client, admin_override, monkeypatch):
    """`accommodation_type` is VARCHAR(50) -- an over-long value must 422
    here instead of reaching Postgres as an unhandled 22001."""
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(accommodation_type="x" * 51))

    assert response.status_code == 422
    assert "hotels" not in fake_client.table_calls


@pytest.mark.asyncio
async def test_create_hotel_malformed_destination_id_returns_422(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": []}, rpc_results={"next_manual_hotel_source_id": 1})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels", json=_create_body(destination_id="not-a-uuid"))

    assert response.status_code == 422
    assert "hotels" not in fake_client.table_calls


# ---------------------------------------------------------------------------
# CSV formula injection (L3 -- B2 makes name/address/city user-controlled)
# ---------------------------------------------------------------------------


def test_csv_safe_escapes_leading_formula_characters():
    for dangerous in ("=cmd()", "+1+1", "-1-1", "@SUM(A1)"):
        assert hotels_module._csv_safe(dangerous).startswith("\t")
    assert hotels_module._csv_safe("Khách sạn Ngô Quyền") == "Khách sạn Ngô Quyền"
