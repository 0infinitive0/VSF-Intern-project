"""Admin B5 -- Quản lý phòng (phase-10-rooms.md). Tab `Phòng` inside B3:
`bookings.room_id` is a hard dependency (`ON DELETE RESTRICT`, `NOT NULL`) --
a hotel with zero rooms cannot be sold and the bot will never recommend it,
so this is not an optional CRUD screen.

A room's `is_manual`/pipeline-managed posture is the SAME as its parent
hotel's -- `rooms` has no `source_platform` column of its own (see
`admin_hotel_rows`'s `is_manual = source_platform = 'manual'`), so an
admin-created room inside an ETL-sourced hotel is still fully editable, just
warned (decision #7, same posture as B3's hotel-level fields). Manually
created rooms get `source_room_id = nextval('manual_room_source_id_seq')`
(20260824_add_manual_room_source_id_rpc.sql) -- a range (starts at
9,000,000,000) chosen to never collide with a real OTA numeric room id.

`RAG_FIELDS_ROOM` (embedding_fields.py) mirrors B3's `EMBEDDING_FIELDS`
pattern: touching `name`/`bed_description`/`view`/`room_facilities` clears
`rooms.embedding`; `max_guests`/`room_size_sqm`/`images` do not. The DAG's
`rooms` branch of `_build_text` must stay byte-for-byte unchanged -- this
file never touches embed_supabase_dag.py.

`lowest_price_30d` (L44) is computed as ONE query across every room_id of the
hotel (not per-room -- see the plan's N+1 risk mitigation), same
`.in_(room_ids)` + date-range pattern as `services/place_details.py`.
`booking_count` counts bookings in EVERY status (including CANCELLED --
still real history per L45) since it gates hard-delete, not just display.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from src.api.admin.amenities import AmenityOption
from src.api.admin.audit import write_audit
from src.api.admin.embedding_fields import RAG_FIELDS_ROOM
from src.api.admin.hotels import UploadImageResponse
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services.amenity_catalog import query_all_approved_amenities_by_ids, query_approved_amenities

logger = logging.getLogger(__name__)

rooms_router = APIRouter(tags=["admin-rooms"])

_MAX_IMAGES = 50
_LOWEST_PRICE_WINDOW_DAYS = 30
_ROOM_FACILITY_SCOPES = frozenset({"room", "both"})
# Reuses B3's `hotel-images` Storage bucket (20260824_add_hotel_images_storage_bucket.sql)
# instead of provisioning a second bucket -- rooms need the same
# public-read/5MB/jpeg-png-webp posture, and adding another bucket migration
# just widens the "was this actually applied to the live DB" surface (see
# rooms.py's rolling-deploy fallbacks above). Uploads are namespaced under a
# `rooms/` path prefix so they don't mix with hotel-level uploads (`{hotel_id}/...`)
# in the same bucket.
_ROOM_IMAGES_BUCKET = "hotel-images"
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_ROOM_FIELDS = (
    "id,hotel_id,source_room_id,name,bed_description,room_size_sqm,max_occupancy_raw,max_guests,"
    "view,room_facilities,available_room_count,embedding,images,image_count"
)
# Rolling-deploy fallback: `max_occupancy_raw` is declared in
# database_schema.sql and written by hotel_pipeline.py, but a deployment
# whose Postgres hasn't had that column added yet 42703s on the select
# above. Same posture as amenity_catalog.py's `_LEGACY_CATALOG_FIELDS`
# retry -- degrade the one field rather than 500 the whole tab.
_ROOM_FIELDS_LEGACY = _ROOM_FIELDS.replace("max_occupancy_raw,", "")


class RoomRow(BaseModel):
    id: str
    name: str
    max_guests: int | None = None
    max_occupancy_raw: str | None = None
    bed_description: str | None = None
    room_size_sqm: float | None = None
    view: str | None = None
    room_facilities: list[str]
    facility_count: int
    images: list[str]
    image_count: int
    available_room_count: int | None = None
    lowest_price_30d: str | None = None
    currency: str
    embedding_state: Literal["embedded", "missing"]
    is_manual: bool
    booking_count: int


class RoomListResponse(BaseModel):
    items: list[RoomRow]


class CreateRoomRequest(BaseModel):
    """POST /hotels/{hotel_id}/rooms body. `max_length`s mirror the `rooms`
    column widths (`name`/`view` VARCHAR(255)) in database_schema.sql."""

    name: str = Field(min_length=1, max_length=255)
    max_guests: int | None = Field(default=None, ge=1, le=10)
    bed_description: str | None = Field(default=None, max_length=500)
    room_size_sqm: float | None = Field(default=None, ge=0, le=9999.99)
    view: str | None = Field(default=None, max_length=255)
    room_facilities: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list, max_length=_MAX_IMAGES)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @field_validator("images")
    @classmethod
    def _images_are_http_urls(cls, value: list[str]) -> list[str]:
        for url in value:
            if len(url) > 2048 or not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError(f"invalid image url: {url[:80]!r}")
        return value


class UpdateRoomRequest(BaseModel):
    """PATCH /rooms/{room_id} partial update -- only fields present in the
    body (`model_fields_set`) are considered, same posture as B3's
    UpdateHotelRequest."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    max_guests: int | None = Field(default=None, ge=1, le=10)
    bed_description: str | None = Field(default=None, max_length=500)
    room_size_sqm: float | None = Field(default=None, ge=0, le=9999.99)
    view: str | None = Field(default=None, max_length=255)
    room_facilities: list[str] | None = None
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


