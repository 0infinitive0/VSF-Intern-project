"""Admin D1/D2 -- Danh sách + chi tiết đơn hàng (phase-04-orders-list.md,
phase-05-order-detail.md).

Read-only, highest-value screens: "đơn hàng" is one payment row (decision
#2), `bookings` are its line items. The list (D1) reads through two views --
`admin_orders` (one row per payment, booking aggregates rolled up) and
`admin_unpaid_bookings` (bookings not attached to any payment yet) — built in
scripts/migrations/20260824_add_admin_order_views.sql, since
`payments.booking_ids` is a UUID[] PostgREST can't join through directly.
The detail endpoint (D2, `GET /orders/{payment_id}`) reuses `admin_orders`
for its `booking_status`/`needs_attention` rollup (one CASE, one place it can
disagree with the list) but re-joins `bookings` -> `rooms` -> `hotels`
itself rather than reusing payment_service.booking_summary_for_email: that
helper aggregates rooms for the confirmation email and drops each booking's
own id/status/expires_at/cancelled_at plus each room's hotel_id/max_guests,
all of which D2 needs per-line (L9-L14 in the plan). Kept in this module,
not payment_service, so it stays testable through the same single
`get_supabase_client()` monkeypatch point as the rest of this file.

`order_code`/`hold_code` (`DH-3F2A1`, `GC-9182`) are display-only, derived
from the last 5 hex chars of the row's own UUID (`_short_code`) -- there is
no sequence backing them, tooltip in the frontend shows the full UUID, and
lookups still go by UUID.

L2 (plan): no "Tạo đơn thủ công" endpoint here on purpose -- no requirement,
no `temporary_user_ref` to attach a manually-created order to. L4: the one
write, `release_expired_holds`, only ever touches bookings this same request
re-selects with `expires_at < now()` computed server-side -- never trusts a
client-supplied id list -- via `admin_unpaid_bookings`, which also keeps it
scoped to holds with no payment attached yet.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services import payment_service
from src.services.booking_service import BookingError, cancel_booking, confirm_booking, get_booking
from src.services.email_service import send_booking_confirmation_email
from src.services.vnpay_service import VN_TZ

logger = logging.getLogger(__name__)

orders_router = APIRouter(prefix="/orders", tags=["admin-orders"])

_ORDERS_VIEW = "admin_orders"
_UNPAID_VIEW = "admin_unpaid_bookings"
_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100
# CSV export ignores pagination but still needs a ceiling -- see hotels.py's
# _CSV_MAX_ROWS for the same reasoning. Orders is a narrower ceiling than
# hotels' 10k per the plan's explicit "chặn 5000 dòng".
_CSV_MAX_ROWS = 5_000
_EXPIRING_SOON_MINUTES = 30
_PENDING_OVER_HOURS = 2
# Bounds the one query in this module that pulls rows into Python to sum
# rather than counting them (`get_order_stats`' revenue_today) -- without an
# explicit range PostgREST applies its own default row cap, which would
# silently under-report revenue with no error once a day passes that many
# PAID payments. Logged, not raised, if ever hit (H2 code-review finding).
_REVENUE_ROWS_CAP = 5_000
# Caps one release_expired_holds call so a large backlog can't run past the
# request/proxy timeout mid-loop, leaving an unknown prefix cancelled with
# no result returned to the admin (M2 code-review finding). cancel_booking
# is idempotent, so a second click safely continues the batch.
_RELEASE_BATCH_CAP = 200

BookingStatus = Literal["PENDING", "RESERVED", "CONFIRMED", "CANCELLED", "EXPIRED", "MIXED", "UNKNOWN"]
PaymentStatus = Literal["PENDING", "PAID", "FAILED", "CANCELLED"]
# `bookings.status`'s own CHECK constraint -- a single row, unlike
# OrderRow.booking_status' aggregated MIXED/UNKNOWN.
RawBookingStatus = Literal["PENDING", "RESERVED", "CONFIRMED", "CANCELLED", "EXPIRED"]
_RAW_BOOKING_STATUSES = frozenset({"PENDING", "RESERVED", "CONFIRMED", "CANCELLED", "EXPIRED"})


class OrderRow(BaseModel):
    payment_id: str
    order_code: str
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    hotel_ids: list[str]
    hotel_names: list[str]
    check_in_date: date | None = None
    check_out_date: date | None = None
    room_count: int
    booking_count: int
    amount: str
    currency: str
    booking_status: BookingStatus
    payment_status: PaymentStatus
    needs_attention: bool
    earliest_expires_at: str | None = None
    created_at: str


class OrderListResponse(BaseModel):
    items: list[OrderRow]
    total: int
    page: int
    page_size: int


class UnpaidBookingRow(BaseModel):
    booking_id: str
    hold_code: str
    guest_label: str | None = None
    hotel_name: str | None = None
    room_name: str | None = None
    check_in_date: date
    check_out_date: date
    room_count: int
    total_amount: str | None = None
    currency: str | None = None
    status: RawBookingStatus
    expires_at: str | None = None
    created_at: str
    session_id: str | None = None


class UnpaidBookingListResponse(BaseModel):
    items: list[UnpaidBookingRow]
    total: int
    page: int
    page_size: int
    expiring_count: int


class ReleaseExpiredResponse(BaseModel):
    released: int
    skipped: int


class OrderStatsResponse(BaseModel):
    orders_today: int
    orders_yesterday: int
    revenue_today: str
    currency: str
    avg_order_value: str
    pending_count: int
    pending_over_2h: int
    expiring_holds_30m: int


TimelineKind = Literal["created", "reserved", "paid", "cancelled", "expired", "confirmed", "awaiting_admin"]


class OrderGuest(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    order_count: int


class OrderRoomLine(BaseModel):
    booking_id: str
    hotel_id: str | None = None
    hotel_name: str | None = None
    room_id: str
    room_name: str | None = None
    max_guests: int | None = None
    check_in_date: date
    check_out_date: date
    nights: int
    room_count: int
    unit_price: str
    total_amount: str
    status: RawBookingStatus
    expires_at: str | None = None


class OrderTotals(BaseModel):
    subtotal: str
    fee: str | None = None
    total: str
    currency: str


class OrderTimelineEvent(BaseModel):
    kind: TimelineKind
    at: str | None = None
    since: str | None = None
    expires_at: str | None = None
    room_count: int | None = None


class OrderVnpay(BaseModel):
    transaction_no: str | None = None
    response_code: str | None = None
    paid_at: str | None = None
    amount: str
    currency: str


class OrderChatSession(BaseModel):
    session_id: str
    started_at: str | None = None
    message_count: int


class BookingActionResult(BaseModel):
    booking_id: str
    ok: bool
    error: str | None = None


class ConfirmOrderResponse(BaseModel):
    payment_id: str
    confirmed: int
    failed: int
    booking_status: BookingStatus
    email_sent: bool
    results: list[BookingActionResult]


class CancelOrderRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class CancelOrderResponse(BaseModel):
    payment_id: str
    cancelled: int
    failed: int
    booking_status: BookingStatus
    results: list[BookingActionResult]


class OrderDetailResponse(BaseModel):
    payment_id: str
    order_code: str
    booking_status: BookingStatus
    payment_status: PaymentStatus
    needs_attention: bool
    attention_hours: int
    guest: OrderGuest
    rooms: list[OrderRoomLine]
    totals: OrderTotals
    timeline: list[OrderTimelineEvent]
    vnpay: OrderVnpay
    chat_session: OrderChatSession | None = None


def _short_code(prefix: str, entity_id: str) -> str:
    return f"{prefix}-{entity_id.replace('-', '')[-5:].upper()}"


def _money_str(value: Any) -> str:
    return str(Decimal(str(value)))


def _vn_day_start(d: date) -> str:
    """VN-local midnight of `d`, as an absolute-instant `timestamptz` string.
    Sending a bare `YYYY-MM-DD` string instead would leave Postgres to cast
    it to `timestamptz` using the DB session's own timezone -- correct only
    if that happens to also be VN time (H3 code-review finding). An explicit
    offset makes the day boundary correct regardless of DB session tz."""
    return datetime(d.year, d.month, d.day, tzinfo=VN_TZ).isoformat()


def _normalize_search_term(q: str) -> tuple[str, str]:
    """Returns (email_term, phone_term). `,` is PostgREST's `.or_()` clause
    separator -- stripped so it can't be read as a second condition (same
    guard as hotels.py's `_apply_filters`). Phone side additionally
    normalizes `+84` -> `0` and drops spaces per the plan's matching rule,
    since `guest_phone` is stored in that shape."""
    term = q.replace(",", "")
    phone_term = term.replace(" ", "")
    if phone_term.startswith("+84"):
        phone_term = "0" + phone_term[3:]
    return term, phone_term


def _apply_paid_filters(
    query: Any,
    *,
    booking_status: BookingStatus | None,
    payment_status: PaymentStatus | None,
    from_: date | None,
    to_: date | None,
    hotel_id: str | None,
    q: str | None,
    needs_attention: bool | None,
) -> Any:
    if booking_status:
        query = query.eq("booking_status", booking_status)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    if from_:
        query = query.gte("created_at", _vn_day_start(from_))
    if to_:
        query = query.lt("created_at", _vn_day_start(to_ + timedelta(days=1)))
    if hotel_id:
        query = query.contains("hotel_ids", [hotel_id])
    if q:
        email_term, phone_term = _normalize_search_term(q)
        query = query.or_(f"guest_email.ilike.%{email_term}%,guest_phone.ilike.%{phone_term}%")
    if needs_attention is not None:
        query = query.eq("needs_attention", needs_attention)
    return query


def _apply_unpaid_filters(
    query: Any,
    *,
    booking_status: BookingStatus | None,
    from_: date | None,
    to_: date | None,
    hotel_id: str | None,
) -> Any:
    # `booking_status` here is a bare `bookings.status` value, not the
    # aggregated `admin_orders.booking_status` -- MIXED/UNKNOWN (valid on the
    # paid tab) can never match a row here, so silently skip rather than
    # returning a confidently-empty result for a value that was never
    # supposed to apply to this tab (M1 code-review finding).
    if booking_status in _RAW_BOOKING_STATUSES:
        query = query.eq("status", booking_status)
    if from_:
        query = query.gte("created_at", _vn_day_start(from_))
    if to_:
        query = query.lt("created_at", _vn_day_start(to_ + timedelta(days=1)))
    if hotel_id:
        query = query.eq("hotel_id", hotel_id)
    return query


def _fetch_orders(*, start: int, end: int, **filters: Any) -> tuple[list[dict[str, Any]], int]:
    query = get_supabase_client().table(_ORDERS_VIEW).select("*", count="exact")
    query = _apply_paid_filters(query, **filters)
    response = query.order("created_at", desc=True).range(start, end).execute()
    return response.data or [], response.count or 0


def _fetch_unpaid_bookings(*, start: int, end: int, **filters: Any) -> tuple[list[dict[str, Any]], int]:
    query = get_supabase_client().table(_UNPAID_VIEW).select("*", count="exact")
    query = _apply_unpaid_filters(query, **filters)
    # Ascending `expires_at` puts the soonest-to-expire hold first; Postgres'
    # default NULLS LAST on ascending order already pushes PENDING rows with
    # no expiry to the bottom, so no explicit nullsfirst needed.
    response = query.order("expires_at").range(start, end).execute()
    return response.data or [], response.count or 0


def _count_expiring_unpaid(*, now: datetime, **filters: Any) -> int:
    soon = now + timedelta(minutes=_EXPIRING_SOON_MINUTES)
    query = get_supabase_client().table(_UNPAID_VIEW).select("booking_id", count="exact")
    query = _apply_unpaid_filters(query, **filters)
    response = query.gt("expires_at", now.isoformat()).lte("expires_at", soon.isoformat()).range(0, 0).execute()
    return response.count or 0


def _row_to_order(row: dict[str, Any]) -> OrderRow:
    return OrderRow(
        payment_id=row["payment_id"],
        order_code=_short_code("DH", row["payment_id"]),
        guest_name=row.get("guest_name"),
        guest_email=row.get("guest_email"),
        guest_phone=row.get("guest_phone"),
        hotel_ids=row.get("hotel_ids") or [],
        hotel_names=row.get("hotel_names") or [],
        check_in_date=row.get("check_in_date"),
        check_out_date=row.get("check_out_date"),
        room_count=row.get("room_count") or 0,
        booking_count=row.get("booking_count") or 0,
        amount=_money_str(row["amount"]),
        currency=row["currency"],
        booking_status=row["booking_status"],
        payment_status=row["payment_status"],
        needs_attention=bool(row["needs_attention"]),
        earliest_expires_at=row.get("earliest_expires_at"),
        created_at=row["created_at"],
    )


def _row_to_unpaid_booking(row: dict[str, Any]) -> UnpaidBookingRow:
    # L8 (plan): `bookings` has no guest name -- only `temporary_user_ref`,
    # the anonymous chat-guest handle. Shown truncated; null when the
    # booking itself has no ref to show.
    ref = row.get("temporary_user_ref")
    return UnpaidBookingRow(
        booking_id=row["booking_id"],
        hold_code=_short_code("GC", row["booking_id"]),
        guest_label=f"Khách ẩn danh · {ref[:8]}" if ref else None,
        hotel_name=row.get("hotel_name"),
        room_name=row.get("room_name"),
        check_in_date=row["check_in_date"],
        check_out_date=row["check_out_date"],
        room_count=row.get("room_count") or 0,
        total_amount=_money_str(row["total_amount"]) if row.get("total_amount") is not None else None,
        currency=row.get("currency"),
        status=row["status"],
        expires_at=row.get("expires_at"),
        created_at=row["created_at"],
        session_id=row.get("session_id"),
    )


def _csv_safe(value: str) -> str:
    """Same formula-injection guard as hotels.py's `_csv_safe` -- duplicated
    rather than shared, per the plan's file-ownership split (Đơn hàng branch
    only owns this file)."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "\t" + value
    return value


