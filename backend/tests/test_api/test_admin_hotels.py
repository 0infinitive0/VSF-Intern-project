"""Tests for admin B1 (Danh sách khách sạn) -- src/api/admin/hotels.py.

Uses a generic in-memory fake for the postgrest-style `.table(...).eq(...)
.execute()` chain (extends the recording-fake pattern already used by
tests/test_booking_service.py) since three tables are queried across these
endpoints (admin_hotel_rows, rooms, bookings, hotels) and the blocking-
booking check joins across them.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.admin import hotels as hotels_module

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
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
        self._is: list[tuple[str, object]] = []
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

    def is_(self, field, value):
        """postgrest `is.null` -- `get_hotel`/`update_hotel` read through
        `.is_("deleted_at", "null")` so a soft-deleted hotel 404s
        (20260826_add_hotels_deleted_at.sql)."""
        self._is.append((field, None if value == "null" else value))
        return self

    def or_(self, expr):
        self._or = expr
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def limit(self, n):
        self._start, self._end = 0, n - 1
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
        for field, value in self._is:
            if row.get(field) is not value:
                return False
        return True

    def execute(self):
        if self._inserted is not None:
            return _Response(self._inserted, count=len(self._inserted))
        if self.update_payload is not None:
            matched = [row for row in self._rows if self._matches(row)]
            for row in matched:
                row.update(self.update_payload)
            return _Response(matched, count=len(matched))
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


class _FakeStorageBucket:
    def __init__(self):
        self.uploaded: list[tuple[str, bytes, dict]] = []

    def upload(self, path, data, options):
        self.uploaded.append((path, data, options))
        return {"path": path}

    def get_public_url(self, path):
        return f"https://fake.supabase.co/storage/v1/object/public/hotel-images/{path}"


class _FakeStorage:
    def __init__(self):
        self.buckets: dict[str, _FakeStorageBucket] = {}

    def from_(self, bucket_name):
        return self.buckets.setdefault(bucket_name, _FakeStorageBucket())


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]], rpc_results: dict[str, object] | None = None):
        self._tables = tables
        self.table_calls: list[str] = []
        self.queries: dict[str, list[_FakeQuery]] = {}
        self._rpc_results = rpc_results or {}
        self.rpc_calls: list[tuple[str, dict]] = []
        self.storage = _FakeStorage()

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


def test_embedding_state_stale_when_hotel_vector_predates_its_text():
    assert hotels_module._embedding_state(True, 0, True, 0) == "stale"


def test_embedding_state_stale_when_only_a_room_vector_predates_its_text():
    assert hotels_module._embedding_state(True, 0, False, 2) == "stale"


def test_embedding_state_missing_beats_stale():
    """A hotel with no vector is invisible to search; one with an outdated
    vector is merely answering from old text. The worse state must win, or
    the badge would tell the admin the cheaper problem."""
    assert hotels_module._embedding_state(False, 0, True, 5) == "missing"


def test_embedding_state_partial_beats_stale():
    assert hotels_module._embedding_state(True, 3, True, 5) == "partial"


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


def test_row_to_hotel_reads_stale_flags_from_the_view():
    row = {
        "id": "hotel-1",
        "name": "Mường Thanh Grand Đà Nẵng",
        "source_platform": "booking",
        "is_manual": False,
        "is_active": True,
        "room_count": 42,
        "hotel_embedded": True,
        "rooms_missing_embedding": 0,
        "hotel_embedding_stale": True,
        "rooms_stale_embedding": 4,
    }
    hotel = hotels_module._row_to_hotel(row)
    assert hotel.embedding_state == "stale"
    assert hotel.hotel_embedding_stale is True
    assert hotel.rooms_stale_embedding == 4


def test_row_to_hotel_from_a_view_without_the_stale_columns_is_not_stale():
    """Rolling deploy: a Postgres that hasn't had
    20260827_add_embedding_stale.sql applied returns rows without the two
    staleness columns. Those rows must read as the pre-staleness states
    rather than 500 the whole list."""
    row = {
        "id": "hotel-1",
        "name": "Mường Thanh Grand Đà Nẵng",
        "source_platform": "booking",
        "is_manual": False,
        "is_active": True,
        "room_count": 42,
        "hotel_embedded": True,
        "rooms_missing_embedding": 0,
    }
    hotel = hotels_module._row_to_hotel(row)
    assert hotel.embedding_state == "embedded"
    assert hotel.hotel_embedding_stale is False


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
async def test_list_hotels_embedding_incomplete_covers_missing_hotel_or_missing_rooms(client, admin_override, monkeypatch):
    """B7's own filter (phase-12-embedding-status.md): unlike `missing`
    (`hotel_embedded=false` only), `incomplete` must also catch a hotel
    whose own embedding is set but still has rooms missing theirs -- B1's
    `missing` filter would silently skip that hotel. Stale rows belong here
    too: the bot has learned the hotel, but not what it currently says."""
    fake_client = _FakeClient({"admin_hotel_rows": [_hotel_row()]})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels", params={"embedding": "incomplete"})

    assert response.status_code == 200
    query = fake_client.queries["admin_hotel_rows"][0]
    assert query._or == (
        "hotel_embedded.eq.false,rooms_missing_embedding.gt.0,"
        "hotel_embedding_stale.eq.true,rooms_stale_embedding.gt.0"
    )
    assert ("hotel_embedded", False) not in query._eq


@pytest.mark.asyncio
async def test_list_hotels_embedding_stale_filter_covers_hotel_or_room_staleness(client, admin_override, monkeypatch):
    """"Cần chạy lại" is its own filter, not a slice of `missing`: those rows
    still have a vector, so `hotel_embedded` is true for every one of them."""
    fake_client = _FakeClient({"admin_hotel_rows": [_hotel_row()]})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels", params={"embedding": "stale"})

    assert response.status_code == 200
    query = fake_client.queries["admin_hotel_rows"][0]
    assert query._or == "hotel_embedding_stale.eq.true,rooms_stale_embedding.gt.0"
    assert ("hotel_embedded", False) not in query._eq


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


# ---------------------------------------------------------------------------
# GET / PATCH /api/v1/admin/hotels/{id} (B3 -- phase-09-hotel-edit.md)
# ---------------------------------------------------------------------------


def _hotel_detail_row(**overrides) -> dict:
    row = {
        "id": "hotel-1",
        "name": "Mường Thanh Grand Đà Nẵng",
        "accommodation_type": "hotel",
        "description": "Mô tả gốc.",
        "star_rating": 4,
        "address": "962 Ngô Quyền, Sơn Trà",
        "city": "Đà Nẵng",
        "area_name": "Sơn Trà",
        "location_highlight": "Cách bãi biển 350 mét",
        "destination_id": "44f1bfd4-f8a9-4d49-a0fb-932d69d705c9",
        "coordinates": "16.06, 108.24",
        "check_in_time": "14:00",
        "check_in_until": None,
        "check_out_time": "12:00",
        "amenities": ["swimming_pool", "wifi"],
        "amenity_groups": None,
        "images": ["https://example.com/1.jpg"],
        "image_url": "https://example.com/1.jpg",
        "nearby_attractions": None,
        "nearby_essentials": None,
        "source_platform": "booking",
        "is_active": True,
    }
    row.update(overrides)
    return row


def _admin_aggregates_row(**overrides) -> dict:
    row = {
        "id": "hotel-1",
        "is_manual": False,
        "hotel_embedded": True,
        "rooms_missing_embedding": 0,
        "room_count": 128,
    }
    row.update(overrides)
    return row


def _fake_client_for_hotel(hotel_row: dict, aggregates_row: dict, **extra_tables) -> _FakeClient:
    return _FakeClient({"hotels": [hotel_row], "admin_hotel_rows": [aggregates_row], **extra_tables})


@pytest.mark.asyncio
async def test_get_hotel_manual_hotel_has_no_pipeline_managed_fields(client, admin_override, monkeypatch):
    hotel = _hotel_detail_row(source_platform="manual")
    aggregates = _admin_aggregates_row(is_manual=True)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: _fake_client_for_hotel(hotel, aggregates))

    response = await client.get("/api/v1/admin/hotels/hotel-1")

    assert response.status_code == 200
    body = response.json()
    assert body["is_manual"] is True
    assert body["pipeline_managed_fields"] == []
    assert body["rag_fields"] == list(hotels_module.EMBEDDING_FIELDS)
    assert body["latitude"] == 16.06 and body["longitude"] == 108.24


@pytest.mark.asyncio
async def test_get_hotel_etl_hotel_has_pipeline_managed_fields(client, admin_override, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: _fake_client_for_hotel(hotel, aggregates))

    response = await client.get("/api/v1/admin/hotels/hotel-1")

    assert response.status_code == 200
    body = response.json()
    assert body["is_manual"] is False
    assert set(body["pipeline_managed_fields"]) == set(hotels_module.PIPELINE_MANAGED_FIELDS_HOTEL)
    assert body["room_count"] == 128


@pytest.mark.asyncio
async def test_get_hotel_not_found_returns_404(client, admin_override, monkeypatch):
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: _FakeClient({"hotels": [], "admin_hotel_rows": []}))

    response = await client.get("/api/v1/admin/hotels/missing")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_hotel_description_marks_embedding_stale_and_flags_rag_changed(client, admin_override, no_audit, monkeypatch):
    """A RAG edit keeps the vector and marks it out of date. Nulling it would
    drop the hotel out of `match_hotels_with_rooms` (it filters on
    `embedding IS NOT NULL`), so the bot would stop finding the hotel at all
    over a description edit (20260827_add_embedding_stale.sql)."""
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"description": "Mô tả mới."})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["description"]
    assert body["rag_fields_changed"] == ["description"]
    assert body["embedding_stale"] is True
    assert body["embedding_state"] == "stale"
    hotels_update = fake_client.queries["hotels"][1]  # [0] was the current-row read
    assert hotels_update.update_payload["description"] == "Mô tả mới."
    assert hotels_update.update_payload["embedding_stale"] is True
    assert "embedding" not in hotels_update.update_payload
    assert no_audit[0]["action"] == "hotel.update"
    assert "embedding" not in no_audit[0]["after"]


@pytest.mark.asyncio
async def test_update_hotel_rag_field_keeps_missing_when_hotel_has_no_vector(client, admin_override, no_audit, monkeypatch):
    """Staleness never downgrades a worse state: a hotel that was never
    embedded stays "Chưa embed", not "Cần chạy lại"."""
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row(hotel_embedded=False)
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"description": "Mô tả mới."})

    assert response.status_code == 200
    assert response.json()["embedding_state"] == "missing"


@pytest.mark.asyncio
async def test_update_hotel_rag_field_keeps_partial_when_rooms_are_unembedded(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row(rooms_missing_embedding=3)
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"description": "Mô tả mới."})

    assert response.status_code == 200
    assert response.json()["embedding_state"] == "partial"


@pytest.mark.asyncio
async def test_update_hotel_star_rating_only_does_not_mark_embedding_stale(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"star_rating": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["star_rating"]
    assert body["rag_fields_changed"] == []
    assert body["embedding_stale"] is False
    assert body["embedding_state"] == "embedded"
    hotels_update = fake_client.queries["hotels"][1]
    assert "embedding" not in hotels_update.update_payload
    assert "embedding_stale" not in hotels_update.update_payload


@pytest.mark.asyncio
async def test_update_hotel_mixed_rag_and_non_rag_only_rag_reported_as_changed(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch(
        "/api/v1/admin/hotels/hotel-1", json={"check_in_time": "15:00", "description": "Mô tả mới."}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["changed_fields"]) == {"check_in_time", "description"}
    assert body["rag_fields_changed"] == ["description"]


@pytest.mark.asyncio
async def test_update_hotel_ignores_source_platform_in_body(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch(
        "/api/v1/admin/hotels/hotel-1", json={"source_platform": "manual", "star_rating": 3}
    )

    assert response.status_code == 200
    hotels_update = fake_client.queries["hotels"][1]
    assert "source_platform" not in hotels_update.update_payload


@pytest.mark.asyncio
async def test_update_hotel_invalid_amenity_id_returns_422_and_no_write(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(hotels_module, "query_all_approved_amenities_by_ids", lambda ids: [])

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"amenities": ["not_a_real_id"]})

    assert response.status_code == 422
    assert response.json()["detail"] == "Tiện ích không hợp lệ: not_a_real_id"
    assert len(fake_client.queries["hotels"]) == 1  # only the current-row read, no update query issued
    assert no_audit == []


@pytest.mark.asyncio
async def test_update_hotel_amenities_accepts_approved_hotel_scoped_ids(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row(amenities=["wifi"])
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)
    catalog = [SimpleNamespace(id="swimming_pool", scope="hotel"), SimpleNamespace(id="wifi", scope="both")]
    monkeypatch.setattr(
        hotels_module, "query_all_approved_amenities_by_ids", lambda ids: [e for e in catalog if e.id in ids]
    )

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"amenities": ["swimming_pool", "wifi"]})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["amenities"]
    assert body["rag_fields_changed"] == ["amenities"]


@pytest.mark.asyncio
async def test_update_hotel_amenities_reorder_only_is_not_a_change(client, admin_override, no_audit, monkeypatch):
    """Same set, different order -- must not report a change, clear
    `embedding`, or write anything. A toggle-on-then-off in
    hotel-tab-amenities.tsx produces exactly this."""
    hotel = _hotel_detail_row(amenities=["wifi", "swimming_pool"])
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"amenities": ["swimming_pool", "wifi"]})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == []
    assert body["embedding_stale"] is False
    assert len(fake_client.queries["hotels"]) == 1  # only the current-row read, no write
    assert no_audit == []


@pytest.mark.asyncio
async def test_update_hotel_amenities_only_validates_newly_added_ids(client, admin_override, no_audit, monkeypatch):
    """A pre-existing id that's since fallen out of the catalog (e.g.
    unapproved) must not block saving unrelated changes to this row."""
    hotel = _hotel_detail_row(amenities=["legacy_unapproved_id"])
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)
    lookups: list[list[str]] = []

    def fake_lookup(ids):
        lookups.append(list(ids))
        return [SimpleNamespace(id="wifi", scope="both")]

    monkeypatch.setattr(hotels_module, "query_all_approved_amenities_by_ids", fake_lookup)

    response = await client.patch(
        "/api/v1/admin/hotels/hotel-1", json={"amenities": ["legacy_unapproved_id", "wifi"]}
    )

    assert response.status_code == 200
    assert lookups == [["wifi"]]  # only the newly-added id was checked


@pytest.mark.asyncio
async def test_update_hotel_no_changes_writes_nothing(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"star_rating": hotel["star_rating"]})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == []
    assert body["embedding_stale"] is False
    assert len(fake_client.queries["hotels"]) == 1  # only the current-row read
    assert no_audit == []


@pytest.mark.asyncio
async def test_update_hotel_not_found_returns_404(client, admin_override, monkeypatch):
    monkeypatch.setattr(
        hotels_module, "get_supabase_client", lambda: _FakeClient({"hotels": [], "admin_hotel_rows": []})
    )

    response = await client.patch("/api/v1/admin/hotels/missing", json={"star_rating": 4})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_hotel_latitude_only_recombines_with_existing_longitude(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row(coordinates="16.06, 108.24")
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"latitude": 10.5})

    assert response.status_code == 200
    hotels_update = fake_client.queries["hotels"][1]
    assert hotels_update.update_payload["coordinates"] == "10.5, 108.24"


@pytest.mark.asyncio
async def test_update_hotel_both_coordinates_present_one_null_returns_422(client, admin_override, monkeypatch):
    """Sending both keys with only one null would otherwise wipe
    `coordinates` entirely (update_hotel's recombination can't tell "the
    other one was explicitly cleared" from "the other one was never
    touched")."""
    fake_client = _fake_client_for_hotel(_hotel_detail_row(coordinates="16.06, 108.24"), _admin_aggregates_row())
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"latitude": None, "longitude": 108.24})

    assert response.status_code == 422
    assert "hotels" not in fake_client.queries


