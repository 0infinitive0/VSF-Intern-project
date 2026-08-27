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
        self._neq: list[tuple[str, object]] = []
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

    def neq(self, field, value):
        self._neq.append((field, value))
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
        for field, value in self._neq:
            if row.get(field) == value:
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
    assert orders_module.short_code("DH", "abcdef12-3456-7890-abcd-ef123f2a1000") == "DH-A1000"


def test_money_str_normalizes_decimal_shape():
    assert orders_module.money_str(1850000) == "1850000"
    assert orders_module.money_str("1850000.00") == "1850000.00"


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


def _stub_mark_payment_failed(monkeypatch):
    calls: list[dict] = []

    def fake(*, payment_id, vnp_response_code, status="FAILED"):
        calls.append({"payment_id": str(payment_id), "vnp_response_code": vnp_response_code, "status": status})
        return {"id": str(payment_id), "status": status}

    monkeypatch.setattr(orders_module.payment_service, "mark_payment_failed", fake)
    return calls


@pytest.mark.asyncio
async def test_release_expired_holds_settles_stalled_checkout_with_lapsed_hold(client, admin_override, no_audit, monkeypatch):
    now = datetime.now(timezone.utc)
    payment_id = "cccccccc-0000-0000-0000-000000000001"
    booking_id = "dddddddd-0000-0000-0000-000000000002"
    admin_orders = [{
        "payment_id": payment_id,
        "payment_status": "PENDING",
        "booking_status": "RESERVED",
        "earliest_expires_at": (now - timedelta(minutes=5)).isoformat(),
    }]
    payments = [{"id": payment_id, "status": "PENDING", "booking_ids": [booking_id], "temporary_user_ref": "guest-ref-9"}]
    fake_client = _FakeClient({"admin_unpaid_bookings": [], "admin_orders": admin_orders, "payments": payments})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    cancelled: list[str] = []
    monkeypatch.setattr(orders_module, "cancel_booking", lambda *, booking_id, temporary_user_ref: cancelled.append(str(booking_id)))
    mpf_calls = _stub_mark_payment_failed(monkeypatch)

    response = await client.post("/api/v1/admin/orders/holds/release-expired")

    assert response.status_code == 200
    assert response.json() == {"released": 1, "skipped": 0}
    assert cancelled == [booking_id]
    assert mpf_calls == [{"payment_id": payment_id, "vnp_response_code": "HOLD_EXPIRED", "status": "CANCELLED"}]


@pytest.mark.asyncio
async def test_release_expired_holds_settles_orphaned_pending_payment(client, admin_override, no_audit, monkeypatch):
    """Bookings already CANCELLED, only the PENDING payment row is left."""
    payment_id = "cccccccc-0000-0000-0000-000000000003"
    admin_orders = [{
        "payment_id": payment_id,
        "payment_status": "PENDING",
        "booking_status": "CANCELLED",
        "earliest_expires_at": None,
    }]
    payments = [{"id": payment_id, "status": "PENDING", "booking_ids": ["b-old"], "temporary_user_ref": "r"}]
    fake_client = _FakeClient({"admin_unpaid_bookings": [], "admin_orders": admin_orders, "payments": payments})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    cancelled: list[str] = []
    monkeypatch.setattr(orders_module, "cancel_booking", lambda *, booking_id, temporary_user_ref: cancelled.append(str(booking_id)))
    mpf_calls = _stub_mark_payment_failed(monkeypatch)

    response = await client.post("/api/v1/admin/orders/holds/release-expired")

    assert response.status_code == 200
    assert response.json() == {"released": 0, "skipped": 0}
    assert cancelled == []  # rollup is CANCELLED, no live booking to cancel
    assert [c["status"] for c in mpf_calls] == ["CANCELLED"]


