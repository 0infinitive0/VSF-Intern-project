"""Admin B1 -- Danh sách khách sạn (phase-07-hotels-list.md).

Reads go through the `admin_hotel_rows` view (one row per hotel with
room_count + embedding coverage pre-aggregated, see
scripts/migrations/20260824_add_admin_hotel_view.sql) so listing never does
N+1 per-hotel lookups. Writes (`is_active` toggle) stay on the `hotels` table
directly and always check for live CONFIRMED bookings first: deactivating a
hotel a guest is mid-stay or about to check into would strand them with no
room, so that path 409s instead (plan's L20 mitigation) rather than the B4
confirmation dialog the design called for and decision #10 cut.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client

hotels_router = APIRouter(prefix="/hotels", tags=["admin-hotels"])

_VIEW = "admin_hotel_rows"
_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100
# CSV export ignores pagination (an admin exporting a filtered set wants the
# whole set, not whatever page happened to be on screen) but still needs a
# ceiling so one request can't pull the entire table unbounded.
_CSV_MAX_ROWS = 10_000
_MAX_BLOCKING_BOOKINGS_LISTED = 5


class HotelRow(BaseModel):
    id: str
    name: str
    address: str | None = None
    city: str | None = None
    star_rating: float | None = None
    source_platform: str
    is_manual: bool
    is_active: bool
    room_count: int
    hotel_embedded: bool
    rooms_missing_embedding: int
    embedding_state: Literal["embedded", "partial", "missing"]
    image_url: str | None = None


class HotelListResponse(BaseModel):
    items: list[HotelRow]
    total: int
    page: int
    page_size: int


class SetActiveRequest(BaseModel):
    is_active: bool


class HotelActiveResponse(BaseModel):
    id: str
    is_active: bool


class BulkActiveRequest(BaseModel):
    hotel_ids: list[str]
    is_active: bool


class BulkBlockedHotel(BaseModel):
    hotel_id: str
    count: int


class BulkActiveResponse(BaseModel):
    updated: int
    blocked: list[BulkBlockedHotel]


def _embedding_state(hotel_embedded: bool, rooms_missing_embedding: int) -> Literal["embedded", "partial", "missing"]:
    if not hotel_embedded:
        return "missing"
    if rooms_missing_embedding > 0:
        return "partial"
    return "embedded"


def _row_to_hotel(row: dict[str, Any]) -> HotelRow:
    rooms_missing = row.get("rooms_missing_embedding") or 0
    return HotelRow(
        id=row["id"],
        name=row["name"],
        address=row.get("address"),
        city=row.get("city"),
        star_rating=row.get("star_rating"),
        source_platform=row["source_platform"],
        is_manual=row["is_manual"],
        is_active=row["is_active"],
        room_count=row.get("room_count") or 0,
        hotel_embedded=row["hotel_embedded"],
        rooms_missing_embedding=rooms_missing,
        embedding_state=_embedding_state(row["hotel_embedded"], rooms_missing),
        image_url=row.get("image_url"),
    )


def _apply_filters(
    query: Any,
    *,
    q: str | None,
    source: Literal["manual", "pipeline", "all"],
    is_active: bool | None,
    embedding: Literal["embedded", "missing", "all"],
) -> Any:
    if q:
        # `,` is the postgrest .or_() clause separator -- stripped so a
        # comma in the search text can't be read as a second condition.
        term = q.replace(",", "")
        query = query.or_(f"name.ilike.%{term}%,city.ilike.%{term}%")
    if source == "manual":
        query = query.eq("is_manual", True)
    elif source == "pipeline":
        query = query.eq("is_manual", False)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    if embedding == "embedded":
        query = query.eq("hotel_embedded", True)
    elif embedding == "missing":
        query = query.eq("hotel_embedded", False)
    return query


def _fetch_hotels(
    *,
    q: str | None,
    source: Literal["manual", "pipeline", "all"],
    is_active: bool | None,
    embedding: Literal["embedded", "missing", "all"],
    start: int,
    end: int,
) -> tuple[list[dict[str, Any]], int]:
    query = get_supabase_client().table(_VIEW).select("*", count="exact")
    query = _apply_filters(query, q=q, source=source, is_active=is_active, embedding=embedding)
    response = query.order("updated_at", desc=True).range(start, end).execute()
    return response.data or [], response.count or 0


def _hotels_csv_response(hotels: list[HotelRow]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "ten_khach_san", "dia_chi", "thanh_pho", "hang_sao", "nguon", "so_phong", "trang_thai_embedding", "dang_ban"]
    )
    for hotel in hotels:
        writer.writerow(
            [
                hotel.id,
                hotel.name,
                hotel.address or "",
                hotel.city or "",
                hotel.star_rating or "",
                "Tự nhập" if hotel.is_manual else "Từ pipeline",
                hotel.room_count,
                hotel.embedding_state,
                "Đang bán" if hotel.is_active else "Ngừng bán",
            ]
        )
    # Leading BOM so Excel opens the UTF-8 file with Vietnamese diacritics
    # intact instead of guessing an 8-bit codepage.
    content = "﻿" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=khach-san.csv"},
    )


@hotels_router.get("", response_model=HotelListResponse)
def list_hotels(
    q: str | None = Query(default=None),
    source: Literal["manual", "pipeline", "all"] = Query(default="all"),
    is_active: bool | None = Query(default=None),
    embedding: Literal["embedded", "missing", "all"] = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    response_format: Literal["json", "csv"] = Query(default="json", alias="format"),
) -> HotelListResponse | Response:
    if response_format == "csv":
        rows, _total = _fetch_hotels(q=q, source=source, is_active=is_active, embedding=embedding, start=0, end=_CSV_MAX_ROWS - 1)
        return _hotels_csv_response([_row_to_hotel(row) for row in rows])

    start = (page - 1) * page_size
    rows, total = _fetch_hotels(q=q, source=source, is_active=is_active, embedding=embedding, start=start, end=start + page_size - 1)
    return HotelListResponse(items=[_row_to_hotel(row) for row in rows], total=total, page=page, page_size=page_size)


def _blocking_bookings(hotel_id: str) -> tuple[int, list[dict[str, Any]]]:
    """CONFIRMED bookings for this hotel's rooms that haven't checked out
    yet. Returns (total_count, up_to_5_for_the_banner) -- see module
    docstring for why deactivation must check this."""
    supabase = get_supabase_client()
    room_rows = supabase.table("rooms").select("id").eq("hotel_id", hotel_id).execute().data or []
    room_ids = [row["id"] for row in room_rows]
    if not room_ids:
        return 0, []
    today = date.today().isoformat()
    booking_rows = (
        supabase.table("bookings")
        .select("id,check_in_date,room_id,rooms(name)")
        .in_("room_id", room_ids)
        .eq("status", "CONFIRMED")
        .gte("check_out_date", today)
        .order("check_in_date")
        .execute()
        .data
        or []
    )
    bookings = [
        {
            "booking_id": row["id"],
            "check_in_date": row["check_in_date"],
            "room_name": (row.get("rooms") or {}).get("name", ""),
        }
        for row in booking_rows
    ]
    return len(bookings), bookings[:_MAX_BLOCKING_BOOKINGS_LISTED]


def _blocked_response(count: int, bookings: list[dict[str, Any]]) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "hotel_has_future_confirmed_bookings", "count": count, "bookings": bookings},
    )


@hotels_router.patch("/{hotel_id}/active", response_model=HotelActiveResponse)
def set_hotel_active(
    hotel_id: str, body: SetActiveRequest, admin: AdminUser = Depends(require_admin)
) -> HotelActiveResponse | JSONResponse:
    if not body.is_active:
        count, bookings = _blocking_bookings(hotel_id)
        if count > 0:
            return _blocked_response(count, bookings)

    get_supabase_client().table("hotels").update({"is_active": body.is_active}).eq("id", hotel_id).execute()
    write_audit(
        admin,
        action="hotel.activate" if body.is_active else "hotel.deactivate",
        entity_type="hotel",
        entity_id=hotel_id,
        after={"is_active": body.is_active},
    )
    return HotelActiveResponse(id=hotel_id, is_active=body.is_active)


@hotels_router.post("/bulk-active", response_model=BulkActiveResponse)
def bulk_set_hotel_active(body: BulkActiveRequest, admin: AdminUser = Depends(require_admin)) -> BulkActiveResponse:
    updated = 0
    blocked: list[BulkBlockedHotel] = []
    for hotel_id in body.hotel_ids:
        if not body.is_active:
            count, _bookings = _blocking_bookings(hotel_id)
            if count > 0:
                blocked.append(BulkBlockedHotel(hotel_id=hotel_id, count=count))
                continue

        get_supabase_client().table("hotels").update({"is_active": body.is_active}).eq("id", hotel_id).execute()
        write_audit(
            admin,
            action="hotel.activate" if body.is_active else "hotel.deactivate",
            entity_type="hotel",
            entity_id=hotel_id,
            after={"is_active": body.is_active},
        )
        updated += 1
    return BulkActiveResponse(updated=updated, blocked=blocked)
