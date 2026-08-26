"""Admin -- Danh mục tiện ích & tiện nghi (phase-18-amenity-catalog.md).

Three status axes, kept deliberately separate:

- `is_approved` -- can this id be selected/served at all (chat search, B3/B5
  pickers)? `false -> true` (Duyệt) is the only valid transition for an
  existing row; there is no `true -> false` write in this file (see below).
- `retired_at` -- "Ngừng dùng". Writes here are gated on
  `admin_amenity_usage.hotel_count + room_count == 0` **and** on having no
  live children (`parent_id = id`, G12) -- retiring a row that's still
  referenced would make `hotels.amenities`/`rooms.room_facilities` carry an
  id `all_approved_amenities()` no longer returns, and the app-chat card
  renderer (`displayAmenityLabels`) shows the raw id string instead of a
  label when that happens. Since retiring is only ever allowed at usage=0,
  that failure mode is structurally impossible through this file -- the
  guard is what makes retire safe, not `retired_at` vs `is_approved` as a
  column choice.
- `needs_review` -- out of scope for this phase (decision #5). The migration
  clears it once; nothing here reads or writes it again.

`is_approved=false` rows are always safe to hard-delete (`DELETE`): per
`bind_amenity_rows` in `services/amenity_catalog.py`, an unapproved id is
never written into `hotels.amenities`/`rooms.room_facilities` -- a pending
row, whatever its source (chat/pipeline discovery or this file's own
`/draft`), has provably never been referenced anywhere.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from src.api.admin.audit import write_audit
from src.auth import AdminUser, require_admin
from src.clients.supabase_client import get_supabase_client
from src.services.amenity_catalog import (
    AMENITY_CATEGORIES,
    AmenityScope,
    clear_all_approved_amenities_cache,
    draft_new_amenities,
    score_against_catalog,
)

logger = logging.getLogger(__name__)

amenity_catalog_router = APIRouter(prefix="/amenity-catalog", tags=["admin-amenity-catalog"])

_TABLE = "amenity_catalog"
_USAGE_VIEW = "admin_amenity_usage"
_ROW_FIELDS = "id,label_vi,label_en,scope,category,icon_key,match_keywords,parent_id,is_approved,retired_at"
_EXACT_SCORE = 0.85
_FLAGGED_SCORE = 0.55
_MAX_PARENT_WALK = 20
_MAX_TEXT_NAMES = 20
_UPDATE_FIELDS = ("label_vi", "label_en", "category", "icon_key", "match_keywords", "parent_id", "scope")
_MUTABLE_FIELD_SET = frozenset(_UPDATE_FIELDS)


# ---------------------------------------------------------------------- #
# Models
# ---------------------------------------------------------------------- #


class AmenityCatalogRow(BaseModel):
    id: str
    label_vi: str
    label_en: str
    scope: Literal["hotel", "room", "both"]
    category: str
    icon_key: str | None = None
    match_keywords: list[str]
    parent_id: str | None = None
    is_approved: bool
    retired_at: str | None = None
    hotel_count: int
    room_count: int
    child_count: int


class AmenityCatalogListResponse(BaseModel):
    items: list[AmenityCatalogRow]
    total: int
    page: int
    page_size: int
    pending_count: int


class AmenityMatch(BaseModel):
    id: str
    label_vi: str
    label_en: str
    score: float


class FlaggedName(BaseModel):
    name: str
    closest: AmenityMatch
    score: float


class CheckDuplicateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    scope: Literal["hotel", "room"]


class CheckDuplicateResponse(BaseModel):
    parsed: list[str]
    exact: list[FlaggedName]
    flagged: list[FlaggedName]
    clear: list[str]


class DraftRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=_MAX_TEXT_NAMES)
    scope: Literal["hotel", "room"]
    acknowledge: list[str] = Field(default_factory=list)

    @field_validator("names")
    @classmethod
    def _names_not_blank(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value if name.strip()]
        if not cleaned:
            raise ValueError("names must contain at least one non-blank entry")
        return cleaned


class DraftResponse(BaseModel):
    items: list[AmenityCatalogRow]
    skipped_exact: list[str]
    skipped_duplicate: list[str]


class UpdateAmenityRequest(BaseModel):
    label_vi: str | None = Field(default=None, min_length=1, max_length=80)
    label_en: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = None
    icon_key: str | None = Field(default=None, max_length=64)
    match_keywords: list[str] | None = Field(default=None, max_length=8)
    parent_id: str | None = None
    scope: Literal["hotel", "room", "both"] | None = None

    @field_validator("category")
    @classmethod
    def _category_is_known(cls, value: str | None) -> str | None:
        if value is not None and value not in AMENITY_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(AMENITY_CATEGORIES)}")
        return value

    @field_validator("match_keywords")
    @classmethod
    def _keywords_bounded(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        for keyword in value:
            if not keyword.strip() or len(keyword) > 80:
                raise ValueError("each keyword must be 1-80 characters")
        return value


class UpdateAmenityResponse(BaseModel):
    id: str
    changed_fields: list[str]


class ApproveResponse(BaseModel):
    id: str
    is_approved: bool


class BulkApproveRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class BulkApproveResponse(BaseModel):
    approved: int


class RetireResponse(BaseModel):
    id: str
    retired_at: str | None


# ---------------------------------------------------------------------- #
# Shared reads
# ---------------------------------------------------------------------- #


def _fetch_row(amenity_id: str) -> dict[str, Any] | None:
    rows = get_supabase_client().table(_TABLE).select(_ROW_FIELDS).eq("id", amenity_id).limit(1).execute().data
    return rows[0] if rows else None


def _fetch_usage(ids: list[str]) -> dict[str, tuple[int, int]]:
    """One query for every id on the current page -- avoids N+1, same
    posture as B5's `_fetch_lowest_prices_30d`/`_fetch_booking_counts`."""
    if not ids:
        return {}
    rows = get_supabase_client().table(_USAGE_VIEW).select("amenity_id,hotel_count,room_count").in_("amenity_id", ids).execute().data or []
    return {row["amenity_id"]: (row.get("hotel_count") or 0, row.get("room_count") or 0) for row in rows}