@pytest.mark.asyncio
async def test_update_hotel_explicit_null_clears_nullable_field(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row(star_rating=4)
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"star_rating": None})

    assert response.status_code == 200
    assert response.json()["changed_fields"] == ["star_rating"]
    hotels_update = fake_client.queries["hotels"][1]
    assert hotels_update.update_payload["star_rating"] is None


@pytest.mark.asyncio
async def test_update_hotel_rejects_non_http_image_url(client, admin_override, monkeypatch):
    fake_client = _fake_client_for_hotel(_hotel_detail_row(), _admin_aggregates_row())
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"images": ["javascript:alert(1)"]})

    assert response.status_code == 422
    assert "hotels" not in fake_client.queries


@pytest.mark.asyncio
async def test_update_hotel_bumps_updated_at_but_excludes_it_from_audit(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row()
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/hotels/hotel-1", json={"star_rating": 5})

    assert response.status_code == 200
    hotels_update = fake_client.queries["hotels"][1]
    assert "updated_at" in hotels_update.update_payload
    assert "updated_at" not in no_audit[0]["after"]
    assert "updated_at" not in response.json()["changed_fields"]


@pytest.mark.asyncio
async def test_update_hotel_images_changed_but_not_rag_relevant(client, admin_override, no_audit, monkeypatch):
    hotel = _hotel_detail_row(images=["https://example.com/1.jpg"])
    aggregates = _admin_aggregates_row()
    fake_client = _fake_client_for_hotel(hotel, aggregates)
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch(
        "/api/v1/admin/hotels/hotel-1", json={"images": ["https://example.com/1.jpg", "https://example.com/2.jpg"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["images"]
    assert body["rag_fields_changed"] == []
    assert body["embedding_stale"] is False


# ---------------------------------------------------------------------------
# embedding_fields.py's two constants vs. their actual DAG source (drift guard)
#
# Asserting `EMBEDDING_FIELDS`/`PIPELINE_MANAGED_FIELDS_HOTEL` against
# themselves (elsewhere in this file) only proves the response wiring reads
# them -- it says nothing about whether the copies are still correct. These
# two parse the literal DAG source (airflow isn't importable from this
# venv -- see test_rpc_call_sites_known.py's docstring for the same
# constraint) so a DAG column-list edit that isn't mirrored here fails a
# test instead of silently drifting.
# ---------------------------------------------------------------------------


def _dag_hotel_table_columns() -> list[str]:
    path = _BACKEND_ROOT / "src" / "airflow" / "dags" / "data_pipeline" / "embed_supabase_dag.py"
    match = re.search(r'"hotels":\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    assert match, "TABLE_COLUMNS['hotels'] not found in embed_supabase_dag.py"
    columns = match.group(1).split(",")
    columns.remove("id")
    return columns


def _pipeline_hotel_update_columns() -> list[str]:
    path = _BACKEND_ROOT / "src" / "airflow" / "dags" / "data_pipeline" / "hotel_pipeline.py"
    match = re.search(r"_HOTEL_COLUMNS = \[(.*?)\]", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, "_HOTEL_COLUMNS not found in hotel_pipeline.py"
    columns = re.findall(r'"([a-z_]+)"', match.group(1))
    return [c for c in columns if c not in ("source_platform", "source_hotel_id")]


def test_embedding_fields_matches_embed_supabase_dag_table_columns():
    assert list(hotels_module.EMBEDDING_FIELDS) == _dag_hotel_table_columns()


def test_pipeline_managed_fields_matches_hotel_pipeline_update_columns():
    assert list(hotels_module.PIPELINE_MANAGED_FIELDS_HOTEL) == _pipeline_hotel_update_columns()


def test_invalid_amenity_ids_helper_filters_room_only_scope(monkeypatch):
    monkeypatch.setattr(
        hotels_module,
        "query_all_approved_amenities_by_ids",
        lambda ids: [SimpleNamespace(id="room_service", scope="room")],
    )
    assert hotels_module._invalid_amenity_ids(["room_service"]) == ["room_service"]
    assert hotels_module._invalid_amenity_ids([]) == []


# ---------------------------------------------------------------------------
# POST /api/v1/admin/hotels/{id}/images/upload (B3 -- Hình ảnh tab, L38)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_hotel_image_succeeds_and_returns_public_url(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post(
        "/api/v1/admin/hotels/hotel-1/images/upload",
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fakejpegbytes", "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"].startswith("https://fake.supabase.co/storage/v1/object/public/hotel-images/hotel-1/")
    assert body["url"].endswith(".jpg")

    bucket = fake_client.storage.buckets["hotel-images"]
    assert len(bucket.uploaded) == 1
    uploaded_path, uploaded_bytes, options = bucket.uploaded[0]
    assert uploaded_path.startswith("hotel-1/")
    assert uploaded_bytes == b"\xff\xd8\xff\xe0fakejpegbytes"
    assert options["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_hotel_image_rejects_unsupported_type(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)

    response = await client.post(
        "/api/v1/admin/hotels/hotel-1/images/upload",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported_image_type"
    assert fake_client.storage.buckets == {}


@pytest.mark.asyncio
async def test_upload_hotel_image_rejects_oversized_file(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(hotels_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(hotels_module, "_MAX_UPLOAD_BYTES", 10)

    response = await client.post(
        "/api/v1/admin/hotels/hotel-1/images/upload",
        files={"file": ("photo.jpg", b"x" * 100, "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "image_too_large"
    assert fake_client.storage.buckets == {}