class CreateRoomResponse(BaseModel):
    id: str
    source_room_id: int
    embedding_state: Literal["missing"]


class UpdateRoomResponse(BaseModel):
    id: str
    changed_fields: list[str]
    rag_fields_changed: list[str]
    embedding_cleared: bool
    embedding_state: Literal["embedded", "missing"]


def _fetch_hotel_ref(hotel_id: str) -> dict[str, Any] | None:
    rows = get_supabase_client().table("hotels").select("id,source_platform").eq("id", hotel_id).limit(1).execute().data
    return rows[0] if rows else None


def _select_rooms(query_fn: Any) -> list[dict[str, Any]]:
    """Runs `query_fn(fields)` against `_ROOM_FIELDS`, retrying with
    `_ROOM_FIELDS_LEGACY` on a missing-column error (see `_ROOM_FIELDS_LEGACY`
    docstring above)."""
    try:
        return query_fn(_ROOM_FIELDS).execute().data or []
    except Exception as exc:
        if "max_occupancy_raw" not in str(exc):
            raise
        logger.warning("rooms.max_occupancy_raw missing -- falling back to legacy field list: %s", exc)
        return query_fn(_ROOM_FIELDS_LEGACY).execute().data or []


def _fetch_room_row(room_id: str) -> dict[str, Any] | None:
    rows = _select_rooms(lambda fields: get_supabase_client().table("rooms").select(fields).eq("id", room_id).limit(1))
    return rows[0] if rows else None


def _fetch_rooms_for_hotel(hotel_id: str) -> list[dict[str, Any]]:
    return _select_rooms(lambda fields: get_supabase_client().table("rooms").select(fields).eq("hotel_id", hotel_id).order("name"))


def _fetch_lowest_prices_30d(room_ids: list[str]) -> dict[str, tuple[Decimal, str]]:
    """One query for every room of the hotel (not per-room -- plan's N+1
    mitigation), mirroring `services/place_details.py`'s `.in_(room_ids)` +
    date-range read. `min(price)` computed in Python across the returned
    rows, keyed by `room_id`."""
    if not room_ids:
        return {}
    today = date.today()
    horizon = today + timedelta(days=_LOWEST_PRICE_WINDOW_DAYS)
    rows = (
        get_supabase_client()
        .table("room_prices")
        .select("room_id,price,currency")
        .in_("room_id", room_ids)
        .eq("sold_out", False)
        .gte("check_in_date", today.isoformat())
        .lt("check_in_date", horizon.isoformat())
        .execute()
        .data
        or []
    )
    lowest: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        price = row.get("price")
        if price is None:
            continue
        price_dec = Decimal(str(price))
        current = lowest.get(row["room_id"])
        if current is None or price_dec < current[0]:
            lowest[row["room_id"]] = (price_dec, row.get("currency") or "VND")
    return lowest


def _fetch_booking_counts(room_ids: list[str]) -> dict[str, int]:
    """Every booking status counted, including CANCELLED -- gates hard
    delete (L45), where cancelled history still blocks the FK, not just a
    "currently active" display figure."""
    if not room_ids:
        return {}
    rows = get_supabase_client().table("bookings").select("room_id").in_("room_id", room_ids).execute().data or []
    return dict(Counter(row["room_id"] for row in rows))