@pytest.mark.asyncio
async def test_release_expired_holds_leaves_stalled_checkout_whose_hold_is_still_live(client, admin_override, no_audit, monkeypatch):
    now = datetime.now(timezone.utc)
    admin_orders = [{
        "payment_id": "cccccccc-0000-0000-0000-000000000004",
        "payment_status": "PENDING",
        "booking_status": "RESERVED",
        "earliest_expires_at": (now + timedelta(minutes=20)).isoformat(),
    }]
    fake_client = _FakeClient({"admin_unpaid_bookings": [], "admin_orders": admin_orders, "payments": []})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(orders_module, "cancel_booking", lambda **_: None)
    mpf_calls = _stub_mark_payment_failed(monkeypatch)

    response = await client.post("/api/v1/admin/orders/holds/release-expired")

    assert response.status_code == 200
    assert response.json() == {"released": 0, "skipped": 0}
    assert mpf_calls == []


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
        {"id": "pay1", "amount": "1000000.00", "status": "PAID", "created_at": today_vn_morning, "paid_at": today_vn_morning},
        {"id": "pay2", "amount": "700000.00", "status": "PAID", "created_at": today_vn_evening, "paid_at": today_vn_evening},
        {"id": "pay3", "amount": "2000000.00", "status": "PENDING", "created_at": today_vn_morning, "paid_at": None},
        {"id": "pay4", "amount": "500000.00", "status": "PENDING", "created_at": "2026-01-01T09:00:00Z", "paid_at": None},
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


@pytest.mark.asyncio
async def test_order_stats_splits_todays_orders_into_confirmed_and_pending(client, admin_override, monkeypatch):
    """A3 (phase-17-overview-kpi.md): "12 đã xác nhận · 6 chờ" under Đơn hôm
    nay. `confirmed_today` counts `admin_orders.booking_status = CONFIRMED`
    within today's VN-local window; `pending_today` is the remainder of
    `orders_today` -- everything else (PENDING/RESERVED/MIXED/etc.) bucketed
    as "chờ" per L76's softened copy, not claimed as a precise breakdown."""
    from zoneinfo import ZoneInfo

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    today = datetime.now(vn_tz).date()
    today_vn_morning = datetime(today.year, today.month, today.day, 8, 0, tzinfo=vn_tz).isoformat()
    payments = [
        {"id": f"pay{i}", "amount": "100000.00", "status": "PAID", "created_at": today_vn_morning, "paid_at": today_vn_morning} for i in range(3)
    ]
    admin_orders = [
        {"payment_id": "pay0", "booking_status": "CONFIRMED", "created_at": today_vn_morning},
        {"payment_id": "pay1", "booking_status": "PENDING", "created_at": today_vn_morning},
        {"payment_id": "pay2", "booking_status": "RESERVED", "created_at": today_vn_morning},
    ]
    fake_client = _FakeClient({"payments": payments, "bookings": [], "admin_orders": admin_orders})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["orders_today"] == 3
    assert body["confirmed_today"] == 1
    assert body["pending_today"] == 2


@pytest.mark.asyncio
async def test_order_stats_cancelled_today_excludes_sweep_cancelled_payments(client, admin_override, monkeypatch):
    """`cancelled_today` is the guest hitting "huỷ" at VNPay, NOT a payment the
    expiry sweep settled -- those carry `vnp_response_code = "HOLD_EXPIRED"`
    and would otherwise inflate the donut's "Khách huỷ" slice with orders no
    guest actually abandoned."""
    from zoneinfo import ZoneInfo

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    today = datetime.now(vn_tz).date()
    morning = datetime(today.year, today.month, today.day, 8, 0, tzinfo=vn_tz).isoformat()
    payments = [
        {"id": "pay0", "amount": "0", "status": "CANCELLED", "vnp_response_code": "24", "created_at": morning, "paid_at": None},
        {"id": "pay1", "amount": "0", "status": "CANCELLED", "vnp_response_code": "HOLD_EXPIRED", "created_at": morning, "paid_at": None},
        {"id": "pay2", "amount": "0", "status": "PENDING", "vnp_response_code": None, "created_at": morning, "paid_at": None},
    ]
    fake_client = _FakeClient({"payments": payments, "bookings": [], "admin_orders": []})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["orders_today"] == 3
    assert body["cancelled_today"] == 1  # only the vnp_ResponseCode=24 guest cancel


