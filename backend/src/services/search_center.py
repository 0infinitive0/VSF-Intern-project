"""Deterministic center resolution for hotel radius search (doc §20, §21).

A radius search ("Tìm khách sạn trong bán kính 3km") needs a center point
before it can filter by distance. Resolution order, per the phase-08 plan's
locked decision:

  1. The user's already-selected hotel, when known. Not yet reachable from
     `graph_v2` today -- no hotel-selection concept exists in
     `TravelGraphState`/`TravelState` yet (that lands whenever a later phase
     adds one). `selected_hotel_coordinates` stays a real parameter so this
     function is already correct for that day; `hotel_node` just always
     passes `None` for it right now.
  2. An explicitly named POI/landmark, geocoded against the `attractions`
     table, falling back to the `hotels` table when no attraction matches --
     never guessed by the model. Doc §20: "Do not let GPT calculate
     geographic distance." `extract_named_place` only pulls the candidate
     NAME out of the message via a plain regex; the coordinates always come
     from a real row in `attractions` or `hotels`, or resolution fails.
  3. Neither: unresolved. `hotel_node` is the one that calls `interrupt()`
     on this outcome -- this module stays a plain, DB-touching services
     function so it stays trivially testable without a graph runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from src.services.supabase_search import get_supabase_client
from src.services.trip_scheduler import parse_coordinates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CenterResolution:
    latitude: float | None
    longitude: float | None
    source: str  # "selected_hotel" | "poi" | "hotel" | "unresolved"
    poi_name: str | None = None

    @property
    def resolved(self) -> bool:
        return self.latitude is not None and self.longitude is not None


# Prepositions that plausibly introduce a landmark name in a Vietnamese
# radius request ("... từ Bà Nà Hills", "cách Bà Nà Hills 3km", "quanh chợ
# Bến Thành"). Deliberately narrow -- a false negative just falls through to
# `hotel_node`'s interrupt ask, which is the safe direction; a false
# positive would hand a wrong string to the DB lookup, which fails closed
# (no match -> unresolved) rather than fabricating a center.
_CENTER_PREPOSITION_RE = re.compile(r"(?:\btừ\b|\bgần\b|\bquanh\b|\bcách\b)\s+(?P<place>.+)$", re.IGNORECASE)

# Strips a trailing radius clause ("... 3km", "... 3 km") that lands inside
# the captured group when the preposition precedes the place but the radius
# number follows it ("cách Bà Nà Hills 3km", as opposed to "trong bán kính
# 3km từ Bà Nà Hills", where the radius clause precedes "từ" and never
# enters the capture at all).
_TRAILING_RADIUS_RE = re.compile(r"\s*,?\s*(?:trong\s+)?(?:bán\s*kính\s+)?\d+(?:[.,]\d+)?\s*km\b.*$", re.IGNORECASE)


def extract_named_place(message: str) -> str | None:
    """Best-effort extraction of a landmark name following a Vietnamese
    locative preposition. Returns None when no preposition is found --
    never a guess, since the caller treats None as "no POI named"."""
    match = _CENTER_PREPOSITION_RE.search(message)
    if not match:
        return None
    place = _TRAILING_RADIUS_RE.sub("", match.group("place")).strip(" .,")
    return place or None


def find_attraction_by_name(name: str, destination_id: str) -> tuple[float, float] | None:
    """Case-insensitive substring match against `attractions.name` (DB-side
    `ilike`, same convention as `supabase_search._get_destination_id_by_name`
    -- diacritics must still match), scoped to the trip's destination.
    Returns the first match's coordinates, or None when nothing matches or
    the lookup fails -- never guesses."""
    stripped = name.strip()
    if not stripped or not destination_id:
        return None
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("attractions")
            .select("id,name,coordinates")
            .eq("destination_id", destination_id)
            .ilike("name", f"%{stripped}%")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to look up attraction %r for center resolution: %s", name, exc)
        return None
    rows = response.data or []
    if not rows:
        return None
    return parse_coordinates(rows[0].get("coordinates"))


def find_hotel_by_name(name: str, destination_id: str) -> tuple[float, float] | None:
    """Same case-insensitive substring match as `find_attraction_by_name`,
    against `hotels.name` instead. Lets a named hotel (e.g. "gần Khách sạn
    X") serve as a search center even though hotels aren't attractions --
    never guesses; no match or a failed lookup returns None."""
    stripped = name.strip()
    if not stripped or not destination_id:
        return None
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table("hotels")
            .select("id,name,coordinates")
            .eq("destination_id", destination_id)
            .ilike("name", f"%{stripped}%")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to look up hotel %r for center resolution: %s", name, exc)
        return None
    rows = response.data or []
    if not rows:
        return None
    return parse_coordinates(rows[0].get("coordinates"))


def resolve_center(
    *,
    destination_id: str,
    named_place: str | None = None,
    selected_hotel_coordinates: tuple[float, float] | None = None,
) -> CenterResolution:
    """Resolve a radius search's center, deterministically, in priority
    order. Never falls back to a destination-wide or otherwise guessed
    center -- an unresolved outcome is the caller's cue to ask, not to pick
    something plausible."""
    if selected_hotel_coordinates is not None:
        latitude, longitude = selected_hotel_coordinates
        return CenterResolution(latitude=latitude, longitude=longitude, source="selected_hotel")

    if named_place:
        coordinates = find_attraction_by_name(named_place, destination_id)
        if coordinates is not None:
            latitude, longitude = coordinates
            return CenterResolution(latitude=latitude, longitude=longitude, source="poi", poi_name=named_place)

        coordinates = find_hotel_by_name(named_place, destination_id)
        if coordinates is not None:
            latitude, longitude = coordinates
            return CenterResolution(latitude=latitude, longitude=longitude, source="hotel", poi_name=named_place)

    return CenterResolution(latitude=None, longitude=None, source="unresolved", poi_name=named_place)