def _fetch_child_counts(ids: list[str]) -> dict[str, int]:
    """Live (approved, non-retired) children per id, in one query (G12) --
    a parent can show `hotel_count=0` in `admin_amenity_usage` while still
    being unsafe to retire because its children carry all the real usage."""
    if not ids:
        return {}
    rows = (
        get_supabase_client()
        .table(_TABLE)
        .select("parent_id")
        .in_("parent_id", ids)
        .eq("is_approved", True)
        .is_("retired_at", "null")
        .execute()
        .data
        or []
    )
    counts: dict[str, int] = {}
    for row in rows:
        parent_id = row.get("parent_id")
        if parent_id:
            counts[parent_id] = counts.get(parent_id, 0) + 1
    return counts


def _row_to_model(row: dict[str, Any], *, hotel_count: int, room_count: int, child_count: int) -> AmenityCatalogRow:
    return AmenityCatalogRow(
        id=row["id"],
        label_vi=row["label_vi"],
        label_en=row["label_en"],
        scope=row["scope"],
        category=row["category"],
        icon_key=row.get("icon_key"),
        match_keywords=row.get("match_keywords") or [],
        parent_id=row.get("parent_id"),
        is_approved=row["is_approved"],
        retired_at=row.get("retired_at"),
        hotel_count=hotel_count,
        room_count=room_count,
        child_count=child_count,
    )