@pytest.mark.asyncio
async def test_order_stats_revenue_today_follows_paid_at_not_created_at_c1(client, admin_override, monkeypatch):
    """C1 code-review finding / phase-17-overview-kpi.md's own success
    criterion: "revenue today" is money that landed today, not orders
    opened today. A payment created yesterday but paid today must count;
    a payment created today but not yet paid today must not."""
    from zoneinfo import ZoneInfo

    vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    today = datetime.now(vn_tz).date()
    today_vn_morning = datetime(today.year, today.month, today.day, 8, 0, tzinfo=vn_tz).isoformat()
    yesterday_vn_evening = datetime(today.year, today.month, today.day, 8, 0, tzinfo=vn_tz) - timedelta(days=1, hours=-14)
    payments = [
        # Opened yesterday, paid this morning -- must count toward today's revenue.
        {"id": "pay-carryover", "amount": "500000.00", "status": "PAID", "created_at": yesterday_vn_evening.isoformat(), "paid_at": today_vn_morning},
        # Opened today, still unpaid -- must NOT count toward revenue.
        {"id": "pay-unpaid-today", "amount": "9000000.00", "status": "PENDING", "created_at": today_vn_morning, "paid_at": None},
    ]
    fake_client = _FakeClient({"payments": payments, "bookings": [], "admin_orders": []})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["revenue_today"] == "500000.00"


# ---------------------------------------------------------------------------
# GET /api/v1/admin/orders/{payment_id} -- D2 (phase-05-order-detail.md)
# ---------------------------------------------------------------------------


def _payment_row(**overrides) -> dict:
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "temporary_user_ref": "guest-ref-1",
        "booking_ids": ["b1", "b2"],
        "amount": "1850000.00",
        "currency": "VND",
        "status": "PAID",
        "guest_name": "Trần Quốc Bảo",
        "guest_email": "bao.tran@vsf.dev",
        "guest_phone": "0905218447",
        "vnp_transaction_no": "VNP14829371",
        "vnp_response_code": "00",
        "paid_at": "2026-08-24T08:49:00Z",
        "created_at": "2026-08-24T08:31:00Z",
    }
    row.update(overrides)
    return row


def _booking_row(**overrides) -> dict:
    row = {
        "id": "b1",
        "room_id": "r1",
        "check_in_date": "2026-08-25",
        "check_out_date": "2026-08-28",
        "room_count": 1,
        "total_amount": "1050000.00",
        "currency": "VND",
        "status": "RESERVED",
        "expires_at": "2026-08-24T09:03:00Z",
        "cancelled_at": None,
        "created_at": "2026-08-24T08:33:00Z",
        "updated_at": "2026-08-24T08:33:00Z",
        "session_id": "ct-90218",
    }
    row.update(overrides)
    return row


def _full_order_tables(**payment_overrides) -> dict[str, list[dict]]:
    return {
        "payments": [
            _payment_row(**payment_overrides),
            # Two more payments sharing guest_email -- exercises L11's
            # order_count = count(payments WHERE guest_email = ...) = 3.
            _payment_row(id="p2", amount="500000.00"),
            _payment_row(id="p3", amount="700000.00"),
        ],
        "admin_orders": [{"payment_id": "11111111-1111-1111-1111-111111111111", "booking_status": "RESERVED", "needs_attention": True}],
        "bookings": [
            _booking_row(id="b1", room_id="r1", total_amount="1050000.00", room_count=1),
            _booking_row(id="b2", room_id="r2", total_amount="650000.00", room_count=1, check_in_date="2026-08-25", check_out_date="2026-08-28"),
        ],
        "rooms": [
            {"id": "r1", "name": "Deluxe King", "hotel_id": "h1", "max_guests": 2},
            {"id": "r2", "name": "Superior Twin", "hotel_id": "h1", "max_guests": 2},
        ],
        "hotels": [{"id": "h1", "name": "Silk Path Hà Nội"}],
        "sessions": [{"session_id": "ct-90218", "created_at": "2026-08-24T08:31:00Z"}],
        "chat_messages": [{"id": str(i), "session_id": "ct-90218"} for i in range(14)],
    }


