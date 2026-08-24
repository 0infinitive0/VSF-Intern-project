"""Tests for admin B5 (Quản lý phòng) -- src/api/admin/rooms.py
(phase-10-rooms.md). Same generic in-memory postgrest fake pattern as
test_admin_hotels.py, extended with `.gte`/`.lt`/`.delete` for the
room_prices/bookings queries this module issues.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.admin import rooms as rooms_module
from src.auth import AdminUser, require_admin
from src.main import app

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class _Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, rows, on_delete=None):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._gte: list[tuple[str, object]] = []
        self._lt: list[tuple[str, object]] = []
        self._start: int | None = None
        self._end: int | None = None
        self.update_payload: dict | None = None
        self._inserted: list[dict] | None = None
        self._deleting = False
        self._on_delete = on_delete

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

    def lt(self, field, value):
        self._lt.append((field, value))
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

    def delete(self):
        self._deleting = True
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
        for field, value in self._lt:
            if row.get(field) is None or row.get(field) >= value:
                return False
        return True

    def execute(self):
        if self._inserted is not None:
            return _Response(self._inserted, count=len(self._inserted))
        matched = [row for row in self._rows if self._matches(row)]
        if self.update_payload is not None:
            for row in matched:
                row.update(self.update_payload)
            return _Response(matched, count=len(matched))
        if self._deleting:
            if self._on_delete:
                self._on_delete(matched)
            return _Response(matched, count=len(matched))
        rows = matched
        if self._start is not None:
            rows = rows[self._start : self._end + 1]
        return _Response(rows, count=len(matched))


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

    def _on_delete(self, table_name):
        def handler(matched_rows):
            for row in matched_rows:
                self._tables[table_name].remove(row)

        return handler

    def table(self, name):
        self.table_calls.append(name)
        query = _FakeQuery(self._tables.setdefault(name, []), on_delete=self._on_delete(name))
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
    calls: list[dict] = []
    monkeypatch.setattr(rooms_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


def _room_row(**overrides) -> dict:
    row = {
        "id": "room-1",
        "hotel_id": "hotel-1",
        "source_room_id": 501,
        "name": "Deluxe King",
        "bed_description": "1 giường đôi lớn (King)",
        "room_size_sqm": 32,
        "max_occupancy_raw": "2 người lớn",
        "max_guests": 2,
        "view": "Nhìn ra thành phố",
        "room_facilities": ["air_conditioning", "minibar"],
        "available_room_count": 5,
        "embedding": [0.1] * 4,
        "images": ["https://example.com/1.jpg"],
        "image_count": 1,
    }
    row.update(overrides)
    return row


def _fake_client_for_room(room: dict, *, hotel_source_platform="manual") -> _FakeClient:
    return _FakeClient({"hotels": [{"id": room["hotel_id"], "source_platform": hotel_source_platform}], "rooms": [room]})


# ---------------------------------------------------------------------------
# GET /hotels/{hotel_id}/rooms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_rooms_empty_hotel_returns_empty_items(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "hotel-1", "source_platform": "manual"}], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/hotel-1/rooms")

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_list_rooms_unknown_hotel_returns_404(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/missing/rooms")

    assert response.status_code == 404


class _ColumnMissingQuery(_FakeQuery):
    """Raises like postgrest's 42703 when `.select()` is called with a field
    list containing `_missing_column`; otherwise projects rows down to the
    requested fields (unlike the base fake, which ignores `.select()` and
    returns whole rows) so a legacy-field retry actually proves the missing
    column is gone from the response, not just that no exception was
    raised. Reproduces a deployment whose `rooms` table hasn't had
    `max_occupancy_raw` added yet (see `_ROOM_FIELDS_LEGACY`)."""

    _missing_column = "max_occupancy_raw"

    def select(self, *args, **kwargs):
        self._selected_fields = args[0].split(",") if args else None
        return super().select(*args, **kwargs)

    def execute(self):
        if self._selected_fields and self._missing_column in self._selected_fields:
            raise Exception(f"column rooms.{self._missing_column} does not exist")
        response = super().execute()
        if self._selected_fields:
            response.data = [{k: v for k, v in row.items() if k in self._selected_fields} for row in response.data]
        return response


@pytest.mark.asyncio
async def test_list_rooms_falls_back_when_max_occupancy_raw_column_missing(client, admin_override, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    fake_client._tables["room_prices"] = []
    fake_client._tables["bookings"] = []

    original_table = fake_client.table

    def table(name):
        if name != "rooms":
            return original_table(name)
        query = _ColumnMissingQuery(fake_client._tables["rooms"], on_delete=fake_client._on_delete("rooms"))
        fake_client.queries.setdefault("rooms", []).append(query)
        return query

    fake_client.table = table
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/hotel-1/rooms")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["id"] == "room-1"
    assert item["max_occupancy_raw"] is None  # dropped from the legacy field list, not fabricated


@pytest.mark.asyncio
async def test_list_rooms_no_price_rows_returns_null_lowest_price(client, admin_override, monkeypatch):
    room = _room_row(embedding=None)
    fake_client = _fake_client_for_room(room)
    fake_client._tables["room_prices"] = []
    fake_client._tables["bookings"] = []
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/hotel-1/rooms")

    item = response.json()["items"][0]
    assert item["lowest_price_30d"] is None
    assert item["embedding_state"] == "missing"


@pytest.mark.asyncio
async def test_list_rooms_lowest_price_is_min_across_30_day_window(client, admin_override, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    today = date.today()
    fake_client._tables["room_prices"] = [
        {"room_id": "room-1", "price": 1500000, "currency": "VND", "check_in_date": (today + timedelta(days=1)).isoformat(), "sold_out": False},
        {"room_id": "room-1", "price": 1200000, "currency": "VND", "check_in_date": (today + timedelta(days=5)).isoformat(), "sold_out": False},
        # Outside the 30-day window -- must not be considered.
        {"room_id": "room-1", "price": 100, "currency": "VND", "check_in_date": (today + timedelta(days=45)).isoformat(), "sold_out": False},
        # Sold out -- must not be considered.
        {"room_id": "room-1", "price": 50, "currency": "VND", "check_in_date": (today + timedelta(days=2)).isoformat(), "sold_out": True},
    ]
    fake_client._tables["bookings"] = []
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/hotel-1/rooms")

    item = response.json()["items"][0]
    assert item["lowest_price_30d"] == "1200000"
    assert item["currency"] == "VND"


@pytest.mark.asyncio
async def test_list_rooms_booking_count_includes_cancelled(client, admin_override, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    fake_client._tables["room_prices"] = []
    fake_client._tables["bookings"] = [
        {"room_id": "room-1", "status": "CANCELLED"},
        {"room_id": "room-1", "status": "CONFIRMED"},
        {"room_id": "other-room", "status": "CONFIRMED"},
    ]
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/hotels/hotel-1/rooms")

    assert response.json()["items"][0]["booking_count"] == 2


# ---------------------------------------------------------------------------
# POST /hotels/{hotel_id}/rooms
# ---------------------------------------------------------------------------


def _create_body(**overrides) -> dict:
    body = {
        "name": "Deluxe King",
        "max_guests": 2,
        "bed_description": "1 giường đôi lớn (King)",
        "room_size_sqm": 32,
        "view": "Nhìn ra thành phố",
        "room_facilities": ["air_conditioning"],
        "images": ["https://example.com/1.jpg"],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_create_room_succeeds_with_manual_source_and_null_embedding(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "hotel-1", "source_platform": "booking"}], "rooms": []}, rpc_results={"next_manual_room_source_id": 9000000001})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(rooms_module, "query_all_approved_amenities_by_ids", lambda ids: [SimpleNamespace(id="air_conditioning", scope="room")])

    response = await client.post("/api/v1/admin/hotels/hotel-1/rooms", json=_create_body())

    assert response.status_code == 201
    body = response.json()
    assert body["source_room_id"] == 9000000001
    assert body["embedding_state"] == "missing"

    inserted = fake_client.queries["rooms"][0]._inserted[0]
    assert inserted["hotel_id"] == "hotel-1"
    assert inserted["source_room_id"] == 9000000001
    assert inserted["embedding"] is None
    assert inserted["image_count"] == 1
    assert no_audit[0]["action"] == "room.create"


@pytest.mark.asyncio
async def test_create_room_two_in_a_row_get_increasing_source_room_id(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "hotel-1", "source_platform": "manual"}], "rooms": []})
    calls = iter([9000000001, 9000000002])
    fake_client.rpc = lambda name, params: _FakeRpc(_Response(next(calls)))  # type: ignore[method-assign]
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(rooms_module, "query_all_approved_amenities_by_ids", lambda ids: [])

    first = await client.post("/api/v1/admin/hotels/hotel-1/rooms", json=_create_body(room_facilities=[]))
    second = await client.post("/api/v1/admin/hotels/hotel-1/rooms", json=_create_body(room_facilities=[], name="Panorama Studio"))

    assert first.json()["source_room_id"] == 9000000001
    assert second.json()["source_room_id"] == 9000000002


@pytest.mark.asyncio
async def test_create_room_unknown_hotel_returns_404(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels/missing/rooms", json=_create_body(room_facilities=[]))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_room_invalid_facility_id_returns_422_and_no_write(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "hotel-1", "source_platform": "manual"}], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(rooms_module, "query_all_approved_amenities_by_ids", lambda ids: [])

    response = await client.post("/api/v1/admin/hotels/hotel-1/rooms", json=_create_body(room_facilities=["not_a_real_id"]))

    assert response.status_code == 422
    assert "rooms" not in fake_client.table_calls
    assert no_audit == []


@pytest.mark.asyncio
async def test_create_room_blank_name_returns_422(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [{"id": "hotel-1", "source_platform": "manual"}], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.post("/api/v1/admin/hotels/hotel-1/rooms", json=_create_body(name="   ", room_facilities=[]))

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /rooms/{room_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_room_bed_description_clears_embedding(client, admin_override, no_audit, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/rooms/room-1", json={"bed_description": "2 giường đơn"})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["bed_description"]
    assert body["rag_fields_changed"] == ["bed_description"]
    assert body["embedding_cleared"] is True
    assert body["embedding_state"] == "missing"
    update_payload = fake_client.queries["rooms"][1].update_payload
    assert update_payload["embedding"] is None
    assert update_payload["bed_description"] == "2 giường đơn"


@pytest.mark.asyncio
async def test_update_room_size_does_not_clear_embedding(client, admin_override, no_audit, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/rooms/room-1", json={"room_size_sqm": 40})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == ["room_size_sqm"]
    assert body["rag_fields_changed"] == []
    assert body["embedding_cleared"] is False
    assert body["embedding_state"] == "embedded"
    update_payload = fake_client.queries["rooms"][1].update_payload
    assert "embedding" not in update_payload


@pytest.mark.asyncio
async def test_update_room_images_recomputes_image_count(client, admin_override, monkeypatch):
    room = _room_row(images=["https://example.com/1.jpg"], image_count=1)
    fake_client = _fake_client_for_room(room)
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch(
        "/api/v1/admin/rooms/room-1", json={"images": ["https://example.com/1.jpg", "https://example.com/2.jpg"]}
    )

    assert response.status_code == 200
    update_payload = fake_client.queries["rooms"][1].update_payload
    assert update_payload["image_count"] == 2
    assert "embedding" not in update_payload  # images is not RAG-relevant


@pytest.mark.asyncio
async def test_update_room_facilities_reorder_only_is_not_a_change(client, admin_override, no_audit, monkeypatch):
    room = _room_row(room_facilities=["wifi", "minibar"])
    fake_client = _fake_client_for_room(room)
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/rooms/room-1", json={"room_facilities": ["minibar", "wifi"]})

    assert response.status_code == 200
    body = response.json()
    assert body["changed_fields"] == []
    assert body["embedding_cleared"] is False
    assert len(fake_client.queries["rooms"]) == 1  # only the current-row read
    assert no_audit == []


@pytest.mark.asyncio
async def test_update_room_invalid_facility_id_returns_422_and_no_write(client, admin_override, no_audit, monkeypatch):
    room = _room_row(room_facilities=["wifi"])
    fake_client = _fake_client_for_room(room)
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(rooms_module, "query_all_approved_amenities_by_ids", lambda ids: [])

    response = await client.patch("/api/v1/admin/rooms/room-1", json={"room_facilities": ["wifi", "not_a_real_id"]})

    assert response.status_code == 422
    assert len(fake_client.queries["rooms"]) == 1
    assert no_audit == []


@pytest.mark.asyncio
async def test_update_room_unknown_id_returns_404(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.patch("/api/v1/admin/rooms/missing", json={"name": "x"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /rooms/{room_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_room_without_bookings_succeeds(client, admin_override, no_audit, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    fake_client._tables["bookings"] = []
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.delete("/api/v1/admin/rooms/room-1")

    assert response.status_code == 204
    assert fake_client._tables["rooms"] == []
    assert no_audit[0]["action"] == "room.delete"


@pytest.mark.asyncio
async def test_delete_room_with_bookings_returns_409_and_keeps_room(client, admin_override, no_audit, monkeypatch):
    room = _room_row()
    fake_client = _fake_client_for_room(room)
    fake_client._tables["bookings"] = [
        {"room_id": "room-1", "status": "CANCELLED"},
        {"room_id": "room-1", "status": "CONFIRMED"},
    ]
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.delete("/api/v1/admin/rooms/room-1")

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "room_has_bookings"
    assert body["count"] == 2
    assert fake_client._tables["rooms"] == [room]
    assert no_audit == []


@pytest.mark.asyncio
async def test_delete_room_unknown_id_returns_404(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"hotels": [], "rooms": []})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.delete("/api/v1/admin/rooms/missing")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /room-facilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_room_facilities_filters_to_room_and_both_scopes(client, admin_override, monkeypatch):
    catalog = [
        SimpleNamespace(id="tv", label="TV", label_en="TV", category="room_comfort", scope="room"),
        SimpleNamespace(id="wifi", label="Wi-Fi", label_en="Wi-Fi", category="connectivity", scope="both"),
        SimpleNamespace(id="swimming_pool", label="Hồ bơi", label_en="Pool", category="wellness", scope="hotel"),
    ]
    monkeypatch.setattr(rooms_module, "query_approved_amenities", lambda: catalog)

    response = await client.get("/api/v1/admin/room-facilities")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert ids == {"tv", "wifi"}


# ---------------------------------------------------------------------------
# POST /rooms/{room_id}/images/upload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_room_image_succeeds_and_returns_public_url(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.post(
        "/api/v1/admin/rooms/room-1/images/upload",
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fakejpegbytes", "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"].startswith("https://fake.supabase.co/storage/v1/object/public/hotel-images/rooms/room-1/")
    assert body["url"].endswith(".jpg")

    bucket = fake_client.storage.buckets["hotel-images"]
    assert len(bucket.uploaded) == 1
    uploaded_path, uploaded_bytes, options = bucket.uploaded[0]
    assert uploaded_path.startswith("rooms/room-1/")
    assert uploaded_bytes == b"\xff\xd8\xff\xe0fakejpegbytes"
    assert options["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_upload_room_image_rejects_unsupported_type(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)

    response = await client.post(
        "/api/v1/admin/rooms/room-1/images/upload",
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "unsupported_image_type"
    assert fake_client.storage.buckets == {}


@pytest.mark.asyncio
async def test_upload_room_image_rejects_oversized_file(client, admin_override, monkeypatch):
    fake_client = _FakeClient({})
    monkeypatch.setattr(rooms_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(rooms_module, "_MAX_UPLOAD_BYTES", 10)

    response = await client.post(
        "/api/v1/admin/rooms/room-1/images/upload",
        files={"file": ("photo.jpg", b"x" * 100, "image/jpeg")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "image_too_large"
    assert fake_client.storage.buckets == {}


# ---------------------------------------------------------------------------
# DAG template guard -- rooms.py must never change embed_supabase_dag.py's
# `_build_text`/`TABLE_COLUMNS["rooms"]` (plan's Success Criteria: "git diff
# xác nhận"). Parses the literal DAG source instead of importing it --
# airflow isn't installed in this venv (see test_admin_hotels.py's
# `_dag_hotel_table_columns` for the same constraint) -- so a DAG column-list
# edit that isn't mirrored in RAG_FIELDS_ROOM fails a test instead of
# silently drifting.
# ---------------------------------------------------------------------------


def _dag_room_table_columns() -> list[str]:
    path = _BACKEND_ROOT / "src" / "airflow" / "dags" / "data_pipeline" / "embed_supabase_dag.py"
    match = re.search(r'"rooms":\s*"([^"]+)"', path.read_text(encoding="utf-8"))
    assert match, "TABLE_COLUMNS['rooms'] not found in embed_supabase_dag.py"
    columns = match.group(1).split(",")
    columns.remove("id")
    return columns


def test_rooms_rag_fields_match_dag_table_columns():
    assert list(rooms_module.RAG_FIELDS_ROOM) == _dag_room_table_columns()