def _rows_to_models(rows: list[dict[str, Any]]) -> list[AmenityCatalogRow]:
    ids = [row["id"] for row in rows]
    usage = _fetch_usage(ids)
    children = _fetch_child_counts(ids)
    return [
        _row_to_model(row, hotel_count=usage.get(row["id"], (0, 0))[0], room_count=usage.get(row["id"], (0, 0))[1], child_count=children.get(row["id"], 0))
        for row in rows
    ]


def _pending_count() -> int:
    response = get_supabase_client().table(_TABLE).select("id", count="exact").eq("is_approved", False).limit(1).execute()
    return response.count or 0


# ---------------------------------------------------------------------- #
# GET list
# ---------------------------------------------------------------------- #


_DB_SORT_COLUMNS = {"name": "label_vi", "category": "category", "scope": "scope"}


def _status_rank(row: AmenityCatalogRow) -> int:
    """Chờ duyệt < Đã duyệt < Đã ngừng dùng -- same tie-break the frontend's
    own `sortValue` used before this became a server-side sort."""
    if not row.is_approved:
        return 0
    return 2 if row.retired_at else 1


@amenity_catalog_router.get("", response_model=AmenityCatalogListResponse)
def list_amenity_catalog(
    scope: Literal["hotel", "room", "all"] = Query(default="all"),
    status: Literal["approved", "pending", "retired", "all"] = Query(default="all"),
    category: str = Query(default="all"),
    q: str | None = Query(default=None),
    sort: Literal["name", "category", "scope", "usage", "status"] = Query(default="name"),
    direction: Literal["asc", "desc"] = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> AmenityCatalogListResponse:
    query = get_supabase_client().table(_TABLE).select(_ROW_FIELDS)

    if scope != "all":
        query = query.in_("scope", [scope, "both"])
    if status == "approved":
        query = query.eq("is_approved", True).is_("retired_at", "null")
    elif status == "pending":
        query = query.eq("is_approved", False)
    elif status == "retired":
        query = query.eq("is_approved", True).not_.is_("retired_at", "null")
    if category != "all":
        if category not in AMENITY_CATEGORIES:
            return AmenityCatalogListResponse(items=[], total=0, page=page, page_size=page_size, pending_count=_pending_count())
        query = query.eq("category", category)
    if q:
        term = q.replace(",", "")
        query = query.or_(f"label_vi.ilike.%{term}%,label_en.ilike.%{term}%")

    # `usage`/`status` aren't real columns (usage comes from a separate view
    # join in `_rows_to_models`, status is derived) -- there's no way to sort
    # or paginate on them at the postgrest layer. Fetch every row the filters
    # match (a few hundred at most, same "read the whole thing" posture
    # `_query_approved_amenities` already uses for chat search), sort in
    # Python where all three sort kinds can share one code path, then
    # paginate the sorted list -- this is what makes "sort by usage" actually
    # span all pages instead of just whatever 25 rows already loaded.
    desc = direction == "desc"
    if sort in _DB_SORT_COLUMNS:
        query = query.order(_DB_SORT_COLUMNS[sort], desc=desc)
    else:
        query = query.order("label_vi")
    rows = query.execute().data or []
    items = _rows_to_models(rows)

    if sort == "usage":
        items.sort(key=lambda r: r.hotel_count + r.room_count, reverse=desc)
    elif sort == "status":
        items.sort(key=_status_rank, reverse=desc)

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]

    return AmenityCatalogListResponse(
        items=page_items,
        total=total,
        page=page,
        page_size=page_size,
        pending_count=_pending_count(),
    )


@amenity_catalog_router.get("/{amenity_id}", response_model=AmenityCatalogRow)
def get_amenity(amenity_id: str) -> AmenityCatalogRow | JSONResponse:
    """Single-row read -- lets the parent picker (amenity-parent-picker.tsx)
    resolve just the one label it needs for an already-set parent_id instead
    of the list endpoint's full-catalog fetch."""
    row = _fetch_row(amenity_id)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})
    return _rows_to_models([row])[0]


