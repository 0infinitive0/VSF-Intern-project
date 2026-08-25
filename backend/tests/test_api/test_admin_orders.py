"""Tests for admin D1 (Danh sách đơn hàng) -- src/api/admin/orders.py.

Uses a small fake postgrest-style query builder (same shape as
test_admin_hotels.py's `_FakeQuery`, extended with the filter methods this
module actually calls: `gte`/`lt`/`gt`/`lte`, `contains`, and a minimal
`.or_()` ILIKE matcher).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.api.admin import orders as orders_module
from src.auth import AdminUser, require_admin
from src.main import app


class _Response:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


def _comparable(value):
    """Parses an ISO datetime string to an aware `datetime` for comparison
    (falls back to the raw value for plain dates/strings/numbers). Needed
    because orders.py now sends `+07:00`-offset bounds (`_vn_day_start`)
    that don't lexicographically compare against `Z`-suffixed fixture
    timestamps, even though they compare correctly as instants."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _parse_or_ilike(expr: str, row: dict) -> bool:
    """Matches this module's only `.or_()` shape: `field.ilike.%term%,...`."""
    for clause in expr.split(","):
        field, _op, pattern = clause.split(".", 2)
        term = pattern.strip("%").lower()
        value = str(row.get(field) or "").lower()
        if term in value:
            return True
    return False


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._eq: list[tuple[str, object]] = []
        self._gte: list[tuple[str, object]] = []
        self._lt: list[tuple[str, object]] = []
        self._lte: list[tuple[str, object]] = []
        self._gt: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._contains: list[tuple[str, list]] = []
        self._or: str | None = None
        self._order_col: str | None = None
        self._order_desc = False
        self._start: int | None = None
        self._end: int | None = None
        self._count_requested = False

    def select(self, *_args, count=None, **_kwargs):
        if count is not None:
            self._count_requested = True
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

    def lte(self, field, value):
        self._lte.append((field, value))
        return self

    def gt(self, field, value):
        self._gt.append((field, value))
        return self

    def in_(self, field, values):
        self._in.append((field, list(values)))
        return self

    def contains(self, field, values):
        self._contains.append((field, list(values)))
        return self

    def or_(self, expr):
        self._or = expr
        return self

    def order(self, column, *, desc=False, **_kwargs):
        self._order_col = column
        self._order_desc = desc
        return self

    def limit(self, n):
        self._start, self._end = 0, n - 1
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def _matches(self, row) -> bool:
        for field, value in self._eq:
            if row.get(field) != value:
                return False
        for field, value in self._gte:
            if row.get(field) is None or _comparable(row[field]) < _comparable(value):
                return False
        for field, value in self._lt:
            if row.get(field) is None or _comparable(row[field]) >= _comparable(value):
                return False
        for field, value in self._lte:
            if row.get(field) is None or _comparable(row[field]) > _comparable(value):
                return False
        for field, value in self._gt:
            if row.get(field) is None or _comparable(row[field]) <= _comparable(value):
                return False
        for field, values in self._in:
            if row.get(field) not in values:
                return False
        for field, values in self._contains:
            row_values = row.get(field) or []
            if not all(v in row_values for v in values):
                return False
        if self._or and not _parse_or_ilike(self._or, row):
            return False
        return True

    def execute(self):
        rows = [row for row in self._rows if self._matches(row)]
        if self._order_col:
            rows.sort(key=lambda r: (r.get(self._order_col) is None, r.get(self._order_col)), reverse=self._order_desc)
        total = len(rows)
        if self._start is not None:
            rows = rows[self._start : self._end + 1]
        return _Response(rows, count=total if self._count_requested else None)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.table_calls: list[str] = []

    def table(self, name):
        self.table_calls.append(name)
        return _FakeQuery(self._tables.get(name, []))


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def no_audit(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(orders_module, "write_audit", lambda actor, **kwargs: calls.append({"actor": actor, **kwargs}))
    return calls


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_short_code_uses_last_5_hex_chars_uppercase():
    assert orders_module._short_code("DH", "abcdef12-3456-7890-abcd-ef123f2a1000") == "DH-A1000"


def test_money_str_normalizes_decimal_shape():
    assert orders_module._money_str(1850000) == "1850000"
    assert orders_module._money_str("1850000.00") == "1850000.00"


def test_row_to_order_maps_view_row():
    row = {
        "payment_id": "11111111-1111-1111-1111-111111111111",
        "guest_name": "Trần Quốc Bảo",
        "guest_email": "bao.tran@vsf.dev",
        "guest_phone": "0905218447",
        "hotel_ids": ["h1"],
        "hotel_names": ["Silk Path Hà Nội"],
        "check_in_date": "2026-08-25",
        "check_out_date": "2026-08-28",
        "room_count": 2,
        "booking_count": 2,
        "amount": "1850000.00",
        "currency": "VND",
        "booking_status": "PENDING",
        "payment_status": "PAID",
        "needs_attention": True,
        "earliest_expires_at": None,
        "created_at": "2026-08-24T08:47:00Z",
    }
    order = orders_module._row_to_order(row)
    assert order.order_code == "DH-11111"
    assert order.needs_attention is True
    assert order.amount == "1850000.00"


def test_row_to_unpaid_booking_guest_label_present_when_ref_set():
    row = {
        "booking_id": "22222222-2222-2222-2222-222222222222",
        "temporary_user_ref": "guest-abcdef01",
        "hotel_name": "Vinpearl Resort Nha Trang",
        "room_name": "Ocean Suite",
        "check_in_date": "2026-08-30",
        "check_out_date": "2026-09-02",
        "room_count": 3,
        "total_amount": "12900000.00",
        "currency": "VND",
        "status": "RESERVED",
        "expires_at": "2026-08-24T10:46:00Z",
        "created_at": "2026-08-24T10:16:00Z",
        "session_id": "ct-90218",
    }
    booking = orders_module._row_to_unpaid_booking(row)
    assert booking.hold_code == "GC-22222"
    assert booking.guest_label == "Khách ẩn danh · guest-ab"


def test_row_to_unpaid_booking_guest_label_none_when_ref_missing():
    row = {
        "booking_id": "33333333-3333-3333-3333-333333333333",
        "temporary_user_ref": None,
        "hotel_name": None,
        "room_name": None,
        "check_in_date": "2026-08-30",
        "check_out_date": "2026-09-02",
        "room_count": 1,
        "total_amount": None,
        "currency": None,
        "status": "PENDING",
        "expires_at": None,
        "created_at": "2026-08-24T10:16:00Z",
        "session_id": None,
    }
    booking = orders_module._row_to_unpaid_booking(row)
    assert booking.guest_label is None
    assert booking.total_amount is None


# ---------------------------------------------------------------------------
# GET /api/v1/admin/orders?tab=paid
# ---------------------------------------------------------------------------


def _order_row(**overrides) -> dict:
    row = {
        "payment_id": "11111111-1111-1111-1111-111111111111",
        "guest_name": "Trần Quốc Bảo",
        "guest_email": "bao.tran@vsf.dev",
        "guest_phone": "0905218447",
        "hotel_ids": ["h1"],
        "hotel_names": ["Silk Path Hà Nội"],
        "check_in_date": "2026-08-25",
        "check_out_date": "2026-08-28",
        "room_count": 2,
        "booking_count": 2,
        "amount": "1850000.00",
        "currency": "VND",
        "booking_status": "PENDING",
        "payment_status": "PAID",
        "needs_attention": False,
        "earliest_expires_at": None,
        "created_at": "2026-08-24T08:47:00Z",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_list_orders_paid_returns_items_and_total(client, admin_override, monkeypatch):
    rows = [_order_row(payment_id="p1"), _order_row(payment_id="p2", payment_status="PENDING")]
    fake_client = _FakeClient({"admin_orders": rows})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["payment_id"] for item in body["items"]} == {"p1", "p2"}


@pytest.mark.asyncio
async def test_list_orders_paid_filters_by_hotel_id_via_contains(client, admin_override, monkeypatch):
    rows = [_order_row(payment_id="p1", hotel_ids=["h1"]), _order_row(payment_id="p2", hotel_ids=["h2"])]
    fake_client = _FakeClient({"admin_orders": rows})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders", params={"hotel_id": "h1"})

    assert response.status_code == 200
    body = response.json()
    assert [item["payment_id"] for item in body["items"]] == ["p1"]


@pytest.mark.asyncio
async def test_list_orders_paid_search_matches_normalized_phone(client, admin_override, monkeypatch):
    rows = [_order_row(payment_id="p1", guest_phone="0905218447"), _order_row(payment_id="p2", guest_phone="0900000000")]
    fake_client = _FakeClient({"admin_orders": rows})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    # +84 905 218 447 should normalize to 0905218447 and match p1 only.
    response = await client.get("/api/v1/admin/orders", params={"q": "+84 905 218 447"})

    assert response.status_code == 200
    body = response.json()
    assert [item["payment_id"] for item in body["items"]] == ["p1"]


@pytest.mark.asyncio
async def test_list_orders_rejects_from_after_to(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"admin_orders": []})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders", params={"from": "2026-08-24", "to": "2026-08-18"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_orders_paid_csv_ignores_pagination(client, admin_override, monkeypatch):
    rows = [_order_row(payment_id=f"p{i}") for i in range(3)]
    fake_client = _FakeClient({"admin_orders": rows})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders", params={"format": "csv", "page_size": 1})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text
    assert body.count("\n") >= 4  # header + 3 data rows (+ trailing newline)