def _row_to_room(row: dict[str, Any], *, is_manual: bool, lowest_price: tuple[Decimal, str] | None, booking_count: int) -> RoomRow:
    facilities = row.get("room_facilities") or []
    images = row.get("images") or []
    return RoomRow(
        id=row["id"],
        name=row["name"],
        max_guests=row.get("max_guests"),
        max_occupancy_raw=row.get("max_occupancy_raw"),
        bed_description=row.get("bed_description"),
        room_size_sqm=float(row["room_size_sqm"]) if row.get("room_size_sqm") is not None else None,
        view=row.get("view"),
        room_facilities=facilities,
        facility_count=len(facilities),
        images=images,
        # Computed from `images` itself, not the stored column -- guarantees
        # the invariant in every response even for a pre-existing ETL row
        # whose stored `image_count` predates this endpoint and may have
        # drifted (writes here always keep the two in sync; reads shouldn't
        # trust a value that predates that guarantee).
        image_count=len(images),
        available_room_count=row.get("available_room_count"),
        lowest_price_30d=str(lowest_price[0]) if lowest_price else None,
        currency=lowest_price[1] if lowest_price else "VND",
        embedding_state="embedded" if row.get("embedding") is not None else "missing",
        is_manual=is_manual,
        booking_count=booking_count,
    )


@rooms_router.get("/hotels/{hotel_id}/rooms", response_model=RoomListResponse)
def list_rooms(hotel_id: str) -> RoomListResponse | JSONResponse:
    hotel = _fetch_hotel_ref(hotel_id)
    if hotel is None:
        return JSONResponse(status_code=404, content={"detail": "hotel_not_found"})
    is_manual = hotel["source_platform"] == "manual"

    rooms = _fetch_rooms_for_hotel(hotel_id)
    room_ids = [room["id"] for room in rooms]
    lowest_prices = _fetch_lowest_prices_30d(room_ids)
    booking_counts = _fetch_booking_counts(room_ids)

    return RoomListResponse(
        items=[
            _row_to_room(room, is_manual=is_manual, lowest_price=lowest_prices.get(room["id"]), booking_count=booking_counts.get(room["id"], 0))
            for room in rooms
        ]
    )


def _invalid_room_facility_ids(facility_ids: list[str]) -> list[str]:
    """Same posture as B3's `_invalid_amenity_ids`: exact-ID, non-fuzzy
    lookup for a chip-toggle UI that only ever sends catalog IDs it was
    already handed by GET /room-facilities -- not `bind_amenity_rows`, which
    exists for free-text discovery from chat/ETL input."""
    if not facility_ids:
        return []
    entries = query_all_approved_amenities_by_ids(facility_ids)
    valid_ids = {entry.id for entry in entries if entry.scope in _ROOM_FACILITY_SCOPES}
    return [fid for fid in facility_ids if fid not in valid_ids]


def _next_manual_room_source_id() -> int:
    value = get_supabase_client().rpc("next_manual_room_source_id", {}).execute().data
    if not isinstance(value, int):
        raise RuntimeError(f"next_manual_room_source_id() returned {value!r}, expected int")
    return value


@rooms_router.post("/hotels/{hotel_id}/rooms", response_model=CreateRoomResponse, status_code=201)
def create_room(hotel_id: str, body: CreateRoomRequest, admin: AdminUser = Depends(require_admin)) -> CreateRoomResponse | JSONResponse:
    if _fetch_hotel_ref(hotel_id) is None:
        return JSONResponse(status_code=404, content={"detail": "hotel_not_found"})

    invalid = _invalid_room_facility_ids(body.room_facilities)
    if invalid:
        return JSONResponse(status_code=422, content={"detail": f"Tiện nghi không hợp lệ: {', '.join(invalid)}"})

    source_room_id = _next_manual_room_source_id()
    payload: dict[str, Any] = {
        "hotel_id": hotel_id,
        "source_room_id": source_room_id,
        "embedding": None,
        "name": body.name,
        "max_guests": body.max_guests,
        "bed_description": body.bed_description,
        "room_size_sqm": body.room_size_sqm,
        "view": body.view,
        "room_facilities": body.room_facilities,
        "images": body.images,
        "image_count": len(body.images),
    }
    row = get_supabase_client().table("rooms").insert(payload).execute().data[0]
    write_audit(admin, action="room.create", entity_type="room", entity_id=row["id"], after=payload)
    return CreateRoomResponse(id=row["id"], source_room_id=source_room_id, embedding_state="missing")


_DIRECT_UPDATE_FIELDS = ("name", "max_guests", "bed_description", "room_size_sqm", "view")