def _orders_csv_response(orders: list[OrderRow]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["ma_don", "khach", "email", "sdt", "khach_san", "ngay_nhan", "ngay_tra", "so_phong", "tong_tien", "trang_thai_dat_phong", "trang_thai_thanh_toan", "tao_luc"]
    )
    for order in orders:
        writer.writerow(
            [
                order.order_code,
                _csv_safe(order.guest_name or ""),
                _csv_safe(order.guest_email or ""),
                _csv_safe(order.guest_phone or ""),
                _csv_safe(", ".join(order.hotel_names)),
                order.check_in_date or "",
                order.check_out_date or "",
                order.room_count,
                order.amount,
                order.booking_status,
                order.payment_status,
                order.created_at,
            ]
        )
    content = "﻿" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=don-hang.csv"},
    )


def _unpaid_csv_response(bookings: list[UnpaidBookingRow]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["ma_giu_cho", "khach", "khach_san", "phong", "ngay_nhan", "ngay_tra", "so_phong", "tong_tien", "trang_thai", "het_han_luc", "tao_luc"])
    for booking in bookings:
        writer.writerow(
            [
                booking.hold_code,
                _csv_safe(booking.guest_label or ""),
                _csv_safe(booking.hotel_name or ""),
                _csv_safe(booking.room_name or ""),
                booking.check_in_date,
                booking.check_out_date,
                booking.room_count,
                booking.total_amount or "",
                booking.status,
                booking.expires_at or "",
                booking.created_at,
            ]
        )
    content = "﻿" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=giu-cho-chua-thanh-toan.csv"},
    )