# ---------------------------------------------------------------------- #
# Duplicate check + draft creation
# ---------------------------------------------------------------------- #


def _parse_names(text: str) -> list[str]:
    """Split on commas/newlines -- deterministic, no LLM call for this step
    (phase-18's "Bước 1.5" is meant to be instant)."""
    parts = re.split(r"[,\n]+", text)
    seen: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen[:_MAX_TEXT_NAMES]


def _bucket_names(names: list[str], *, scope: Literal["hotel", "room"]) -> tuple[list[FlaggedName], list[FlaggedName], list[str]]:
    exact: list[FlaggedName] = []
    flagged: list[FlaggedName] = []
    clear: list[str] = []
    for name in names:
        scored = score_against_catalog(name, scope=scope, limit=1)
        if not scored:
            clear.append(name)
            continue
        entry, score = scored[0]
        match = AmenityMatch(id=entry.id, label_vi=entry.label, label_en=entry.label_en, score=round(score, 2))
        if score >= _EXACT_SCORE:
            exact.append(FlaggedName(name=name, closest=match, score=round(score, 2)))
        elif score >= _FLAGGED_SCORE:
            flagged.append(FlaggedName(name=name, closest=match, score=round(score, 2)))
        else:
            clear.append(name)
    return exact, flagged, clear


@amenity_catalog_router.post("/check-duplicate", response_model=CheckDuplicateResponse)
def check_duplicate(body: CheckDuplicateRequest) -> CheckDuplicateResponse:
    parsed = _parse_names(body.text)
    exact, flagged, clear = _bucket_names(parsed, scope=body.scope)
    return CheckDuplicateResponse(parsed=parsed, exact=exact, flagged=flagged, clear=clear)


@amenity_catalog_router.post("/draft", response_model=DraftResponse)
def draft_amenities(body: DraftRequest, admin: AdminUser = Depends(require_admin)) -> DraftResponse:
    exact, flagged, clear = _bucket_names(body.names, scope=body.scope)
    exact_by_name = {match.name: match for match in exact}
    flagged_by_name = {match.name: match for match in flagged}
    acknowledge = set(body.acknowledge)

    # Both buckets are overridable the same way -- exact (>=0.85) is a
    # stronger warning than flagged (0.55-0.85), not an unconditional block:
    # the scorer can false-positive on a single shared generic keyword (e.g.
    # "test" matching an unrelated "Covid-19 testing" entry at 86%), and an
    # admin who can see that context needs a way through, same as flagged.
    skipped_exact = [name for name in exact_by_name if name not in acknowledge]
    skipped_duplicate = [name for name in flagged_by_name if name not in acknowledge]
    to_create = clear + [name for name in exact_by_name if name in acknowledge] + [name for name in flagged_by_name if name in acknowledge]
    # Preserve the admin's original order rather than "clear-then-exact-then-flagged".
    to_create = [name for name in body.names if name in to_create]

    entries = draft_new_amenities(to_create, scope=body.scope, persist=True) if to_create else []
    # `discover_and_store_amenities` can return more than one AmenityCatalogEntry
    # for the same id -- e.g. two admin-typed names that resolve to the same
    # new entry within one batch (the DB write already deduped that to one
    # row via its own db_rows_by_id merge). Audit once per unique id, not
    # once per raw returned entry.
    unique_ids = dict.fromkeys(entry.id for entry in entries)
    entries_by_id = {entry.id: entry for entry in entries}
    for amenity_id in unique_ids:
        entry = entries_by_id[amenity_id]
        write_audit(
            admin,
            action="amenity.draft",
            entity_type="amenity",
            entity_id=entry.id,
            after={"label_vi": entry.label, "label_en": entry.label_en, "scope": entry.scope, "category": entry.category},
        )

    ids = list(unique_ids)
    rows = get_supabase_client().table(_TABLE).select(_ROW_FIELDS).in_("id", ids).execute().data if ids else []
    return DraftResponse(items=_rows_to_models(rows), skipped_exact=sorted(skipped_exact), skipped_duplicate=sorted(skipped_duplicate))


