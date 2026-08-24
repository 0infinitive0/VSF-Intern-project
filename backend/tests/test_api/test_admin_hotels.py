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
        rows = [row for row in self._rows if self._matches(row)]
        total = len(rows)
        if self._start is not None:
            rows = rows[self._start : self._end + 1]
        return _Response(rows, count=total)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.table_calls: list[str] = []
        self.queries: dict[str, list[_FakeQuery]] = {}

    def table(self, name):
        self.table_calls.append(name)
        query = _FakeQuery(self._tables.get(name, []))
        self.queries.setdefault(name, []).append(query)
        return query


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