@orders_router.get("", response_model=OrderListResponse | UnpaidBookingListResponse)
def list_orders(
    tab: Literal["paid", "unpaid"] = Query(default="paid"),
    booking_status: BookingStatus | None = Query(default=None),
    payment_status: PaymentStatus | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to_: date | None = Query(default=None, alias="to"),
    hotel_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    needs_attention: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    response_format: Literal["json", "csv"] = Query(default="json", alias="format"),
) -> OrderListResponse | UnpaidBookingListResponse | Response:
    if from_ and to_ and from_ > to_:
        raise HTTPException(status_code=422, detail="from must not be after to")

    if tab == "unpaid":
        unpaid_filters = {"booking_status": booking_status, "from_": from_, "to_": to_, "hotel_id": hotel_id}
        if response_format == "csv":
            rows, _total = _fetch_unpaid_bookings(start=0, end=_CSV_MAX_ROWS - 1, **unpaid_filters)
            return _unpaid_csv_response([_row_to_unpaid_booking(row) for row in rows])

        start = (page - 1) * page_size
        rows, total = _fetch_unpaid_bookings(start=start, end=start + page_size - 1, **unpaid_filters)
        expiring_count = _count_expiring_unpaid(now=datetime.now(timezone.utc), **unpaid_filters)
        return UnpaidBookingListResponse(
            items=[_row_to_unpaid_booking(row) for row in rows], total=total, page=page, page_size=page_size, expiring_count=expiring_count
        )

    paid_filters = {
        "booking_status": booking_status,
        "payment_status": payment_status,
        "from_": from_,
        "to_": to_,
        "hotel_id": hotel_id,
        "q": q,
        "needs_attention": needs_attention,
    }
    if response_format == "csv":
        rows, _total = _fetch_orders(start=0, end=_CSV_MAX_ROWS - 1, **paid_filters)
        return _orders_csv_response([_row_to_order(row) for row in rows])

    start = (page - 1) * page_size
    rows, total = _fetch_orders(start=start, end=start + page_size - 1, **paid_filters)
    return OrderListResponse(items=[_row_to_order(row) for row in rows], total=total, page=page, page_size=page_size)


