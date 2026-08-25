"""Admin B6 -- Quản lý giá phòng theo đêm (phase-11-room-prices.md). The one
screen that writes directly into the data the bot quotes prices from --
`room_prices` is one row per NIGHT (`check_in_date` = that night,
`check_out_date` = the next day), never one row per date range. A night can
carry several rows (one per `source_url`); `place_details._average_price`
always picks the row with the newest `crawled_at`, so an admin write (always
`source_url=NULL`, `crawled_at=now()`) outranks a stale OTA row for that
night without the OTA pipeline ever being touched (decision #7) -- and the
next OTA crawl (a newer `crawled_at`) outranks it back. This module never
touches `rooms.embedding` or shows anything embedding-related: `room_prices`
has no `embedding` column and isn't part of `_build_text`.

Separate module from `rooms.py` (phase-10) per the plan's own file-size call
-- this file is the price-write surface, rooms.py stays the room-shape CRUD
surface.

`admin_upsert_room_prices` (20260824_add_admin_upsert_room_prices_rpc.sql) is
a raw-SQL RPC, not a postgrest `.upsert()`, because `room_prices`' natural
key is an EXPRESSION unique index (`COALESCE(source_url, '')`) that
postgrest's `on_conflict=col,col` REST param cannot target.
`room_night_occupancy` (database_schema.sql) is queried directly instead of
calling `get_room_availability()` once per night in the queried window --
its predicate (CONFIRMED/unexpired-RESERVED bookings overlapping the night)
matches that function exactly, so reading it is one query instead of up to
31 RPC round-trips for a month view. Its raw `units_available` is NOT
clamped the way `get_room_availability` clamps its own result
(`greatest(coalesce(v,0),0)`) -- an overbooked room can read negative and a
NULL `available_room_count` propagates as NULL -- so `_build_nights` below
applies that same clamp before this module treats `available <= 0` as
"Đã kín" (L50).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client

room_prices_router = APIRouter(tags=["admin-room-prices"])

_MAX_NIGHTS = 366
_DEFAULT_CURRENCY = "VND"


class NightRow(BaseModel):
    date: str
    price: str
    currency: str
    sold_out: bool
    available: int | None
    source: Literal["manual", "pipeline"]
    row_count: int


class RangeRow(BaseModel):
    """A VIEW over consecutive `nights` with equal `(price, currency,
    sold_out)` -- not a storage model (see module docstring). `deletable` is
    true when at least one night in the range has an admin-written row
    (`source_url IS NULL`); DELETE only ever removes those rows, so a range
    built entirely from OTA rows must hide the delete action (L52). `source`
    mirrors `deletable`'s "any admin row" rule (not just the first night's
    winner) so a range never reports `source: "pipeline"` while also being
    `deletable: true`."""

    model_config = ConfigDict(populate_by_name=True)

    from_date: str = Field(alias="from")
    to: str
    nights: int
    price: str
    currency: str
    sold_out: bool
    source: Literal["manual", "pipeline"]
    deletable: bool


class RoomPricesResponse(BaseModel):
    room_id: str
    room_name: str
    hotel_id: str
    hotel_name: str
    is_manual: bool
    currency: str
    nights: list[NightRow]
    ranges: list[RangeRow]


class SetRoomPricesRequest(BaseModel):
    """PUT body -- a discrete list of nights, not a range: the calendar's
    `Chỉ T7 & CN` selection is non-contiguous, and expanding `Lặp lại 4 tuần`
    into individual dates is the frontend's job (`expand-dates.ts`) so this
    endpoint never needs to know about repeat rules."""

    dates: list[date] = Field(min_length=1, max_length=_MAX_NIGHTS)
    # Matches room_prices.price's DECIMAL(12,2) column exactly (10 integer
    # digits + 2 decimal) -- without this ceiling, an oversized value 500s
    # on Postgres' "numeric field overflow" instead of 422ing cleanly.
    price: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    currency: str = Field(min_length=1, max_length=10)
    sold_out: bool = False

    @field_validator("dates", mode="before")
    @classmethod
    def _dedupe_and_sort(cls, value: list[date]) -> list[date]:
        # mode="before" so this runs ahead of the max_length check above --
        # a caller submitting >366 raw entries that dedupe to <=366 unique
        # nights (e.g. a UI bug double-sending a date) must not 422 on a
        # count that was never going to be written anyway.
        return sorted(set(value))


class SetRoomPricesResponse(BaseModel):
    written: int
    created: int
    updated: int


class DeleteRoomPricesResponse(BaseModel):
    deleted: int


def _fetch_room_with_hotel(room_id: str) -> dict[str, Any] | None:
    rows = (
        get_supabase_client()
        .table("rooms")
        .select("id,name,hotel_id,available_room_count,hotels(name,source_platform)")
        .eq("id", room_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _fetch_price_rows_by_night(room_id: str, from_date: date, to_date: date) -> dict[str, list[dict[str, Any]]]:
    rows = (
        get_supabase_client()
        .table("room_prices")
        .select("price,currency,check_in_date,sold_out,source_url,crawled_at")
        .eq("room_id", room_id)
        .gte("check_in_date", from_date.isoformat())
        .lt("check_in_date", to_date.isoformat())
        .execute()
        .data
        or []
    )
    by_night: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_night[row["check_in_date"]].append(row)
    return by_night


def _fetch_availability_by_night(room_id: str, from_date: date, to_date: date) -> dict[str, int]:
    rows = (
        get_supabase_client()
        .table("room_night_occupancy")
        .select("night,units_available")
        .eq("room_id", room_id)
        .gte("night", from_date.isoformat())
        .lt("night", to_date.isoformat())
        .execute()
        .data
        or []
    )
    return {row["night"]: row["units_available"] for row in rows}


def _clamp_availability(value: int | None) -> int | None:
    """Mirrors `get_room_availability`'s own `greatest(coalesce(v,0),0)` --
    `room_night_occupancy.units_available` is unclamped, so an overbooked
    room reads negative and a NULL `available_room_count` propagates as
    NULL through the view (see module docstring)."""
    if value is None:
        return None
    return max(value, 0)


def _build_nights(by_night: dict[str, list[dict[str, Any]]], availability_by_night: dict[str, int], base_capacity: int | None) -> list[NightRow]:
    nights: list[NightRow] = []
    for night_str in sorted(by_night):
        rows_for_night = by_night[night_str]
        latest = max(rows_for_night, key=lambda r: str(r.get("crawled_at") or ""))
        if latest.get("price") is None:
            continue
        raw_available = availability_by_night.get(night_str, base_capacity)
        nights.append(
            NightRow(
                date=night_str,
                price=str(Decimal(str(latest["price"]))),
                currency=latest.get("currency") or _DEFAULT_CURRENCY,
                sold_out=bool(latest.get("sold_out")),
                available=_clamp_availability(raw_available),
                source="manual" if latest.get("source_url") is None else "pipeline",
                row_count=len(rows_for_night),
            )
        )
    return nights


def _build_ranges(by_night: dict[str, list[dict[str, Any]]], nights: list[NightRow]) -> list[RangeRow]:
    """Same merge algorithm regardless of which frontend view renders it
    (L: `ranges[]` gộp ở backend, không ở frontend) -- consecutive nights
    with equal `(price, currency, sold_out)` become one row. `currency` is
    in the merge key so two adjacent nights that happen to carry the same
    numeral in different currencies (a mixed-currency ETL room) never merge
    into one row claiming a single price."""
    ranges: list[RangeRow] = []
    group: dict[str, Any] | None = None

    def flush() -> None:
        if group is None:
            return
        ranges.append(
            RangeRow(
                from_date=group["from_date"].isoformat(),
                to=group["to_date"].isoformat(),
                nights=group["nights"],
                price=group["price"],
                currency=group["currency"],
                sold_out=group["sold_out"],
                # Mirrors `deletable`'s "any night" rule, not just the first
                # night's winner -- a range with a mix of admin/OTA nights
                # must not claim source="pipeline" while deletable=true.
                source="manual" if group["has_manual"] else "pipeline",
                deletable=group["has_manual"],
            )
        )

    for night in nights:
        night_date = date.fromisoformat(night.date)
        has_manual_row = any(row.get("source_url") is None for row in by_night[night.date])
        same_group = (
            group is not None
            and night_date == group["to_date"]
            and night.price == group["price"]
            and night.currency == group["currency"]
            and night.sold_out == group["sold_out"]
        )
        if group is not None and same_group:
            group["to_date"] = night_date + timedelta(days=1)
            group["nights"] += 1
            group["has_manual"] = group["has_manual"] or has_manual_row
        else:
            flush()
            group = {
                "from_date": night_date,
                "to_date": night_date + timedelta(days=1),
                "nights": 1,
                "price": night.price,
                "currency": night.currency,
                "sold_out": night.sold_out,
                "has_manual": has_manual_row,
            }
    flush()
    return ranges


def _validate_range(from_date: date, to: date) -> str | None:
    if to <= from_date:
        return "to must be after from"
    if (to - from_date).days > _MAX_NIGHTS:
        return f"range must not exceed {_MAX_NIGHTS} nights"
    return None


@room_prices_router.get("/rooms/{room_id}/prices", response_model=RoomPricesResponse)
def get_room_prices(room_id: str, from_date: date = Query(alias="from"), to: date = Query()) -> RoomPricesResponse | JSONResponse:
    range_error = _validate_range(from_date, to)
    if range_error:
        return JSONResponse(status_code=422, content={"detail": range_error})

    room = _fetch_room_with_hotel(room_id)
    if room is None:
        return JSONResponse(status_code=404, content={"detail": "room_not_found"})
    hotel = room.get("hotels") or {}

    by_night = _fetch_price_rows_by_night(room_id, from_date, to)
    availability_by_night = _fetch_availability_by_night(room_id, from_date, to)
    nights = _build_nights(by_night, availability_by_night, room.get("available_room_count"))
    ranges = _build_ranges(by_night, nights)

    return RoomPricesResponse(
        room_id=room_id,
        room_name=room["name"],
        hotel_id=room["hotel_id"],
        hotel_name=hotel.get("name") or "",
        is_manual=hotel.get("source_platform") == "manual",
        currency=nights[0].currency if nights else _DEFAULT_CURRENCY,
        nights=nights,
        ranges=ranges,
    )


@room_prices_router.put("/rooms/{room_id}/prices", response_model=SetRoomPricesResponse)
def set_room_prices(room_id: str, body: SetRoomPricesRequest, admin: AdminUser = Depends(require_admin)) -> SetRoomPricesResponse | JSONResponse:
    if _fetch_room_with_hotel(room_id) is None:
        return JSONResponse(status_code=404, content={"detail": "room_not_found"})

    result = (
        get_supabase_client()
        .rpc(
            "admin_upsert_room_prices",
            {
                "p_room_id": room_id,
                "p_nights": [d.isoformat() for d in body.dates],
                "p_price": str(body.price),
                "p_currency": body.currency,
                "p_sold_out": body.sold_out,
            },
        )
        .execute()
        .data
    )
    row = result[0] if result else {"written": 0, "created": 0, "updated": 0}

    # One summarized row per call, not one per night (risk table: 366 audit
    # rows for a year of prices would drown admin_audit_log).
    write_audit(
        admin,
        action="price.set",
        entity_type="room",
        entity_id=room_id,
        after={
            "from": body.dates[0].isoformat(),
            "to": body.dates[-1].isoformat(),
            "nights": len(body.dates),
            "price": str(body.price),
            "currency": body.currency,
            "sold_out": body.sold_out,
        },
    )
    return SetRoomPricesResponse(written=row["written"], created=row["created"], updated=row["updated"])


@room_prices_router.delete("/rooms/{room_id}/prices", response_model=DeleteRoomPricesResponse)
def delete_room_prices(
    room_id: str, from_date: date = Query(alias="from"), to: date = Query(), admin: AdminUser = Depends(require_admin)
) -> DeleteRoomPricesResponse | JSONResponse:
    range_error = _validate_range(from_date, to)
    if range_error:
        return JSONResponse(status_code=422, content={"detail": range_error})
    if _fetch_room_with_hotel(room_id) is None:
        return JSONResponse(status_code=404, content={"detail": "room_not_found"})

    # Only ever deletes admin-written rows (source_url IS NULL) -- an OTA
    # row is left alone, it would just reappear on the next crawl (L52).
    deleted_rows = (
        get_supabase_client()
        .table("room_prices")
        .delete()
        .eq("room_id", room_id)
        .gte("check_in_date", from_date.isoformat())
        .lt("check_in_date", to.isoformat())
        .is_("source_url", "null")
        .execute()
        .data
        or []
    )
    deleted = len(deleted_rows)
    if deleted:
        write_audit(
            admin,
            action="price.delete",
            entity_type="room",
            entity_id=room_id,
            before={"from": from_date.isoformat(), "to": to.isoformat(), "deleted": deleted},
        )
    return DeleteRoomPricesResponse(deleted=deleted)
