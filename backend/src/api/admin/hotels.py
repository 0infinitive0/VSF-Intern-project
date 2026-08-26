"""Admin B1/B2 -- Danh sách khách sạn + Tạo khách sạn mới
(phase-07-hotels-list.md, phase-08-hotel-create.md).

Reads go through the `admin_hotel_rows` view (one row per hotel with
room_count + embedding coverage pre-aggregated, see
scripts/migrations/20260824_add_admin_hotel_view.sql) so listing never does
N+1 per-hotel lookups. Writes (`is_active` toggle) stay on the `hotels` table
directly and always check for live CONFIRMED bookings first: deactivating a
hotel a guest is mid-stay or about to check into would strand them with no
room, so that path 409s instead (plan's L20 mitigation) rather than the B4
confirmation dialog the design called for and decision #10 cut.

`create_hotel` (B2) is the one write path that inserts a new `hotels` row.
`source_platform` is hardcoded to 'manual' and never read from the request --
see CreateHotelRequest's docstring for why -- and `source_hotel_id` comes
from `next_manual_hotel_source_id()` (a thin RPC wrapper over
manual_hotel_source_id_seq, see
scripts/migrations/20260824_add_manual_hotel_source_id_rpc.sql), since
`source_hotel_id` is BIGINT NOT NULL with no DB default and no UUID variant.
The row's `embedding` starts NULL, same as every other write path: nothing
here ever sets it, so a manually created hotel is invisible to
`match_hotels_with_rooms` until the embedding DAG runs (the plan's mandatory
banner, not a bug).

Admin B3 -- Chi tiết / Sửa khách sạn (phase-09-hotel-edit.md): `get_hotel`,
`update_hotel`. The reembed trigger itself lives in `embedding.py`'s
`POST /hotels/reembed` (phase-12-embedding-status.md) -- one shared endpoint
for B1/B3/B5/B7 instead of a per-screen stub. Decision #7 (R1, phương án iii)
means an ETL-sourced hotel is still fully editable here -- `pipeline_managed_fields`
(from `embedding_fields.PIPELINE_MANAGED_FIELDS_HOTEL`) only drives a UI
warning, never a server-side write block. `update_hotel` diffs the request
body against the current row itself (`model_fields_set`, not a client-sent
flag) and clears `embedding` whenever a touched column intersects
`embedding_fields.EMBEDDING_FIELDS` -- the same "backend decides, not the
client" posture as B2's `source_platform`.

`upload_hotel_image` (B3's Hình ảnh tab, L38) uploads to the `hotel-images`
Storage bucket (scripts/migrations/20260824_add_hotel_images_storage_bucket.sql)
via the service-role client and hands back a public URL -- it does not touch
`hotels.images` itself. The frontend adds that URL to the array locally and
saves it through the ordinary `PATCH /{hotel_id}` (`images` field), so one
write path handles both a pasted URL and an uploaded file.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from src.api.admin.audit import write_audit
from src.api.admin.embedding_fields import EMBEDDING_FIELDS, PIPELINE_MANAGED_FIELDS_HOTEL
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services.amenity_catalog import query_all_approved_amenities_by_ids
from src.services.routing import parse_coordinates

hotels_router = APIRouter(prefix="/hotels", tags=["admin-hotels"])

_VIEW = "admin_hotel_rows"
_DEFAULT_PAGE_SIZE = 25
_MAX_PAGE_SIZE = 100
# B1's sortable header -> admin_hotel_rows column. "embedding" has no single
# backing column (embedding_state is derived in _embedding_state) --
# ordering by hotel_embedded then rooms_missing_embedding approximates it.
# An unrecognized/absent `sort` falls back to the default order below rather
# than 422ing, since the only caller is this project's own admin frontend.
_SORT_COLUMNS: dict[str, str] = {
    "hotel": "name",
    "city": "city",
    "star_rating": "star_rating",
    "source": "is_manual",
    "room_count": "room_count",
    "embedding": "hotel_embedded",
    "active": "is_active",
}
# CSV export ignores pagination (an admin exporting a filtered set wants the
# whole set, not whatever page happened to be on screen) but still needs a
# ceiling so one request can't pull the entire table unbounded.
_CSV_MAX_ROWS = 10_000
_MAX_BLOCKING_BOOKINGS_LISTED = 5
# Ceiling for the accommodation-type suggestion list -- one request, no
# pagination (see list_accommodation_types docstring). Comfortably above the
# live table's ~1100 rows.
_ACCOMMODATION_TYPES_SCAN_LIMIT = 5000
_DESCRIPTION_MAX_LENGTH = 1000
_LOCATION_HIGHLIGHT_MAX_LENGTH = 255
_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
# Explicit column list for the B3 detail read -- excludes `embedding`
# (a 1024-float pgvector column: fetching it for a page that never displays
# it would be a large, pointless payload) and a handful of ETL-only columns
# B3 doesn't render this phase (awards, warnings, review_score, ...).
_HOTEL_DETAIL_COLUMNS = (
    "id,name,accommodation_type,description,star_rating,address,city,area_name,"
    "location_highlight,destination_id,coordinates,check_in_time,check_in_until,"
    "check_out_time,amenities,amenity_groups,images,image_url,nearby_attractions,"
    "nearby_essentials,source_platform,is_active"
)
_AMENITY_HOTEL_SCOPES = frozenset({"hotel", "both"})
# B3's Hình ảnh tab (L38) manages `images` as a flat URL list -- this is the
# guard against an unbounded array (a URL can also be pasted directly,
# bypassing upload_hotel_image's own per-file bucket limits below).
_MAX_IMAGES = 50
_HOTEL_IMAGES_BUCKET = "hotel-images"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Mirrors the bucket's own `allowed_mime_types`
# (20260824_add_hotel_images_storage_bucket.sql) -- checked here too so a
# rejected upload 422s with a clear reason instead of surfacing whatever
# error shape the Storage API happens to return.
_ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


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


class CreateHotelRequest(BaseModel):
    """B2 (phase-08-hotel-create.md). `source_platform` is deliberately not a
    field here -- accepting it from the client would let a caller claim an
    OTA origin for a hand-entered row, letting fake data into the ETL
    namespace the pipeline trusts (see module docstring). It is always
    'manual', set server-side in `create_hotel`.

    `max_length`s below mirror the `hotels` column widths in
    database_schema.sql (accommodation_type VARCHAR(50), address VARCHAR(500),
    city VARCHAR(100)) so an over-long value 422s here instead of reaching
    Postgres as an unhandled `22001` (string too long)."""

    name: str = Field(min_length=1, max_length=255)
    accommodation_type: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX_LENGTH)
    star_rating: float | None = Field(default=None, ge=0, le=5, multiple_of=0.5)
    address: str | None = Field(default=None, max_length=500)
    destination_id: UUID | None = None
    city: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    check_in_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    check_out_time: str | None = Field(default=None, pattern=_TIME_PATTERN)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @model_validator(mode="after")
    def _coordinates_both_or_neither(self) -> "CreateHotelRequest":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class CreateHotelResponse(BaseModel):
    id: str
    source_platform: str
    source_hotel_id: int
    embedding_state: Literal["missing"]
    is_active: bool


class HotelDetailResponse(BaseModel):
    """B3 (phase-09-hotel-edit.md). `pipeline_managed_fields`/`rag_fields`
    are computed server-side (see module docstring) so the frontend never
    has to reimplement -- and risk drifting from -- either source of truth."""

    id: str
    name: str
    accommodation_type: str | None = None
    description: str | None = None
    star_rating: float | None = None
    address: str | None = None
    city: str | None = None
    area_name: str | None = None
    location_highlight: str | None = None
    destination_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    check_in_time: str | None = None
    check_in_until: str | None = None
    check_out_time: str | None = None
    amenities: list[str]
    amenity_groups: dict[str, Any] | None = None
    images: list[str]
    image_url: str | None = None
    nearby_attractions: Any | None = None
    nearby_essentials: Any | None = None
    source_platform: str
    is_manual: bool
    is_active: bool
    room_count: int
    embedding_state: Literal["embedded", "partial", "missing"]
    rooms_missing_embedding: int
    pipeline_managed_fields: list[str]
    rag_fields: list[str]


class UpdateHotelRequest(BaseModel):
    """B3 partial update -- every field optional, and only the ones actually
    present in the request body (`model_fields_set`, not "not None") are
    considered for the changed-columns diff in `update_hotel`. Same
    `max_length`s as CreateHotelRequest; `star_rating`/`description`/etc. can
    be explicitly nulled (e.g. clearing "Hạng sao" back to "Chưa chọn"),
    which is exactly why the diff logic keys off presence-in-body rather than
    non-None."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    accommodation_type: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX_LENGTH)
    location_highlight: str | None = Field(default=None, max_length=_LOCATION_HIGHLIGHT_MAX_LENGTH)
    star_rating: float | None = Field(default=None, ge=0, le=5, multiple_of=0.5)
    address: str | None = Field(default=None, max_length=500)
    destination_id: UUID | None = None
    city: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    check_in_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    check_out_time: str | None = Field(default=None, pattern=_TIME_PATTERN)
    amenities: list[str] | None = None
    images: list[str] | None = Field(default=None, max_length=_MAX_IMAGES)

    @field_validator("name")
    @classmethod
    def _name_not_blank_if_provided(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("images")
    @classmethod
    def _images_are_http_urls(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        for url in value:
            if len(url) > 2048 or not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"invalid image url: {url[:80]!r}")
        return value

    @model_validator(mode="after")
    def _coordinates_not_split_null(self) -> "UpdateHotelRequest":
        """Only enforced when BOTH keys are in the body -- a request that
        supplies just one of the two is a legitimate partial update
        (`update_hotel` recombines it with whichever value is already
        stored). But if both are present, one null + one set would silently
        wipe `coordinates` entirely (`update_hotel`'s recombination treats
        "no latitude" the same whether it's absent or explicitly null)."""
        fields = self.model_fields_set
        if "latitude" in fields and "longitude" in fields and (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null when both are provided")
        return self


class UpdateHotelResponse(BaseModel):
    id: str
    changed_fields: list[str]
    rag_fields_changed: list[str]
    embedding_cleared: bool
    embedding_state: Literal["embedded", "partial", "missing"]


class UploadImageResponse(BaseModel):
    url: str


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
    embedding: Literal["embedded", "missing", "incomplete", "all"],
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
    elif embedding == "incomplete":
        # B7's own filter (phase-12-embedding-status.md): a hotel with its
        # own embedding set but rooms still missing theirs ("partial" in
        # `_embedding_state`) is not "missing" by B1's `hotel_embedded`-only
        # definition, but B7 exists to surface exactly this case too --
        # answering "bot còn chưa học những gì?" requires both.
        query = query.or_("hotel_embedded.eq.false,rooms_missing_embedding.gt.0")
    return query


def _fetch_hotels(
    *,
    q: str | None,
    source: Literal["manual", "pipeline", "all"],
    is_active: bool | None,
    embedding: Literal["embedded", "missing", "incomplete", "all"],
    start: int,
    end: int,
    sort: str | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
) -> tuple[list[dict[str, Any]], int]:
    query = get_supabase_client().table(_VIEW).select("*", count="exact")
    query = _apply_filters(query, q=q, source=source, is_active=is_active, embedding=embedding)
    column = _SORT_COLUMNS.get(sort or "")
    if column is None:
        query = query.order("updated_at", desc=True)
    else:
        desc = sort_dir == "desc"
        query = query.order(column, desc=desc)
        if column == "hotel_embedded":
            query = query.order("rooms_missing_embedding", desc=desc)
        query = query.order("id")  # stable tiebreak so pagination doesn't reshuffle ties
    response = query.range(start, end).execute()
    return response.data or [], response.count or 0


def _csv_safe(value: str) -> str:
    """Prefixes a leading =/+/-/@ with a tab so spreadsheet apps render the
    cell as text instead of a formula (CSV/formula injection). B2 lets an
    admin type `name`/`address`/`city` freely -- before B2 every row here
    came from ETL, not a human at a keyboard."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "\t" + value
    return value


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
                _csv_safe(hotel.name),
                _csv_safe(hotel.address or ""),
                _csv_safe(hotel.city or ""),
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


def _fetch_accommodation_type_rows() -> list[dict[str, Any]]:
    return (
        get_supabase_client()
        .table("hotels")
        .select("accommodation_type")
        .range(0, _ACCOMMODATION_TYPES_SCAN_LIMIT - 1)
        .execute()
        .data
        or []
    )


@hotels_router.get("/accommodation-types", response_model=list[str])
def list_accommodation_types() -> list[str]:
    """Distinct `accommodation_type` values already in the table, as
    suggestions for B2's combobox (L27) -- ETL free-text from Agoda/Booking,
    so this is not a fixed enum on either side."""
    rows = _fetch_accommodation_type_rows()
    return sorted({row["accommodation_type"] for row in rows if row.get("accommodation_type")})


def _next_manual_hotel_source_id() -> int:
    """nextval() via RPC (see module docstring) -- must never come back empty:
    a NULL here would otherwise surface as an opaque NOT NULL violation on
    the insert below instead of a clear error pointing at the RPC."""
    value = get_supabase_client().rpc("next_manual_hotel_source_id", {}).execute().data
    if not isinstance(value, int):
        raise RuntimeError(f"next_manual_hotel_source_id() returned {value!r}, expected int")
    return value


@hotels_router.post("", response_model=CreateHotelResponse, status_code=201)
def create_hotel(body: CreateHotelRequest, admin: AdminUser = Depends(require_admin)) -> CreateHotelResponse:
    payload: dict[str, Any] = {
        "source_platform": "manual",
        "source_hotel_id": _next_manual_hotel_source_id(),
        "embedding": None,
        "is_active": True,
        "name": body.name,
        "accommodation_type": body.accommodation_type,
        "description": body.description,
        "star_rating": body.star_rating,
        "address": body.address,
        "destination_id": str(body.destination_id) if body.destination_id else None,
        "city": body.city,
        "check_in_time": body.check_in_time,
        "check_out_time": body.check_out_time,
    }
    if body.latitude is not None and body.longitude is not None:
        payload["coordinates"] = f"{body.latitude}, {body.longitude}"

    row = get_supabase_client().table("hotels").insert(payload).execute().data[0]
    write_audit(admin, action="hotel.create", entity_type="hotel", entity_id=row["id"], after=payload)
    return CreateHotelResponse(
        id=row["id"],
        source_platform=row["source_platform"],
        source_hotel_id=row["source_hotel_id"],
        embedding_state="missing",
        is_active=row["is_active"],
    )


@hotels_router.get("", response_model=HotelListResponse)
def list_hotels(
    q: str | None = Query(default=None),
    source: Literal["manual", "pipeline", "all"] = Query(default="all"),
    is_active: bool | None = Query(default=None),
    embedding: Literal["embedded", "missing", "incomplete", "all"] = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    sort: str | None = Query(default=None),
    sort_dir: Literal["asc", "desc"] = Query(default="asc"),
    response_format: Literal["json", "csv"] = Query(default="json", alias="format"),
) -> HotelListResponse | Response:
    if response_format == "csv":
        rows, _total = _fetch_hotels(
            q=q, source=source, is_active=is_active, embedding=embedding, start=0, end=_CSV_MAX_ROWS - 1, sort=sort, sort_dir=sort_dir
        )
        return _hotels_csv_response([_row_to_hotel(row) for row in rows])

    start = (page - 1) * page_size
    rows, total = _fetch_hotels(
        q=q, source=source, is_active=is_active, embedding=embedding, start=start, end=start + page_size - 1, sort=sort, sort_dir=sort_dir
    )
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


# ---------------------------------------------------------------------------
# B3 -- Chi tiết / Sửa khách sạn (phase-09-hotel-edit.md)
# ---------------------------------------------------------------------------


def _fetch_hotel_row(hotel_id: str) -> dict[str, Any] | None:
    rows = (
        get_supabase_client()
        .table("hotels")
        .select(_HOTEL_DETAIL_COLUMNS)
        .eq("id", hotel_id)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _fetch_hotel_admin_aggregates(hotel_id: str) -> dict[str, Any] | None:
    """`room_count`/`hotel_embedded`/`rooms_missing_embedding` -- the same
    per-hotel aggregates B1 lists, read from `admin_hotel_rows` (see module
    docstring) instead of recomputed here."""
    rows = (
        get_supabase_client()
        .table(_VIEW)
        .select("is_manual,hotel_embedded,rooms_missing_embedding,room_count")
        .eq("id", hotel_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def _hotel_row_to_detail(row: dict[str, Any], aggregates: dict[str, Any]) -> HotelDetailResponse:
    is_manual = bool(aggregates["is_manual"])
    coords = parse_coordinates(row.get("coordinates"))
    rooms_missing = aggregates.get("rooms_missing_embedding") or 0
    return HotelDetailResponse(
        id=row["id"],
        name=row["name"],
        accommodation_type=row.get("accommodation_type"),
        description=row.get("description"),
        star_rating=row.get("star_rating"),
        address=row.get("address"),
        city=row.get("city"),
        area_name=row.get("area_name"),
        location_highlight=row.get("location_highlight"),
        destination_id=row.get("destination_id"),
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
        check_in_time=row.get("check_in_time"),
        check_in_until=row.get("check_in_until"),
        check_out_time=row.get("check_out_time"),
        amenities=row.get("amenities") or [],
        amenity_groups=row.get("amenity_groups"),
        images=row.get("images") or [],
        image_url=row.get("image_url"),
        nearby_attractions=row.get("nearby_attractions"),
        nearby_essentials=row.get("nearby_essentials"),
        source_platform=row["source_platform"],
        is_manual=is_manual,
        is_active=row["is_active"],
        room_count=aggregates.get("room_count") or 0,
        embedding_state=_embedding_state(aggregates["hotel_embedded"], rooms_missing),
        rooms_missing_embedding=rooms_missing,
        pipeline_managed_fields=[] if is_manual else list(PIPELINE_MANAGED_FIELDS_HOTEL),
        rag_fields=list(EMBEDDING_FIELDS),
    )


@hotels_router.get("/{hotel_id}", response_model=HotelDetailResponse)
def get_hotel(hotel_id: str) -> HotelDetailResponse | JSONResponse:
    row = _fetch_hotel_row(hotel_id)
    aggregates = _fetch_hotel_admin_aggregates(hotel_id)
    if row is None or aggregates is None:
        return JSONResponse(status_code=404, content={"detail": "hotel_not_found"})
    return _hotel_row_to_detail(row, aggregates)


@hotels_router.delete("/{hotel_id}", status_code=204, response_model=None)
def delete_hotel(hotel_id: str, admin: AdminUser = Depends(require_admin)) -> Response | JSONResponse:
    """Soft delete (`deleted_at`, 20260826_add_hotels_deleted_at.sql) -- never
    a hard `.delete()`. Same guard as `set_hotel_active`'s deactivate path:
    a hotel a guest is mid-stay or about to check into can't just vanish
    from the admin list with no way to manage their stay."""
    current = _fetch_hotel_row(hotel_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "hotel_not_found"})

    count, bookings = _blocking_bookings(hotel_id)
    if count > 0:
        return _blocked_response(count, bookings)

    get_supabase_client().table("hotels").update({"deleted_at": datetime.now(timezone.utc).isoformat(), "is_active": False}).eq(
        "id", hotel_id
    ).execute()
    write_audit(admin, action="hotel.delete", entity_type="hotel", entity_id=hotel_id, before=current)
    return Response(status_code=204)


def _invalid_amenity_ids(amenity_ids: list[str]) -> list[str]:
    """IDs the client sent that are not an approved, hotel-eligible catalog
    entry. Uses `query_all_approved_amenities_by_ids` (an exact-ID,
    non-fuzzy, un-capped lookup) -- not `query_approved_amenities`, whose
    100-ID cap is meant for general callers and would silently mark every id
    past #100 as "invalid" (196 of ~1100 hotels have 100+ amenities in prod);
    and not `resolve_hotel_amenity_ids`/`bind_amenities`, which exist for
    free-text phrases from chat/ETL input and can invoke LLM-based discovery
    for anything unresolved -- the wrong tool (and an unwanted cost) for a
    chip-toggle UI that only ever sends exact catalog IDs already handed to
    it by GET /admin/amenities."""
    if not amenity_ids:
        return []
    entries = query_all_approved_amenities_by_ids(amenity_ids)
    valid_ids = {entry.id for entry in entries if entry.scope in _AMENITY_HOTEL_SCOPES}
    return [aid for aid in amenity_ids if aid not in valid_ids]


_DIRECT_UPDATE_FIELDS = (
    "name",
    "accommodation_type",
    "description",
    "location_highlight",
    "star_rating",
    "address",
    "city",
    "check_in_time",
    "check_out_time",
)


@hotels_router.patch("/{hotel_id}", response_model=UpdateHotelResponse)
def update_hotel(
    hotel_id: str, body: UpdateHotelRequest, admin: AdminUser = Depends(require_admin)
) -> UpdateHotelResponse | JSONResponse:
    current = _fetch_hotel_row(hotel_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "hotel_not_found"})

    provided = body.model_fields_set
    changed: dict[str, Any] = {}

    for field in _DIRECT_UPDATE_FIELDS:
        if field in provided:
            new_value = getattr(body, field)
            if new_value != current.get(field):
                changed[field] = new_value

    if "destination_id" in provided:
        new_value = str(body.destination_id) if body.destination_id else None
        if new_value != current.get("destination_id"):
            changed["destination_id"] = new_value

    if "latitude" in provided or "longitude" in provided:
        current_coords = parse_coordinates(current.get("coordinates"))
        current_lat, current_lng = current_coords if current_coords else (None, None)
        new_lat = body.latitude if "latitude" in provided else current_lat
        new_lng = body.longitude if "longitude" in provided else current_lng
        new_coords = f"{new_lat}, {new_lng}" if new_lat is not None and new_lng is not None else None
        if new_coords != current.get("coordinates"):
            changed["coordinates"] = new_coords

    if "amenities" in provided:
        new_amenities = body.amenities or []
        current_amenities = current.get("amenities") or []
        new_ids, current_ids = set(new_amenities), set(current_amenities)
        # Validate only the newly-added ids: a pre-existing id that's since
        # fallen out of the approved/hotel-eligible catalog stays on the row
        # untouched rather than blocking every future save of this hotel.
        invalid = _invalid_amenity_ids(sorted(new_ids - current_ids))
        if invalid:
            raise HTTPException(status_code=422, detail=f"Tiện ích không hợp lệ: {', '.join(invalid)}")
        # Compared as sets, not lists: hotel-tab-amenities.tsx only ever
        # adds/removes one id per toggle and otherwise preserves the
        # existing array's order, but a stray reorder must not read as
        # "changed" -- amenities is RAG-relevant (EMBEDDING_FIELDS), and
        # clearing embedding + a paid re-embed for a same-set reorder is
        # exactly the "quá tay" cost the plan's risk table warns against.
        if new_ids != current_ids:
            changed["amenities"] = new_amenities

    if "images" in provided:
        new_images = body.images or []
        if new_images != (current.get("images") or []):
            changed["images"] = new_images

    rag_changed = sorted(set(changed) & set(EMBEDDING_FIELDS))
    if not changed:
        aggregates = _fetch_hotel_admin_aggregates(hotel_id)
        state = _embedding_state(aggregates["hotel_embedded"], aggregates.get("rooms_missing_embedding") or 0) if aggregates else "missing"
        return UpdateHotelResponse(id=hotel_id, changed_fields=[], rag_fields_changed=[], embedding_cleared=False, embedding_state=state)

    write_payload = dict(changed)
    if rag_changed:
        # Bot keeps answering from the pre-edit vector until the next
        # only-null embedding DAG run re-embeds this row -- same contract as
        # B2's create path (module docstring), decided server-side only.
        write_payload["embedding"] = None
    # No DB trigger bumps `updated_at` on a postgrest write (only ETL's raw
    # SQL path sets it explicitly) -- B1 orders by `updated_at desc`, so an
    # edited hotel needs this set here or it stays stranded wherever it last
    # sorted.
    write_payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    get_supabase_client().table("hotels").update(write_payload).eq("id", hotel_id).execute()
    write_audit(
        admin,
        action="hotel.update",
        entity_type="hotel",
        entity_id=hotel_id,
        before={field: current.get(field) for field in changed},
        after=changed,
    )

    aggregates = _fetch_hotel_admin_aggregates(hotel_id)
    hotel_embedded = not rag_changed and aggregates is not None and aggregates["hotel_embedded"]
    rooms_missing = aggregates.get("rooms_missing_embedding") or 0 if aggregates else 0
    return UpdateHotelResponse(
        id=hotel_id,
        changed_fields=sorted(changed),
        rag_fields_changed=rag_changed,
        embedding_cleared=bool(rag_changed),
        embedding_state=_embedding_state(hotel_embedded, rooms_missing),
    )


@hotels_router.post("/{hotel_id}/images/upload", response_model=UploadImageResponse, status_code=201)
async def upload_hotel_image(
    hotel_id: str, file: UploadFile = File(...), admin: AdminUser = Depends(require_admin)
) -> UploadImageResponse:
    """Uploads one file to the `hotel-images` bucket and returns its public
    URL -- does not touch `hotels.images` (see module docstring). `hotel_id`
    only namespaces the storage path; this intentionally does not 404 on an
    unknown id, since an orphaned object under a bad id is harmless and the
    only caller is this hotel's own edit page, which already has a real id
    from `GET /{hotel_id}`."""
    del admin
    extension = _ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=422, detail="unsupported_image_type")

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="image_too_large")

    path = f"{hotel_id}/{uuid4()}.{extension}"
    bucket = get_supabase_client().storage.from_(_HOTEL_IMAGES_BUCKET)
    bucket.upload(path, data, {"content-type": file.content_type})
    return UploadImageResponse(url=bucket.get_public_url(path))
