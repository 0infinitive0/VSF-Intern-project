"""Admin B2 -- destination lookup for the hotel create/edit `Thành phố / Tỉnh`
select (phase-08-hotel-create.md, L26). `destinations` is a small, mostly
static reference table (a handful of rows) so this returns the whole thing
sorted by name, no pagination."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.clients.supabase_client import get_supabase_client

destinations_router = APIRouter(prefix="/destinations", tags=["admin-destinations"])


class DestinationOption(BaseModel):
    id: str
    name: str


def _row_to_destination(row: dict[str, Any]) -> DestinationOption:
    return DestinationOption(id=row["id"], name=row["name"])


def _fetch_destinations() -> list[dict[str, Any]]:
    return get_supabase_client().table("destinations").select("id,name").order("name").execute().data or []


@destinations_router.get("", response_model=list[DestinationOption])
def list_destinations() -> list[DestinationOption]:
    return [_row_to_destination(row) for row in _fetch_destinations()]