# ---------------------------------------------------------------------- #
# Edit
# ---------------------------------------------------------------------- #


def _would_create_cycle(amenity_id: str, new_parent_id: str) -> bool:
    """True if walking up `new_parent_id`'s ancestor chain reaches
    `amenity_id` (G4) -- the DB's FK/self-parent CHECK only stops a direct
    self-reference, not a multi-hop cycle."""
    current = new_parent_id
    seen: set[str] = set()
    for _ in range(_MAX_PARENT_WALK):
        if current == amenity_id:
            return True
        if current in seen:
            return True  # an unrelated cycle already exists upstream -- refuse rather than extend it
        seen.add(current)
        rows = get_supabase_client().table(_TABLE).select("parent_id").eq("id", current).limit(1).execute().data
        if not rows or not rows[0].get("parent_id"):
            return False
        current = rows[0]["parent_id"]
    return True


@amenity_catalog_router.patch("/{amenity_id}", response_model=UpdateAmenityResponse)
def update_amenity(amenity_id: str, body: UpdateAmenityRequest, admin: AdminUser = Depends(require_admin)) -> UpdateAmenityResponse | JSONResponse:
    current = _fetch_row(amenity_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})

    provided = body.model_fields_set & _MUTABLE_FIELD_SET
    changed: dict[str, Any] = {}
    for field in provided:
        new_value = getattr(body, field)
        current_value = current.get(field)
        if field == "match_keywords":
            if new_value is not None and set(new_value) != set(current_value or []):
                changed[field] = new_value
            continue
        if new_value != current_value:
            changed[field] = new_value

    if "parent_id" in changed and changed["parent_id"] is not None:
        parent_id = changed["parent_id"]
        if parent_id == amenity_id:
            return JSONResponse(status_code=422, content={"detail": "parent_id_self_reference"})
        parent_row = _fetch_row(parent_id)
        if parent_row is None:
            return JSONResponse(status_code=422, content={"detail": "parent_id_not_found"})
        if _would_create_cycle(amenity_id, parent_id):
            return JSONResponse(status_code=422, content={"detail": "parent_id_cycle"})

    if not changed:
        return UpdateAmenityResponse(id=amenity_id, changed_fields=[])

    get_supabase_client().table(_TABLE).update(changed).eq("id", amenity_id).execute()
    clear_all_approved_amenities_cache()
    write_audit(
        admin,
        action="amenity.update",
        entity_type="amenity",
        entity_id=amenity_id,
        before={field: current.get(field) for field in changed},
        after=changed,
    )
    return UpdateAmenityResponse(id=amenity_id, changed_fields=sorted(changed))


# ---------------------------------------------------------------------- #
# Approve / bulk-approve / delete
# ---------------------------------------------------------------------- #


@amenity_catalog_router.post("/{amenity_id}/approve", response_model=ApproveResponse)
def approve_amenity(amenity_id: str, admin: AdminUser = Depends(require_admin)) -> ApproveResponse | JSONResponse:
    current = _fetch_row(amenity_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})
    if not current["is_approved"]:
        get_supabase_client().table(_TABLE).update({"is_approved": True}).eq("id", amenity_id).execute()
        clear_all_approved_amenities_cache()
        write_audit(admin, action="amenity.approve", entity_type="amenity", entity_id=amenity_id, before={"is_approved": False}, after={"is_approved": True})
    return ApproveResponse(id=amenity_id, is_approved=True)


