"""Admin D1 -- Danh sách đơn hàng (phase-04-orders-list.md).

Read-only, highest-value screen: "đơn hàng" is one payment row (decision #2),
`bookings` are its line items. Both list tabs read through views —
`admin_orders` (one row per payment, booking aggregates rolled up) and
`admin_unpaid_bookings` (bookings not attached to any payment yet) — built in
scripts/migrations/20260824_add_admin_order_views.sql, since
`payments.booking_ids` is a UUID[] PostgREST can't join through directly.

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
from pydantic import BaseModel

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services.booking_service import cancel_booking
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