@pytest.mark.asyncio
async def test_order_detail_full_order_returns_totals_timeline_and_vnpay(client, admin_override, monkeypatch):
    fake_client = _FakeClient(_full_order_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    body = response.json()
    assert body["order_code"] == "DH-11111"
    assert body["booking_status"] == "RESERVED"
    assert body["needs_attention"] is True

    # L9: subtotal + fee = total.
    assert body["totals"] == {"subtotal": "1700000.00", "fee": "150000.00", "total": "1850000.00", "currency": "VND"}

    # L11: matches count(payments WHERE guest_email = bao.tran@vsf.dev).
    assert body["guest"]["order_count"] == 3

    # L12: no breakfast-package field leaks into the room line.
    assert set(body["rooms"][0].keys()) >= {"room_name", "max_guests", "nights", "unit_price", "total_amount", "status"}
    assert "breakfast" not in body["rooms"][0]

    kinds = [e["kind"] for e in body["timeline"]]
    assert kinds == ["created", "reserved", "paid", "awaiting_admin"]
    assert body["timeline"][-1]["kind"] == "awaiting_admin"

    assert body["vnpay"]["transaction_no"] == "VNP14829371"
    # L10: no bank field in the response at all.
    assert "bank_code" not in body["vnpay"] and "card_type" not in body["vnpay"]

    assert body["chat_session"] == {"session_id": "ct-90218", "started_at": "2026-08-24T08:31:00Z", "message_count": 14}


@pytest.mark.asyncio
async def test_order_detail_hides_chat_session_when_no_session_id(client, admin_override, monkeypatch):
    tables = _full_order_tables()
    tables["bookings"] = [_booking_row(id="b1", room_id="r1", session_id=None), _booking_row(id="b2", room_id="r2", session_id=None)]
    fake_client = _FakeClient(tables)
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    assert response.json()["chat_session"] is None


@pytest.mark.asyncio
async def test_order_detail_fee_is_null_when_total_equals_subtotal(client, admin_override, monkeypatch):
    tables = _full_order_tables(amount="1700000.00")
    fake_client = _FakeClient(tables)
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    totals = response.json()["totals"]
    assert totals["subtotal"] == totals["total"] == "1700000.00"
    assert totals["fee"] is None


@pytest.mark.asyncio
async def test_order_detail_cancelled_order_has_no_awaiting_admin_milestone(client, admin_override, monkeypatch):
    tables = _full_order_tables()
    tables["admin_orders"] = [{"payment_id": "11111111-1111-1111-1111-111111111111", "booking_status": "CANCELLED", "needs_attention": False}]
    tables["bookings"] = [
        # `expires_at` deliberately left set (not None): cancel_booking
        # (20260818_add_booking_reservation_rpcs.sql) sets status=CANCELLED
        # and cancelled_at, but never clears expires_at -- a cancelled
        # booking with a real DB row shape still carries a (now-irrelevant)
        # future expires_at. This is the exact shape that used to leak a
        # live hold countdown onto a cancelled order's timeline.
        _booking_row(id="b1", room_id="r1", status="CANCELLED", expires_at="2099-01-01T00:00:00Z", cancelled_at="2026-08-24T09:10:00Z"),
        _booking_row(id="b2", room_id="r2", status="CANCELLED", expires_at="2099-01-01T00:00:00Z", cancelled_at="2026-08-24T09:10:00Z"),
    ]
    fake_client = _FakeClient(tables)
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    kinds = [e["kind"] for e in response.json()["timeline"]]
    assert "cancelled" in kinds
    assert "awaiting_admin" not in kinds
    # H1 regression: a cancelled booking's leftover expires_at must not
    # surface a "reserved"/live-countdown milestone.
    assert "reserved" not in kinds


@pytest.mark.asyncio
async def test_order_detail_404_when_payment_missing(client, admin_override, monkeypatch):
    fake_client = _FakeClient({"payments": []})
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/22222222-2222-2222-2222-222222222222")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_order_detail_no_bookings_does_not_500_on_terminal_rollup(client, admin_override, monkeypatch):
    """A rollup/booking-row mismatch (e.g. booking_ids pointing at rows that
    no longer resolve) must degrade gracefully, not 500 -- `_build_timeline`
    used to call `max()` on an empty list for the EXPIRED/CONFIRMED
    branches."""
    tables = _full_order_tables()
    tables["admin_orders"] = [{"payment_id": "11111111-1111-1111-1111-111111111111", "booking_status": "EXPIRED", "needs_attention": False}]
    tables["bookings"] = []
    fake_client = _FakeClient(tables)
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    response = await client.get("/api/v1/admin/orders/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 200
    body = response.json()
    assert body["rooms"] == []
    # No "created" (needs a booking row) and no "expired" (guarded, empty
    # list) -- "paid" alone doesn't depend on bookings at all.
    assert [e["kind"] for e in body["timeline"]] == ["paid"]


# ---------------------------------------------------------------------------
# POST /api/v1/admin/orders/{payment_id}/confirm, /cancel -- D3
# (phase-06-order-actions.md)
# ---------------------------------------------------------------------------

PAYMENT_ID = "11111111-1111-1111-1111-111111111111"


def _fake_email_summary(*_args, **_kwargs):
    return {
        "hotel_name": "Silk Path Hà Nội",
        "hotel_image_url": None,
        "rooms": [],
        "check_in_date": "2026-08-25",
        "check_out_date": "2026-08-28",
    }


@pytest.fixture
def no_email(monkeypatch):
    """Stubs the email side-effects of confirm_order so tests can assert on
    email_sent without hitting Resend. `sent` records each call; set
    `should_fail` to simulate an EmailError (Resend outage / unconfigured)."""
    state = {"sent": [], "should_fail": False}
    monkeypatch.setattr(orders_module.payment_service, "booking_summary_for_email", _fake_email_summary)

    def fake_send(**kwargs):
        if state["should_fail"]:
            raise RuntimeError("resend_not_configured")
        state["sent"].append(kwargs)
        return "email-id"

    monkeypatch.setattr(orders_module, "send_booking_confirmation_email", fake_send)
    return state


BOOKING_ID_1 = "aaaaaaaa-0000-0000-0000-000000000001"
BOOKING_ID_2 = "aaaaaaaa-0000-0000-0000-000000000002"


def _two_booking_payment_tables(*, booking_status: str = "RESERVED") -> dict[str, list[dict]]:
    # Real UUID-shaped ids -- confirm_order/cancel_order (unlike the D2 read
    # path) parse each booking id with UUID(...) before calling the RPC
    # wrappers, matching booking_service's real `booking_id: UUID` signature.
    tables = _full_order_tables(booking_ids=[BOOKING_ID_1, BOOKING_ID_2])
    tables["bookings"] = [
        _booking_row(id=BOOKING_ID_1, room_id="r1", status=booking_status),
        _booking_row(id=BOOKING_ID_2, room_id="r2", status=booking_status, check_in_date="2026-08-25", check_out_date="2026-08-28"),
    ]
    return tables


@pytest.mark.asyncio
async def test_confirm_order_confirms_all_bookings_and_sends_email(client, admin_override, no_audit, no_email, monkeypatch):
    fake_client = _FakeClient(_two_booking_payment_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    confirmed_ids: list[str] = []
    used_refs: list[str] = []

    def fake_confirm(*, booking_id, temporary_user_ref):
        confirmed_ids.append(str(booking_id))
        used_refs.append(temporary_user_ref)
        return {"id": str(booking_id), "status": "CONFIRMED"}

    monkeypatch.setattr(orders_module, "confirm_booking", fake_confirm)

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "payment_id": PAYMENT_ID,
        "confirmed": 2,
        "failed": 0,
        "booking_status": "RESERVED",  # from the fake admin_orders rollup row
        "email_sent": True,
        "results": [
            {"booking_id": BOOKING_ID_1, "ok": True, "error": None},
            {"booking_id": BOOKING_ID_2, "ok": True, "error": None},
        ],
    }
    assert sorted(confirmed_ids) == sorted([BOOKING_ID_1, BOOKING_ID_2])
    assert len(no_email["sent"]) == 1  # sent once for the whole order, not per booking

    # `temporary_user_ref` used for the RPC's ownership check must come from
    # the `payments` row server-side, never from the request (plan's #1
    # Cao-rated risk) -- the fake payment fixture's own ref is "guest-ref-1".
    assert used_refs == ["guest-ref-1", "guest-ref-1"]

    assert len(no_audit) == 1
    audit = no_audit[0]
    assert audit["action"] == "orders.confirm"
    assert audit["entity_type"] == "payment"
    assert audit["entity_id"] == PAYMENT_ID
    assert audit["before"]["booking_status"] == "RESERVED"
    assert audit["after"]["booking_status"] == "RESERVED"


@pytest.mark.asyncio
async def test_confirm_order_email_failure_still_returns_200_with_email_sent_false(
    client, admin_override, no_audit, no_email, monkeypatch
):
    """Plan success criteria: turning off the Resend key (or any other
    Resend failure) must not fail an otherwise-successful confirm -- the
    booking write already happened, `email_sent` just reflects reality."""
    fake_client = _FakeClient(_two_booking_payment_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)
    monkeypatch.setattr(orders_module, "confirm_booking", lambda *, booking_id, temporary_user_ref: {"id": str(booking_id), "status": "CONFIRMED"})
    no_email["should_fail"] = True

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == 2
    assert body["email_sent"] is False
    assert no_email["sent"] == []


@pytest.mark.asyncio
async def test_confirm_order_partial_success_returns_200_with_results(client, admin_override, no_audit, no_email, monkeypatch):
    fake_client = _FakeClient(_two_booking_payment_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def fake_confirm(*, booking_id, temporary_user_ref):
        if str(booking_id) == BOOKING_ID_2:
            raise orders_module.BookingError("booking_reservation_expired")
        return {"id": str(booking_id), "status": "CONFIRMED"}

    monkeypatch.setattr(orders_module, "confirm_booking", fake_confirm)

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == 1
    assert body["failed"] == 1
    assert {"booking_id": BOOKING_ID_2, "ok": False, "error": "booking_reservation_expired"} in body["results"]
    # Plan: email only goes out once EVERY booking is CONFIRMED -- a partial
    # result must not email the guest a confirmation for a room that's
    # actually still failed (H1 regression: this used to send on any real
    # change, including a partial one).
    assert body["email_sent"] is False
    assert no_email["sent"] == []
    assert len(no_audit) == 1


@pytest.mark.asyncio
async def test_confirm_order_all_fail_returns_409(client, admin_override, no_audit, no_email, monkeypatch):
    fake_client = _FakeClient(_two_booking_payment_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def failing_confirm(*, booking_id, temporary_user_ref):
        raise orders_module.BookingError("booking_not_confirmable")

    monkeypatch.setattr(orders_module, "confirm_booking", failing_confirm)
    # get_booking is only consulted when the RPC says booking_not_confirmable
    # -- here it must report a status that ISN'T CONFIRMED, or the idempotent
    # path would wrongly count these as successes.
    monkeypatch.setattr(orders_module, "get_booking", lambda booking_id: {"id": str(booking_id), "status": "CANCELLED"})

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/confirm")

    assert response.status_code == 409
    assert response.json()["detail"] == "booking_not_confirmable"
    assert no_audit == []  # no audit row for a request that changed nothing


@pytest.mark.asyncio
async def test_confirm_order_second_call_is_idempotent_and_skips_email(client, admin_override, no_audit, no_email, monkeypatch):
    """Both bookings are already CONFIRMED (as if a first confirm call
    already succeeded) -- the RPC itself rejects a re-confirm with
    booking_not_confirmable, so the endpoint must recognize the booking is
    already at the target state, still return 200/ok, but not resend the
    email (plan success criteria)."""
    fake_client = _FakeClient(_two_booking_payment_tables(booking_status="CONFIRMED"))
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def already_confirmed(*, booking_id, temporary_user_ref):
        raise orders_module.BookingError("booking_not_confirmable")

    monkeypatch.setattr(orders_module, "confirm_booking", already_confirmed)
    monkeypatch.setattr(orders_module, "get_booking", lambda booking_id: {"id": str(booking_id), "status": "CONFIRMED"})

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed"] == 2
    assert body["failed"] == 0
    assert body["email_sent"] is False
    assert no_email["sent"] == []


@pytest.mark.asyncio
async def test_confirm_order_404_when_payment_missing(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: _FakeClient({"payments": []}))
    response = await client.post("/api/v1/admin/orders/22222222-2222-2222-2222-222222222222/confirm")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_order_cancels_all_bookings_no_email(client, admin_override, no_audit, no_email, monkeypatch):
    fake_client = _FakeClient(_two_booking_payment_tables(booking_status="RESERVED"))
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    cancelled_ids: list[str] = []
    used_refs: list[str] = []

    def fake_cancel(*, booking_id, temporary_user_ref):
        cancelled_ids.append(str(booking_id))
        used_refs.append(temporary_user_ref)
        return {"id": str(booking_id), "status": "CANCELLED"}

    monkeypatch.setattr(orders_module, "cancel_booking", fake_cancel)

    response = await client.post(
        f"/api/v1/admin/orders/{PAYMENT_ID}/cancel",
        json={"reason": "Khách yêu cầu huỷ", "note": "Gọi điện xác nhận"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] == 2
    assert body["failed"] == 0
    assert sorted(cancelled_ids) == sorted([BOOKING_ID_1, BOOKING_ID_2])
    assert no_email["sent"] == []  # L16 -- cancel never emails
    # Same ownership guard as confirm -- plan's #1 Cao-rated risk.
    assert used_refs == ["guest-ref-1", "guest-ref-1"]

    assert len(no_audit) == 1
    audit = no_audit[0]
    assert audit["action"] == "orders.cancel"
    assert audit["after"]["reason"] == "Khách yêu cầu huỷ"
    assert audit["after"]["note"] == "Gọi điện xác nhận"


@pytest.mark.asyncio
async def test_cancel_order_missing_reason_returns_422(client, admin_override, no_audit):
    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/cancel", json={})
    assert response.status_code == 422
    assert no_audit == []


@pytest.mark.asyncio
async def test_cancel_order_all_fail_returns_409(client, admin_override, no_audit, monkeypatch):
    fake_client = _FakeClient(_two_booking_payment_tables())
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def failing_cancel(*, booking_id, temporary_user_ref):
        raise orders_module.BookingError("booking_not_found")

    monkeypatch.setattr(orders_module, "cancel_booking", failing_cancel)

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/cancel", json={"reason": "Hết phòng"})

    assert response.status_code == 409
    assert no_audit == []


@pytest.mark.asyncio
async def test_cancel_order_called_twice_stays_idempotent_200(client, admin_override, no_audit, monkeypatch):
    """cancel_booking's RPC is itself idempotent (returns the row unchanged
    for an already-CANCELLED booking, never raises) -- a second cancel call
    must still succeed with 200, not surface as a failure."""
    fake_client = _FakeClient(_two_booking_payment_tables(booking_status="CANCELLED"))
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: fake_client)

    def idempotent_cancel(*, booking_id, temporary_user_ref):
        return {"id": str(booking_id), "status": "CANCELLED"}

    monkeypatch.setattr(orders_module, "cancel_booking", idempotent_cancel)

    response = await client.post(f"/api/v1/admin/orders/{PAYMENT_ID}/cancel", json={"reason": "Khách yêu cầu huỷ"})

    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] == 2
    assert body["failed"] == 0


@pytest.mark.asyncio
async def test_cancel_order_404_when_payment_missing(client, admin_override, no_audit, monkeypatch):
    monkeypatch.setattr(orders_module, "get_supabase_client", lambda: _FakeClient({"payments": []}))
    response = await client.post(
        "/api/v1/admin/orders/22222222-2222-2222-2222-222222222222/cancel", json={"reason": "Hết phòng"}
    )
    assert response.status_code == 404