@orders_router.post("/holds/release-expired", response_model=ReleaseExpiredResponse)
def release_expired_holds(admin: AdminUser = Depends(require_admin)) -> ReleaseExpiredResponse:
    """Cancels every unpaid hold this request itself finds already expired --
    `expires_at < now()` is re-evaluated here against `admin_unpaid_bookings`,
    never taken from the client, so a stale/forged id list can't cancel a
    booking that's still live (plan's L4 mitigation, same posture as
    `cancel_reserved_bookings_for_session`)."""
    now = datetime.now(timezone.utc).isoformat()
    rows = (
        get_supabase_client()
        .table(_UNPAID_VIEW)
        .select("booking_id,temporary_user_ref")
        .in_("status", ["RESERVED", "PENDING"])
        .lt("expires_at", now)
        .limit(_RELEASE_BATCH_CAP)
        .execute()
        .data
        or []
    )
    released_ids: list[str] = []
    skipped = 0
    for row in rows:
        booking_id = str(row["booking_id"])
        try:
            cancel_booking(booking_id=UUID(booking_id), temporary_user_ref=row["temporary_user_ref"])
            released_ids.append(booking_id)
        except Exception:
            logger.exception("Unable to release expired hold %s", booking_id)
            skipped += 1
    if released_ids or skipped:
        write_audit(
            admin,
            action="orders.release_expired_holds",
            entity_type="booking",
            entity_id="bulk",
            after={"released_booking_ids": released_ids, "skipped": skipped},
        )
    return ReleaseExpiredResponse(released=len(released_ids), skipped=skipped)


