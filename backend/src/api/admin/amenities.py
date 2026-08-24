"""Admin B3 -- amenity catalog lookup for the Tiện ích tab
(phase-09-hotel-edit.md).

Reuses `services/amenity_catalog.py`'s `query_approved_amenities` -- the same
approved catalog the public `/hotel-amenities` endpoint reads (routes.py:166)
-- filtered to `scope in ('hotel', 'both')`. That public endpoint does NOT
filter by scope (it serves generic client-side labels for both hotel and
room amenities), so it is not reused as-is here: doing so would let the 2
room-only catalog entries appear as hotel amenity options.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.services.amenity_catalog import query_approved_amenities

amenities_router = APIRouter(prefix="/amenities", tags=["admin-amenities"])

_HOTEL_ELIGIBLE_SCOPES = frozenset({"hotel", "both"})


class AmenityOption(BaseModel):
    id: str
    label_vi: str
    label_en: str
    category: str


@amenities_router.get("", response_model=list[AmenityOption])
def list_amenities(scope: Literal["hotel"] = Query(default="hotel")) -> list[AmenityOption]:
    del scope  # only value supported today -- no room-scope admin UI exists yet
    return [
        AmenityOption(id=entry.id, label_vi=entry.label, label_en=entry.label_en, category=entry.category)
        for entry in query_approved_amenities()
        if entry.scope in _HOTEL_ELIGIBLE_SCOPES
    ]
