"""Tests for admin B6 (Quản lý giá phòng theo đêm) -- src/api/admin/room_prices.py
(phase-11-room-prices.md). Self-contained in-memory postgrest fake (not
reused from test_admin_rooms.py's fixtures -- this module doesn't need
storage/booking-count concerns, but does need `.is_()` and a
`admin_upsert_room_prices` RPC that actually performs the natural-key
upsert against a fake table, which the other module's canned-response
`_FakeRpc` cannot do).

`match_hotels_with_rooms`/`place_details._average_price` themselves are real
Postgres SQL/RPCs -- not exercised here (a fake in-memory client cannot run
SQL). Phase 1's fix (`count(DISTINCT rp.check_in_date)`) was verified
directly against `database_schema.sql` during scouting for this phase; this
file instead proves the write-path invariants that make that fix effective:
one row per night, `source_url=NULL` fixed, one upsert call regardless of
night count.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.api.admin import room_prices as room_prices_module
from src.auth import AdminUser, require_admin
from src.main import app


class _Response:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._gte: list[tuple[str, object]] = []
        self._lt: list[tuple[str, object]] = []
        self._is: list[tuple[str, object]] = []
        self._deleting = False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def gte(self, field, value):
        self._gte.append((field, value))
        return self

    def lt(self, field, value):
        self._lt.append((field, value))
        return self

    def is_(self, field, value):
        self._is.append((field, value))
        return self

    def limit(self, _n):
        return self

    def delete(self):
        self._deleting = True
        return self

    def _matches(self, row) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, value in self._gte:
            if row.get(field) is None or row.get(field) < value:
                return False
        for field, value in self._lt:
            if row.get(field) is None or row.get(field) >= value:
                return False
        for field, value in self._is:
            expects_none = value in (None, "null")
            if (row.get(field) is None) != expects_none:
                return False
        return True

    def execute(self):
        matched = [row for row in self._rows if self._matches(row)]
        if self._deleting:
            for row in matched:
                self._rows.remove(row)
        return _Response(matched)


class _FakeRpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Response(self._data)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.rpc_calls: list[tuple[str, dict]] = []

    def table(self, name):
        return _FakeQuery(self._tables.setdefault(name, []))

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        if name == "admin_upsert_room_prices":
            return _FakeRpc([self._upsert_room_prices(params)])
        raise AssertionError(f"unexpected rpc call: {name}")

    def _upsert_room_prices(self, params: dict) -> dict:
        """Mirrors admin_upsert_room_prices' ON CONFLICT semantics:
        matches on (room_id, check_in_date, check_out_date) among rows with
        source_url IS NULL -- an admin write never touches an OTA row."""
        rows = self._tables.setdefault("room_prices", [])
        room_id = params["p_room_id"]
        created = updated = 0
        for night in params["p_nights"]:
            check_out = (date.fromisoformat(night) + timedelta(days=1)).isoformat()
            existing = next(
                (
                    r
                    for r in rows
                    if r["room_id"] == room_id and r["check_in_date"] == night and r["check_out_date"] == check_out and r.get("source_url") is None
                ),
                None,
            )
            if existing:
                existing.update(price=params["p_price"], currency=params["p_currency"], sold_out=params["p_sold_out"], crawled_at="2026-08-24T12:00:00")
                updated += 1
            else:
                rows.append(
                    {
                        "id": f"price-{len(rows)}",
                        "room_id": room_id,
                        "check_in_date": night,
                        "check_out_date": check_out,
                        "price": params["p_price"],
                        "currency": params["p_currency"],
                        "sold_out": params["p_sold_out"],
                        "source_url": None,
                        "crawled_at": "2026-08-24T12:00:00",
                    }
                )
                created += 1
        return {"written": len(params["p_nights"]), "created": created, "updated": updated}


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def no_audit(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(room_prices_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


def _room_row(**overrides) -> dict:
    row = {
        "id": "room-1",
        "hotel_id": "hotel-1",
        "name": "Deluxe King",
        "available_room_count": 5,
        "hotels": {"name": "Silk Path Hà Nội", "source_platform": "manual"},
    }
    row.update(overrides)
    return row


def _fake_client(room: dict, *, room_prices=None, occupancy=None) -> _FakeClient:
    return _FakeClient(
        {
            "rooms": [room],
            "room_prices": list(room_prices or []),
            "room_night_occupancy": list(occupancy or []),
        }
    )


def _price_row(night: str, price: str, *, currency="VND", source_url=None, sold_out=False, crawled_at="2026-08-01T00:00:00") -> dict:
    return {
        "room_id": "room-1",
        "check_in_date": night,
        "check_out_date": (date.fromisoformat(night) + timedelta(days=1)).isoformat(),
        "price": price,
        "currency": currency,
        "sold_out": sold_out,
        "source_url": source_url,
        "crawled_at": crawled_at,
    }


def _dates(start: str, n: int) -> list[str]:
    base = date.fromisoformat(start)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


# ---------------------------------------------------------------------------
# PUT /rooms/{room_id}/prices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_12_nights_creates_12_rows_with_check_out_plus_one(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(_room_row())
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    dates = _dates("2026-08-20", 12)
    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": dates, "price": "1500000.00", "currency": "VND"})

    assert response.status_code == 200
    body = response.json()
    assert body == {"written": 12, "created": 12, "updated": 0}
    rows = fake_client._tables["room_prices"]
    assert len(rows) == 12
    for row in rows:
        assert row["check_out_date"] == (date.fromisoformat(row["check_in_date"]) + timedelta(days=1)).isoformat()
        assert row["source_url"] is None


@pytest.mark.asyncio
async def test_put_same_12_nights_twice_still_12_rows_not_duplicated(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(_room_row())
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)
    dates = _dates("2026-08-20", 12)

    await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": dates, "price": "1500000.00", "currency": "VND"})
    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": dates, "price": "1600000.00", "currency": "VND"})

    assert response.json() == {"written": 12, "created": 0, "updated": 12}
    assert len(fake_client._tables["room_prices"]) == 12
    assert all(row["price"] == "1600000.00" for row in fake_client._tables["room_prices"])


@pytest.mark.asyncio
async def test_put_366_nights_issues_exactly_one_rpc_call(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(_room_row())
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.put(
        "/api/v1/admin/rooms/room-1/prices", json={"dates": _dates("2026-01-01", 366), "price": "1000000.00", "currency": "VND"}
    )

    assert response.status_code == 200
    assert response.json()["written"] == 366
    assert len(fake_client.rpc_calls) == 1


@pytest.mark.asyncio
async def test_put_writes_one_summarized_audit_row(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(_room_row())
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    await client.put(
        "/api/v1/admin/rooms/room-1/prices", json={"dates": _dates("2026-08-20", 12), "price": "1500000.00", "currency": "VND", "sold_out": True}
    )

    assert len(no_audit) == 1
    call = no_audit[0]
    assert call["action"] == "price.set"
    assert call["entity_id"] == "room-1"
    assert call["after"] == {
        "from": "2026-08-20",
        "to": "2026-08-31",
        "nights": 12,
        "price": "1500000.00",
        "currency": "VND",
        "sold_out": True,
    }


@pytest.mark.asyncio
async def test_put_empty_dates_returns_422(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": [], "price": "100.00", "currency": "VND"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_too_many_dates_returns_422(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.put(
        "/api/v1/admin/rooms/room-1/prices", json={"dates": _dates("2026-01-01", 367), "price": "100.00", "currency": "VND"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_negative_price_returns_422(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": ["2026-08-20"], "price": "-1", "currency": "VND"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_price_over_decimal_12_2_ceiling_returns_422_not_500(client, admin_override, no_audit, monkeypatch):
    # room_prices.price is DECIMAL(12,2) -- without a matching Pydantic
    # ceiling this used to reach the RPC and 500 on Postgres' own "numeric
    # field overflow" instead of a clean, actionable 422.
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": ["2026-08-20"], "price": "99999999999999", "currency": "VND"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_dates_dedupe_before_max_length_check(client, admin_override, no_audit, monkeypatch):
    # 400 raw entries with only 300 unique dates must not 422 on the raw
    # (pre-dedupe) count -- the max_length gate is about how many nights
    # actually get written, not how many the caller happened to send.
    fake_client = _fake_client(_room_row())
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)
    unique_dates = _dates("2026-01-01", 300)
    padded = unique_dates + unique_dates[:100]  # 400 entries, 300 unique
    assert len(padded) == 400

    response = await client.put("/api/v1/admin/rooms/room-1/prices", json={"dates": padded, "price": "1000000.00", "currency": "VND"})

    assert response.status_code == 200
    assert response.json()["written"] == 300


@pytest.mark.asyncio
async def test_put_unknown_room_returns_404(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _FakeClient({"rooms": []}))
    response = await client.put("/api/v1/admin/rooms/missing/prices", json={"dates": ["2026-08-20"], "price": "100.00", "currency": "VND"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /rooms/{room_id}/prices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prices_unknown_room_returns_404(client, admin_override, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _FakeClient({"rooms": []}))
    response = await client.get("/api/v1/admin/rooms/missing/prices?from=2026-08-01&to=2026-08-31")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_prices_night_without_a_row_is_absent(client, admin_override, monkeypatch):
    fake_client = _fake_client(_room_row(), room_prices=[_price_row("2026-08-05", "1200000.00")])
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    nights = response.json()["nights"]
    assert [n["date"] for n in nights] == ["2026-08-05"]


@pytest.mark.asyncio
async def test_get_prices_admin_row_outranks_older_ota_row_by_crawled_at(client, admin_override, monkeypatch):
    fake_client = _fake_client(
        _room_row(),
        room_prices=[
            _price_row("2026-08-05", "1200000.00", source_url="https://ota.example/x", crawled_at="2026-08-01T00:00:00"),
            _price_row("2026-08-05", "1500000.00", source_url=None, crawled_at="2026-08-10T00:00:00"),
        ],
    )
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    night = response.json()["nights"][0]
    assert night["price"] == "1500000.00"
    assert night["source"] == "manual"
    assert night["row_count"] == 2


@pytest.mark.asyncio
async def test_get_prices_available_from_occupancy_view_falls_back_to_base_capacity(client, admin_override, monkeypatch):
    fake_client = _fake_client(
        _room_row(available_room_count=5),
        room_prices=[_price_row("2026-08-05", "1200000.00"), _price_row("2026-08-06", "1200000.00")],
        occupancy=[{"room_id": "room-1", "night": "2026-08-05", "units_available": 0}],
    )
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    by_date = {n["date"]: n for n in response.json()["nights"]}
    assert by_date["2026-08-05"]["available"] == 0  # sold_out=false + available=0 -> "Đã kín" (L50)
    assert by_date["2026-08-06"]["available"] == 5  # no occupancy row -> full base capacity


@pytest.mark.asyncio
async def test_get_prices_ranges_merge_equal_consecutive_nights_and_split_on_change(client, admin_override, monkeypatch):
    rows = [_price_row(d, "1200000.00") for d in _dates("2026-08-01", 14)]
    fake_client = _fake_client(_room_row(), room_prices=rows)
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-15")
    ranges = response.json()["ranges"]
    assert ranges == [
        {"from": "2026-08-01", "to": "2026-08-15", "nights": 14, "price": "1200000.00", "currency": "VND", "sold_out": False, "source": "manual", "deletable": True}
    ]


@pytest.mark.asyncio
async def test_get_prices_ranges_split_when_middle_night_price_differs(client, admin_override, monkeypatch):
    rows = [_price_row(d, "1200000.00") for d in _dates("2026-08-01", 14)]
    middle = 7
    rows[middle] = _price_row("2026-08-08", "1900000.00")
    fake_client = _fake_client(_room_row(), room_prices=rows)
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-15")
    ranges = response.json()["ranges"]

    assert len(ranges) == 3
    assert ranges[0]["nights"] == 7
    assert ranges[1] == {
        "from": "2026-08-08", "to": "2026-08-09", "nights": 1, "price": "1900000.00", "currency": "VND", "sold_out": False, "source": "manual", "deletable": True
    }
    assert ranges[2]["nights"] == 6


@pytest.mark.asyncio
async def test_get_prices_ranges_split_on_currency_change_even_when_price_number_matches(client, admin_override, monkeypatch):
    rows = [_price_row(d, "100.00", currency="VND") for d in _dates("2026-08-01", 3)] + [
        _price_row(d, "100.00", currency="USD") for d in _dates("2026-08-04", 3)
    ]
    fake_client = _fake_client(_room_row(), room_prices=rows)
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-07")
    ranges = response.json()["ranges"]

    assert len(ranges) == 2
    assert ranges[0]["currency"] == "VND"
    assert ranges[1]["currency"] == "USD"


@pytest.mark.asyncio
async def test_get_prices_available_clamps_negative_and_null_like_get_room_availability(client, admin_override, monkeypatch):
    # room_night_occupancy.units_available is unclamped (unlike the
    # get_room_availability RPC it's meant to mirror) -- an overbooked room
    # reads negative, and a NULL available_room_count propagates as NULL.
    fake_client = _fake_client(
        _room_row(available_room_count=None),
        room_prices=[_price_row("2026-08-05", "1200000.00"), _price_row("2026-08-06", "1200000.00")],
        occupancy=[{"room_id": "room-1", "night": "2026-08-05", "units_available": -3}],
    )
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    by_date = {n["date"]: n for n in response.json()["nights"]}
    assert by_date["2026-08-05"]["available"] == 0  # overbooked (-3) clamps to 0, not negative
    assert by_date["2026-08-06"]["available"] is None  # no occupancy row + NULL base capacity -> None, not 0


@pytest.mark.asyncio
async def test_get_prices_range_too_wide_returns_422(client, admin_override, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-01-01&to=2027-06-01")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_prices_range_built_only_from_ota_rows_is_not_deletable(client, admin_override, monkeypatch):
    rows = [_price_row(d, "1200000.00", source_url="https://ota.example/x") for d in _dates("2026-08-01", 5)]
    fake_client = _fake_client(_room_row(), room_prices=rows)
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-06")
    ranges = response.json()["ranges"]

    assert len(ranges) == 1
    assert ranges[0]["deletable"] is False
    assert ranges[0]["source"] == "pipeline"


@pytest.mark.asyncio
async def test_get_prices_invalid_range_returns_422(client, admin_override, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.get("/api/v1/admin/rooms/room-1/prices?from=2026-08-31&to=2026-08-01")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /rooms/{room_id}/prices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_only_admin_rows_leaves_ota_row_and_returns_zero_when_none_admin(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(
        _room_row(),
        room_prices=[
            _price_row("2026-08-05", "1200000.00", source_url="https://ota.example/x"),
        ],
    )
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.delete("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    assert response.json() == {"deleted": 0}
    assert len(fake_client._tables["room_prices"]) == 1  # OTA row untouched
    assert no_audit == []


@pytest.mark.asyncio
async def test_delete_removes_admin_row_keeps_ota_row_for_same_night(client, admin_override, no_audit, monkeypatch):
    fake_client = _fake_client(
        _room_row(),
        room_prices=[
            _price_row("2026-08-05", "1200000.00", source_url="https://ota.example/x"),
            _price_row("2026-08-05", "1500000.00", source_url=None),
        ],
    )
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: fake_client)

    response = await client.delete("/api/v1/admin/rooms/room-1/prices?from=2026-08-01&to=2026-08-08")

    assert response.json() == {"deleted": 1}
    remaining = fake_client._tables["room_prices"]
    assert len(remaining) == 1
    assert remaining[0]["source_url"] == "https://ota.example/x"
    assert len(no_audit) == 1
    assert no_audit[0]["action"] == "price.delete"


@pytest.mark.asyncio
async def test_delete_unknown_room_returns_404(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _FakeClient({"rooms": []}))
    response = await client.delete("/api/v1/admin/rooms/missing/prices?from=2026-08-01&to=2026-08-08")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_range_too_wide_returns_422(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(room_prices_module, "get_supabase_client", lambda: _fake_client(_room_row()))
    response = await client.delete("/api/v1/admin/rooms/room-1/prices?from=2026-01-01&to=2027-06-01")
    assert response.status_code == 422