@orders_router.get("/stats", response_model=OrderStatsResponse)
def get_order_stats() -> OrderStatsResponse:
    supabase = get_supabase_client()
    # VN-local calendar day, not the API process' own tz (H3 code-review
    # finding) -- an admin in Vietnam checking the dashboard at, say,
    # 01:00 ICT must see 01:00 ICT's "today", not still-yesterday UTC.
    today = datetime.now(VN_TZ).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    today_start, tomorrow_start, yesterday_start = _vn_day_start(today), _vn_day_start(tomorrow), _vn_day_start(yesterday)

    orders_today = (
        supabase.table("payments").select("id", count="exact").gte("created_at", today_start).lt("created_at", tomorrow_start).range(0, 0).execute().count or 0
    )
    orders_yesterday = (
        supabase.table("payments").select("id", count="exact").gte("created_at", yesterday_start).lt("created_at", today_start).range(0, 0).execute().count or 0
    )

    # Explicitly bounded (unlike every other query here, which counts rather
    # than transfers rows) -- H2 code-review finding: without a range,
    # PostgREST's own default row cap could silently truncate this sum with
    # no error once a day passes that many PAID payments.
    paid_today_rows = (
        supabase.table("payments")
        .select("amount")
        .eq("status", "PAID")
        .gte("created_at", today_start)
        .lt("created_at", tomorrow_start)
        .range(0, _REVENUE_ROWS_CAP - 1)
        .execute()
        .data
        or []
    )
    if len(paid_today_rows) >= _REVENUE_ROWS_CAP:
        logger.warning("revenue_today hit the %d-row cap -- figure may be truncated", _REVENUE_ROWS_CAP)
    revenue_today = sum((Decimal(str(row["amount"])) for row in paid_today_rows), Decimal("0"))
    # L5 (plan): divides by ALL orders created today, not just the paid ones
    # -- matches the design's sample numbers exactly (62.400.000 / 18).
    # Quantized to cents (H1 code-review finding): an exact Decimal division
    # like 62400000/18 doesn't terminate and would otherwise serialize with
    # ~20 decimal digits instead of a money-shaped value.
    avg_order_value = (revenue_today / max(orders_today, 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=_PENDING_OVER_HOURS)
    pending_count = supabase.table("payments").select("id", count="exact").eq("status", "PENDING").range(0, 0).execute().count or 0
    pending_over_2h = (
        supabase.table("payments").select("id", count="exact").eq("status", "PENDING").lt("created_at", two_hours_ago.isoformat()).range(0, 0).execute().count or 0
    )

    soon = now + timedelta(minutes=_EXPIRING_SOON_MINUTES)
    expiring_holds_30m = (
        supabase.table("bookings")
        .select("id", count="exact")
        .eq("status", "RESERVED")
        .gt("expires_at", now.isoformat())
        .lte("expires_at", soon.isoformat())
        .range(0, 0)
        .execute()
        .count
        or 0
    )

    return OrderStatsResponse(
        orders_today=orders_today,
        orders_yesterday=orders_yesterday,
        revenue_today=_money_str(revenue_today),
        currency="VND",
        avg_order_value=_money_str(avg_order_value),
        pending_count=pending_count,
        pending_over_2h=pending_over_2h,
        expiring_holds_30m=expiring_holds_30m,
    )


def _round_money(value: Decimal) -> str:
    """Whole-đồng rounding (risk table: VND has no smaller unit) -- callers
    that need the frontend's `≈` cue derive it themselves by comparing this
    back against `total_amount`, so the wire contract stays exactly what the
    plan specifies (no extra "is_approximate" field)."""
    return str(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _nights(check_in_date: str, check_out_date: str) -> int:
    return (date.fromisoformat(check_out_date) - date.fromisoformat(check_in_date)).days


def _fetch_payment(payment_id: str) -> dict[str, Any] | None:
    rows = get_supabase_client().table("payments").select("*").eq("id", payment_id).limit(1).execute().data
    return dict(rows[0]) if rows else None


def _fetch_order_rollup(payment_id: str) -> dict[str, Any] | None:
    """`booking_status`/`needs_attention` already computed by the
    `admin_orders` view's CASE (20260824_add_admin_order_views.sql) --
    reused here so D1's list and this detail screen can never disagree on
    what either means for the same order."""
    rows = (
        get_supabase_client()
        .table(_ORDERS_VIEW)
        .select("booking_status, needs_attention")
        .eq("payment_id", payment_id)
        .limit(1)
        .execute()
        .data
    )
    return dict(rows[0]) if rows else None


def _fetch_order_bookings(booking_ids: list[str]) -> list[dict[str, Any]]:
    """Per-booking rows (own id/status/expires_at/cancelled_at kept, unlike
    payment_service's aggregated booking_summary_for_email) joined to room
    name/max_guests and hotel id/name -- see this module's docstring for why
    that helper isn't reused here."""
    if not booking_ids:
        return []
    client = get_supabase_client()
    booking_rows = (
        client.table("bookings")
        .select(
            "id, room_id, check_in_date, check_out_date, room_count, total_amount, currency, "
            "status, expires_at, cancelled_at, created_at, updated_at, session_id"
        )
        .in_("id", booking_ids)
        .order("created_at")
        .execute()
        .data
        or []
    )
    if not booking_rows:
        return []

    room_ids = list({row["room_id"] for row in booking_rows})
    room_rows = client.table("rooms").select("id, name, hotel_id, max_guests").in_("id", room_ids).execute().data or []
    room_by_id = {row["id"]: row for row in room_rows}

    hotel_ids = list({row["hotel_id"] for row in room_rows if row.get("hotel_id")})
    hotel_rows = client.table("hotels").select("id, name").in_("id", hotel_ids).execute().data if hotel_ids else []
    hotel_by_id = {row["id"]: row for row in hotel_rows or []}

    result = []
    for row in booking_rows:
        room = room_by_id.get(row["room_id"], {})
        hotel = hotel_by_id.get(room.get("hotel_id"), {})
        result.append({
            **row,
            "room_name": room.get("name"),
            "max_guests": room.get("max_guests"),
            "hotel_id": room.get("hotel_id"),
            "hotel_name": hotel.get("name"),
        })
    return result


def _booking_row_to_room_line(row: dict[str, Any]) -> OrderRoomLine:
    nights = _nights(row["check_in_date"], row["check_out_date"])
    total_amount = Decimal(str(row["total_amount"])) if row.get("total_amount") is not None else Decimal("0")
    room_count = row.get("room_count") or 1
    unit_price = _round_money(total_amount / (max(nights, 1) * room_count))
    return OrderRoomLine(
        booking_id=row["id"],
        hotel_id=row.get("hotel_id"),
        hotel_name=row.get("hotel_name"),
        room_id=row["room_id"],
        room_name=row.get("room_name"),
        max_guests=row.get("max_guests"),
        check_in_date=row["check_in_date"],
        check_out_date=row["check_out_date"],
        nights=nights,
        room_count=room_count,
        unit_price=unit_price,
        total_amount=_money_str(total_amount),
        status=row["status"],
        expires_at=row.get("expires_at"),
    )


def _order_count_for_guest(*, guest_email: str | None, temporary_user_ref: str | None) -> int:
    """L11 (plan): `guest_email` when present, else `temporary_user_ref` --
    matches Success Criteria's `SELECT count(*) FROM payments WHERE
    guest_email = ...` exactly, not the design column's "max of both"
    phrasing (the Xử lý column and success criteria override it)."""
    client = get_supabase_client()
    if guest_email:
        return client.table("payments").select("id", count="exact").eq("guest_email", guest_email).range(0, 0).execute().count or 0
    if temporary_user_ref:
        return (
            client.table("payments")
            .select("id", count="exact")
            .eq("temporary_user_ref", temporary_user_ref)
            .range(0, 0)
            .execute()
            .count
            or 0
        )
    return 0


def _as_utc_iso(value: str | None) -> str | None:
    """`sessions.created_at` is a bare `TIMESTAMP` (no tz), unlike every
    other timestamp on this screen (`bookings.created_at`/`payments.paid_at`
    are `timestamptz`) -- PostgREST returns it with no offset, which a
    browser's `new Date(...)` parses as LOCAL time, skewing it hours off
    from the "created" milestone shown right above it. Stamped `Z` here:
    Postgres stores this column's wall-clock in UTC."""
    if value and "+" not in value and not value.endswith("Z"):
        return value + "Z"
    return value


def _chat_session_info(session_id: str | None) -> OrderChatSession | None:
    if not session_id:
        return None
    client = get_supabase_client()
    session_rows = client.table("sessions").select("created_at").eq("session_id", session_id).limit(1).execute().data
    started_at = _as_utc_iso(session_rows[0]["created_at"]) if session_rows else None
    message_count = client.table("chat_messages").select("id", count="exact").eq("session_id", session_id).range(0, 0).execute().count or 0
    return OrderChatSession(session_id=session_id, started_at=started_at, message_count=message_count)


def _build_timeline(bookings: list[dict[str, Any]], payment: dict[str, Any], booking_status: str) -> list[OrderTimelineEvent]:
    """Suy diễn từ dữ liệu có thật -- không có bảng lịch sử trạng thái
    (module docstring's L9-L14 note), nên chỉ dựng mốc từ trường có bằng
    chứng (`created_at`, `expires_at`, `paid_at`, `cancelled_at`,
    `updated_at`). The four closing branches (cancelled/expired/confirmed/
    awaiting_admin) are mutually exclusive with `booking_status`'s own CASE,
    so at most one ever appears, and `awaiting_admin` -- the only "still
    open" branch -- is always emitted last."""
    events: list[OrderTimelineEvent] = [OrderTimelineEvent(kind="created", at=min(b["created_at"] for b in bookings))] if bookings else []

    def room_count(rows: list[dict[str, Any]]) -> int:
        return sum(b.get("room_count") or 0 for b in rows)

    # `status == "RESERVED"`, not just `expires_at` truthy: cancel_booking
    # (20260818_add_booking_reservation_rpcs.sql) sets CANCELLED but never
    # clears expires_at, unlike confirm_booking_reservation which nulls it
    # on confirm -- without this guard, a cancelled-before-hold-lapsed order
    # would still show a live "hết hạn sau ..." countdown next to "Đã huỷ".
    reserved = [b for b in bookings if b.get("expires_at") and b.get("status") == "RESERVED"]
    if reserved:
        first_reserved = min(reserved, key=lambda b: b["created_at"])
        events.append(
            OrderTimelineEvent(
                kind="reserved", at=first_reserved["created_at"], expires_at=first_reserved["expires_at"], room_count=room_count(reserved)
            )
        )

    if payment.get("paid_at"):
        events.append(OrderTimelineEvent(kind="paid", at=payment["paid_at"]))

    if booking_status == "CANCELLED":
        cancelled = [b for b in bookings if b.get("cancelled_at")]
        if cancelled:
            events.append(OrderTimelineEvent(kind="cancelled", at=max(b["cancelled_at"] for b in cancelled), room_count=room_count(cancelled)))
    elif booking_status == "EXPIRED":
        expired = [b for b in bookings if b.get("status") == "EXPIRED"]
        if expired:
            events.append(OrderTimelineEvent(kind="expired", at=max(b["updated_at"] for b in expired), room_count=room_count(expired)))
    elif booking_status == "CONFIRMED":
        if bookings:
            events.append(OrderTimelineEvent(kind="confirmed", at=max(b["updated_at"] for b in bookings)))
    elif payment.get("status") == "PAID":
        events.append(OrderTimelineEvent(kind="awaiting_admin", since=payment.get("paid_at")))

    return events


@orders_router.get("/{payment_id}", response_model=OrderDetailResponse)
def get_order_detail(payment_id: UUID) -> OrderDetailResponse:
    payment = _fetch_payment(str(payment_id))
    if payment is None:
        raise HTTPException(status_code=404, detail="order_not_found")

    rollup = _fetch_order_rollup(str(payment_id)) or {"booking_status": "UNKNOWN", "needs_attention": False}
    booking_status: BookingStatus = rollup["booking_status"]
    needs_attention = bool(rollup["needs_attention"])

    bookings = _fetch_order_bookings(payment.get("booking_ids") or [])
    rooms = [_booking_row_to_room_line(row) for row in bookings]

    subtotal = sum((Decimal(str(b["total_amount"])) for b in bookings if b.get("total_amount") is not None), Decimal("0"))
    total = Decimal(str(payment["amount"]))
    fee = total - subtotal
    totals = OrderTotals(
        subtotal=_money_str(subtotal),
        fee=_money_str(fee) if fee != 0 else None,
        total=_money_str(total),
        currency=payment["currency"],
    )

    guest = OrderGuest(
        name=payment.get("guest_name"),
        email=payment.get("guest_email"),
        phone=payment.get("guest_phone"),
        order_count=_order_count_for_guest(guest_email=payment.get("guest_email"), temporary_user_ref=payment.get("temporary_user_ref")),
    )

    attention_hours = 0
    if needs_attention and payment.get("paid_at"):
        paid_at = datetime.fromisoformat(str(payment["paid_at"]).replace("Z", "+00:00"))
        attention_hours = max(int((datetime.now(timezone.utc) - paid_at).total_seconds() // 3600), 0)

    vnpay = OrderVnpay(
        transaction_no=payment.get("vnp_transaction_no"),
        response_code=payment.get("vnp_response_code"),
        paid_at=payment.get("paid_at"),
        amount=_money_str(total),
        currency=payment["currency"],
    )

    # Every booking in one order shares a single hold session (a hold is
    # always for one hotel -- use-room-hold.ts), so the first non-null
    # session_id speaks for the whole order; L14 hides the block entirely
    # when every booking has none (not created from a chat session).
    session_id = next((b["session_id"] for b in bookings if b.get("session_id")), None)

    return OrderDetailResponse(
        payment_id=str(payment["id"]),
        order_code=_short_code("DH", str(payment["id"])),
        booking_status=booking_status,
        payment_status=payment["status"],
        needs_attention=needs_attention,
        attention_hours=attention_hours,
        guest=guest,
        rooms=rooms,
        totals=totals,
        timeline=_build_timeline(bookings, payment, booking_status),
        vnpay=vnpay,
        chat_session=_chat_session_info(session_id),
    )


# ---------------------------------------------------------------------------
# D3 -- Xác nhận / Huỷ đơn (phase-06-order-actions.md)
#
# Both write through the same RPCs D5/booking flow already uses
# (confirm_booking_reservation, cancel_booking) -- never a direct UPDATE on
# bookings.status -- one call per booking in the payment's group, no shared
# transaction (each RPC already takes its own row/advisory lock; wrapping
# several in one transaction would hold those locks far longer and invite
# deadlocks -- plan's risk table). A partial result (some bookings ok, some
# not) is a valid 200, not an error: only when EVERY booking in the group
# fails does this 409.
# ---------------------------------------------------------------------------


def _confirm_one(booking_id: str, temporary_user_ref: str | None) -> tuple[BookingActionResult, bool]:
    """Confirms one booking. Returns (result, changed) -- `changed` is True
    only when this call itself just flipped RESERVED -> CONFIRMED; a booking
    already CONFIRMED (a retried/double-click confirm) counts as `ok=True`
    but `changed=False` so the caller doesn't re-send the confirmation email
    for a call that made no actual change (plan success criteria: a second
    confirm call must not send a second email)."""
    try:
        confirm_booking(booking_id=UUID(booking_id), temporary_user_ref=temporary_user_ref or "")
        return BookingActionResult(booking_id=booking_id, ok=True, error=None), True
    except BookingError as exc:
        code = str(exc)
        if code == "booking_not_confirmable":
            current = get_booking(UUID(booking_id))
            if current and current.get("status") == "CONFIRMED":
                return BookingActionResult(booking_id=booking_id, ok=True, error=None), False
        return BookingActionResult(booking_id=booking_id, ok=False, error=code), False


def _send_order_confirmation_email(payment: dict[str, Any]) -> bool:
    """Best-effort -- mirrors routes.py's `_send_confirmation_email_best_effort`
    for the guest-side VNPay IPN flow (kept as its own copy per this module's
    file-ownership split, see module docstring). Never raises: a Resend
    outage -- or any other failure while building the email, including the
    `booking_summary_for_email` read -- must not turn an already-successful
    confirm into a failed request between the DB write and the audit write.
    `email_sent` on the response reflects what actually happened."""
    guest_email = payment.get("guest_email")
    booking_ids = payment.get("booking_ids") or []
    if not guest_email or not booking_ids:
        return False
    try:
        summary = payment_service.booking_summary_for_email([UUID(str(b)) for b in booking_ids])
        send_booking_confirmation_email(
            to_email=guest_email,
            guest_name=payment.get("guest_name") or "",
            hotel_name=(summary or {}).get("hotel_name") or "",
            hotel_image_url=(summary or {}).get("hotel_image_url"),
            booking_code=str(payment["id"])[:8].upper(),
            check_in_date=str((summary or {}).get("check_in_date") or ""),
            check_out_date=str((summary or {}).get("check_out_date") or ""),
            rooms=(summary or {}).get("rooms") or [],
            total_amount=Decimal(str(payment["amount"])) if payment.get("amount") is not None else None,
            currency=payment.get("currency"),
        )
        return True
    except Exception:
        logger.exception("Failed to send booking confirmation email for payment %s", payment["id"])
        return False


@orders_router.post("/{payment_id}/confirm", response_model=ConfirmOrderResponse)
def confirm_order(payment_id: UUID, admin: AdminUser = Depends(require_admin)) -> ConfirmOrderResponse:
    payment = _fetch_payment(str(payment_id))
    if payment is None:
        raise HTTPException(status_code=404, detail="order_not_found")

    before_rollup = _fetch_order_rollup(str(payment_id))
    temporary_user_ref = payment.get("temporary_user_ref")

    results: list[BookingActionResult] = []
    confirmed = 0
    failed = 0
    any_changed = False
    for booking_id in payment.get("booking_ids") or []:
        result, changed = _confirm_one(str(booking_id), temporary_user_ref)
        results.append(result)
        if result.ok:
            confirmed += 1
        else:
            failed += 1
        any_changed = any_changed or changed

    if confirmed == 0:
        raise HTTPException(status_code=409, detail="booking_not_confirmable")

    # Plan: send the confirmation email only "sau khi mọi booking CONFIRMED"
    # -- a partial success (some bookings still failed) must not email the
    # guest a confirmation that lists rooms that were never actually
    # confirmed, or bill them the full order amount for a partial result.
    email_sent = _send_order_confirmation_email(payment) if any_changed and failed == 0 else False

    rollup = _fetch_order_rollup(str(payment_id)) or {"booking_status": "UNKNOWN"}
    write_audit(
        admin,
        action="orders.confirm",
        entity_type="payment",
        entity_id=str(payment_id),
        before={"booking_status": (before_rollup or {}).get("booking_status")},
        after={
            "booking_status": rollup["booking_status"],
            "email_sent": email_sent,
            "results": [r.model_dump() for r in results],
        },
    )

    return ConfirmOrderResponse(
        payment_id=str(payment_id),
        confirmed=confirmed,
        failed=failed,
        booking_status=rollup["booking_status"],
        email_sent=email_sent,
        results=results,
    )


@orders_router.post("/{payment_id}/cancel", response_model=CancelOrderResponse)
def cancel_order(
    payment_id: UUID, body: CancelOrderRequest, admin: AdminUser = Depends(require_admin)
) -> CancelOrderResponse:
    payment = _fetch_payment(str(payment_id))
    if payment is None:
        raise HTTPException(status_code=404, detail="order_not_found")

    before_rollup = _fetch_order_rollup(str(payment_id))
    temporary_user_ref = payment.get("temporary_user_ref")

    results: list[BookingActionResult] = []
    cancelled = 0
    failed = 0
    for booking_id in payment.get("booking_ids") or []:
        try:
            cancel_booking(booking_id=UUID(str(booking_id)), temporary_user_ref=temporary_user_ref or "")
            results.append(BookingActionResult(booking_id=str(booking_id), ok=True, error=None))
            cancelled += 1
        except BookingError as exc:
            results.append(BookingActionResult(booking_id=str(booking_id), ok=False, error=str(exc)))
            failed += 1

    if cancelled == 0:
        raise HTTPException(status_code=409, detail="booking_not_cancellable")

    rollup = _fetch_order_rollup(str(payment_id)) or {"booking_status": "UNKNOWN"}
    # L16 (plan): cancel never sends email -- decision #11, and
    # email_service has no cancellation template anyway.
    write_audit(
        admin,
        action="orders.cancel",
        entity_type="payment",
        entity_id=str(payment_id),
        before={"booking_status": (before_rollup or {}).get("booking_status")},
        after={
            "booking_status": rollup["booking_status"],
            "reason": body.reason,
            "note": body.note,
            "results": [r.model_dump() for r in results],
        },
    )

    return CancelOrderResponse(
        payment_id=str(payment_id),
        cancelled=cancelled,
        failed=failed,
        booking_status=rollup["booking_status"],
        results=results,
    )