@amenity_catalog_router.post("/bulk-approve", response_model=BulkApproveResponse)
def bulk_approve_amenities(body: BulkApproveRequest, admin: AdminUser = Depends(require_admin)) -> BulkApproveResponse:
    rows = get_supabase_client().table(_TABLE).select("id,is_approved").in_("id", body.ids).execute().data or []
    pending_ids = [row["id"] for row in rows if not row["is_approved"]]
    if pending_ids:
        get_supabase_client().table(_TABLE).update({"is_approved": True}).in_("id", pending_ids).execute()
        clear_all_approved_amenities_cache()
        for amenity_id in pending_ids:
            write_audit(admin, action="amenity.approve", entity_type="amenity", entity_id=amenity_id, before={"is_approved": False}, after={"is_approved": True})
    return BulkApproveResponse(approved=len(pending_ids))


@amenity_catalog_router.delete("/{amenity_id}", status_code=204, response_model=None)
def delete_amenity(amenity_id: str, admin: AdminUser = Depends(require_admin)) -> Response | JSONResponse:
    current = _fetch_row(amenity_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})
    if current["is_approved"]:
        return JSONResponse(status_code=409, content={"detail": "amenity_approved_use_retire_instead"})

    get_supabase_client().table(_TABLE).delete().eq("id", amenity_id).execute()
    write_audit(admin, action="amenity.delete", entity_type="amenity", entity_id=amenity_id, before=current)
    return Response(status_code=204)


# ---------------------------------------------------------------------- #
# Retire / reactivate
# ---------------------------------------------------------------------- #


@amenity_catalog_router.patch("/{amenity_id}/retire", response_model=RetireResponse)
def retire_amenity(amenity_id: str, admin: AdminUser = Depends(require_admin)) -> RetireResponse | JSONResponse:
    current = _fetch_row(amenity_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})
    if not current["is_approved"]:
        return JSONResponse(status_code=409, content={"detail": "amenity_not_approved"})
    if current.get("retired_at"):
        return RetireResponse(id=amenity_id, retired_at=current["retired_at"])

    usage = _fetch_usage([amenity_id]).get(amenity_id, (0, 0))
    hotel_count, room_count = usage
    if hotel_count > 0 or room_count > 0:
        return JSONResponse(status_code=409, content={"detail": "amenity_in_use", "hotel_count": hotel_count, "room_count": room_count, "child_count": 0})

    child_count = _fetch_child_counts([amenity_id]).get(amenity_id, 0)
    if child_count > 0:
        children = (
            get_supabase_client()
            .table(_TABLE)
            .select("id,label_vi")
            .eq("parent_id", amenity_id)
            .eq("is_approved", True)
            .is_("retired_at", "null")
            .limit(5)
            .execute()
            .data
            or []
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": "amenity_has_active_children",
                "hotel_count": 0,
                "room_count": 0,
                "child_count": child_count,
                "children": children,
            },
        )

    retired_at = datetime.now(timezone.utc).isoformat()
    get_supabase_client().table(_TABLE).update({"retired_at": retired_at}).eq("id", amenity_id).execute()
    clear_all_approved_amenities_cache()
    write_audit(admin, action="amenity.retire", entity_type="amenity", entity_id=amenity_id, before={"retired_at": None}, after={"retired_at": retired_at})
    return RetireResponse(id=amenity_id, retired_at=retired_at)


@amenity_catalog_router.post("/{amenity_id}/reactivate", response_model=RetireResponse)
def reactivate_amenity(amenity_id: str, admin: AdminUser = Depends(require_admin)) -> RetireResponse | JSONResponse:
    current = _fetch_row(amenity_id)
    if current is None:
        return JSONResponse(status_code=404, content={"detail": "amenity_not_found"})
    if current.get("retired_at"):
        get_supabase_client().table(_TABLE).update({"retired_at": None}).eq("id", amenity_id).execute()
        clear_all_approved_amenities_cache()
        write_audit(admin, action="amenity.reactivate", entity_type="amenity", entity_id=amenity_id, before={"retired_at": current["retired_at"]}, after={"retired_at": None})
    return RetireResponse(id=amenity_id, retired_at=None)