# ---------------------------------------------------------------------------
# GET /api/v1/admin/orders?tab=unpaid
# ---------------------------------------------------------------------------


def _unpaid_row(**overrides) -> dict:
    row = {
        "booking_id": "22222222-2222-2222-2222-222222222222",
        "status": "RESERVED",
        "check_in_date": "2026-08-30",
        "check_out_date": "2026-09-02",
        "room_count": 1,
        "total_amount": "1000000.00",
        "currency": "VND",
        "expires_at": None,
        "created_at": "2026-08-24T10:16:00Z",
        "session_id": "ct-1",
        "temporary_user_ref": "guest-ref-1",
        "hotel_name": "Vinpearl Resort Nha Trang",
        "room_name": "Ocean Suite",
        "hotel_id": "h1",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_list_orders_unpaid_counts_expiring_within_30_minutes(client, admin_override, monkeypatch):
    now = datetime.now(timezone.utc)
    soon = (now + timedelta(minutes=10)).isoformat()
    far = (now + timedelta(hours=5)).isoformat()
    rows = [_unpaid_row(booking_id="b1", expires_at=soon), _unpaid_row(booking_id="b2", expires_at=far)]
    fake_client = _FakeClient({"admin_unpaid_bookings": rows})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders", params={"tab": "unpaid"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["expiring_count"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/admin/orders/holds/release-expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_expired_holds_only_touches_already_expired_rows(client, admin_override, no_audit, monkeypatch):
    now = datetime.now(timezone.utc)
    expired_id = "aaaaaaaa-0000-0000-0000-000000000001"
    live_id = "bbbbbbbb-0000-0000-0000-000000000002"
    expired = _unpaid_row(booking_id=expired_id, status="RESERVED", expires_at=(now - timedelta(minutes=5)).isoformat())
    still_live = _unpaid_row(booking_id=live_id, status="RESERVED", expires_at=(now + timedelta(minutes=30)).isoformat())
    fake_client = _FakeClient({"admin_unpaid_bookings": [expired, still_live]})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    cancelled: list[str] = []

    def fake_cancel_booking(*, booking_id, temporary_user_ref):
        cancelled.append(str(booking_id))
        return {"id": str(booking_id), "status": "CANCELLED"}

    monkeypatch.setattr(orders_module, "cancel_booking", fake_cancel_booking)

    response = await client.post("/api/v1/admin/orders/holds/release-expired")

    assert response.status_code == 200
    body = response.json()
    assert body == {"released": 1, "skipped": 0}
    assert cancelled == [expired_id]


@pytest.mark.asyncio
async def test_release_expired_holds_counts_failures_as_skipped(client, admin_override, no_audit, monkeypatch):
    now = datetime.now(timezone.utc)
    expired = _unpaid_row(booking_id="aaaaaaaa-0000-0000-0000-000000000001", status="RESERVED", expires_at=(now - timedelta(minutes=5)).isoformat())
    fake_client = _FakeClient({"admin_unpaid_bookings": [expired]})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def failing_cancel_booking(*, booking_id, temporary_user_ref):
        raise RuntimeError("booking_operation_failed")

    monkeypatch.setattr(orders_module, "cancel_booking", failing_cancel_booking)

    response = await client.post("/api/v1/admin/orders/holds/release-expired")

    assert response.status_code == 200
    assert response.json() == {"released": 0, "skipped": 1}


# ---------------------------------------------------------------------------
# GET /api/v1/admin/orders/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_stats_matches_hand_computed_values(client, admin_override, monkeypatch):
    from zoneinfo import ZoneInfo

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    today = datetime.now(vn_tz).date()
    today_vn_morning = datetime(today.year, today.month, today.day, 8, 0, tzinfo=vn_tz).isoformat()
    today_vn_evening = datetime(today.year, today.month, today.day, 20, 0, tzinfo=vn_tz).isoformat()
    payments = [
        # 3 orders today, only 2 PAID -- exercises L5's "divide by ALL
        # orders today, not just paid" and a non-divisible amount so a
        # rounding regression (H1) can't hide behind an evenly-divisible
        # fixture the way the previous version of this test did.
        {"id": "pay1", "amount": "1000000.00", "status": "PAID", "created_at": today_vn_morning},
        {"id": "pay2", "amount": "700000.00", "status": "PAID", "created_at": today_vn_evening},
        {"id": "pay3", "amount": "2000000.00", "status": "PENDING", "created_at": today_vn_morning},
        {"id": "pay4", "amount": "500000.00", "status": "PENDING", "created_at": "2026-01-01T09:00:00Z"},
    ]
    bookings = [
        {"id": "b1", "status": "RESERVED", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()},
    ]
    fake_client = _FakeClient({"payments": payments, "bookings": bookings})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["orders_today"] == 3
    assert body["revenue_today"] == "1700000.00"
    # 1,700,000 / 3 = 566,666.666... -> rounds to 566,666.67, not a value a
    # naive `str(Decimal(...))` would produce.
    assert body["avg_order_value"] == "566666.67"
    assert body["pending_count"] == 2
    assert body["expiring_holds_30m"] == 1