@rooms_router.patch("/rooms/{room_id}", response_model=UpdateRoomResponse)
def update_room(room_id: str, body: UpdateRoomRequest, admin: AdminUser = Depends(require_admin)) -> UpdateRoomResponse | JSONResponse:
    current = _fetch_room_row(room_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "room_not_found"})

    provided = body.model_fields_set
    changed: dict[str, Any] = {}

    for field in _DIRECT_UPDATE_FIELDS:
        if field in provided:
            new_value = getattr(body, field)
            if new_value != current.get(field):
                changed[field] = new_value

    if "room_facilities" in provided:
        new_facilities = body.room_facilities or []
        current_facilities = current.get("room_facilities") or []
        new_ids, current_ids = set(new_facilities), set(current_facilities)
        invalid = _invalid_room_facility_ids(sorted(new_ids - current_ids))
        if invalid:
            return JSONResponse(status_code=422, content={"detail": f"Tiện nghi không hợp lệ: {', '.join(invalid)}"})
        # Set comparison, not list -- a same-set reorder must not read as
        # "changed" and trigger a needless re-embed (same reasoning as B3's
        # amenities diff).
        if new_ids != current_ids:
            changed["room_facilities"] = new_facilities

    if "images" in provided:
        new_images = body.images or []
        if new_images != (current.get("images") or []):
            changed["images"] = new_images
            changed["image_count"] = len(new_images)

    rag_changed = sorted(set(changed) & set(RAG_FIELDS_ROOM))
    if not changed:
        return UpdateRoomResponse(
            id=room_id,
            changed_fields=[],
            rag_fields_changed=[],
            embedding_cleared=False,
            embedding_state="embedded" if current.get("embedding") is not None else "missing",
        )

    write_payload = dict(changed)
    if rag_changed:
        write_payload["embedding"] = None

    get_supabase_client().table("rooms").update(write_payload).eq("id", room_id).execute()
    write_audit(
        admin,
        action="room.update",
        entity_type="room",
        entity_id=room_id,
        before={field: current.get(field) for field in changed},
        after=changed,
    )

    embedded = not rag_changed and current.get("embedding") is not None
    return UpdateRoomResponse(
        id=room_id,
        changed_fields=sorted(changed),
        rag_fields_changed=rag_changed,
        embedding_cleared=bool(rag_changed),
        embedding_state="embedded" if embedded else "missing",
    )


@rooms_router.delete("/rooms/{room_id}", status_code=204, response_model=None)
def delete_room(room_id: str, admin: AdminUser = Depends(require_admin)) -> Response | JSONResponse:
    current = _fetch_room_row(room_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "room_not_found"})

    booking_count = _fetch_booking_counts([room_id]).get(room_id, 0)
    if booking_count > 0:
        return JSONResponse(status_code=409, content={"detail": "room_has_bookings", "count": booking_count})

    get_supabase_client().table("rooms").delete().eq("id", room_id).execute()
    write_audit(admin, action="room.delete", entity_type="room", entity_id=room_id, before=current)
    return Response(status_code=204)


@rooms_router.get("/room-facilities", response_model=list[AmenityOption])
def list_room_facilities() -> list[AmenityOption]:
    """Catalog options for the drawer's `Tiện nghi phòng` chips (L43) --
    scope `room`/`both`, same shape as B3's GET /amenities but filtered to
    the room-eligible scopes instead of hotel-eligible ones."""
    return [
        AmenityOption(id=entry.id, label_vi=entry.label, label_en=entry.label_en, category=entry.category)
        for entry in query_approved_amenities()
        if entry.scope in _ROOM_FACILITY_SCOPES
    ]


@rooms_router.post("/rooms/{room_id}/images/upload", response_model=UploadImageResponse, status_code=201)
async def upload_room_image(
    room_id: str, file: UploadFile = File(...), admin: AdminUser = Depends(require_admin)
) -> UploadImageResponse:
    """Uploads one file to the shared `hotel-images` bucket under a
    `rooms/{room_id}/` path and returns its public URL -- does not touch
    `rooms.images` itself. Same contract as B3's `upload_hotel_image`
    (backend/src/api/admin/hotels.py): the drawer adds the returned URL to
    its local `images` array and saves it through the ordinary
    PATCH/POST `images` field, so one write path handles both a pasted URL
    and an uploaded file. `room_id` only namespaces the storage path and is
    not checked against `rooms` -- the only caller is the room drawer, which
    only has a real id in edit mode (a room being created has none yet, so
    upload there is disabled client-side, not enforced here)."""
    del admin
    extension = _ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=422, detail="unsupported_image_type")

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="image_too_large")

    path = f"rooms/{room_id}/{uuid4()}.{extension}"
    bucket = get_supabase_client().storage.from_(_ROOM_IMAGES_BUCKET)
    bucket.upload(path, data, {"content-type": file.content_type})
    return UploadImageResponse(url=bucket.get_public_url(path))
