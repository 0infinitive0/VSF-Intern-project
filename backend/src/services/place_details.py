"""Read-only detail lookups for hotel and attraction focus views."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from typing import Any

from supabase import Client, create_client

from src.config import get_settings

logger = logging.getLogger(__name__)

_HOTEL_FIELDS = (
    "id,name,star_rating,description,address,city,area_name,location_highlight,coordinates,"
    "image_url,images,amenities,amenity_groups,awards,warnings,review_score,review_count,"
    "category_scores,check_in_time,check_in_until,check_out_time,reception_open_until,"
    "nearby_attractions,nearby_essentials,lowest_price,currency,source_platform,source_url"
)
_ROOM_FIELDS = (
    "id,name,bed_description,room_size_sqm,max_guests,view,room_facilities,images,"
    "available_room_count"
)
_PRICE_FIELDS = "room_id,price,currency,check_in_date,check_out_date,sold_out,crawled_at"
_ATTRACTION_FIELDS = (
    "id,name,description,category,is_tour,estimated_duration_minutes,opening_time,closing_time,"
    "ticket_price_adult,ticket_price_child,rating,review_count,coordinates,images"
)
_AGODA_NEARBY_DISTANCE = re.compile(
    r"^(?P<name>.+?)\s*[-–—]\s*(?P<distance_text>.*?(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>km|m))\s*$",
    re.IGNORECASE,
)


def _get_supabase_client() -> Client:
    settings = get_settings()
    url = getattr(settings, "supabase_url", None) or os.environ.get("SUPABASE_URL")
    key = getattr(settings, "supabase_service_key", None) or os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or settings.")
    return create_client(url, key)


def _price_payload(price: dict[str, Any]) -> dict[str, Any]:
    return {
        "amount": price.get("price"),
        "currency": price.get("currency"),
        "check_in_date": price.get("check_in_date"),
        "check_out_date": price.get("check_out_date"),
        "sold_out": price.get("sold_out"),
        # The current schema has no package-detail column; preserve null.
        "package_details": None,
    }


def _choose_price(
    prices: list[dict[str, Any]], check_in: date | None, check_out: date | None
) -> dict[str, Any] | None:
    """Return one applicable price, never falling back to hotel-level pricing."""
    if check_in is not None and check_out is not None:
        check_in_value, check_out_value = check_in.isoformat(), check_out.isoformat()
        matches = [
            row for row in prices
            if row.get("check_in_date") == check_in_value
            and row.get("check_out_date") == check_out_value
            and not row.get("sold_out", False)
        ]
    else:
        matches = [row for row in prices if not row.get("sold_out", False)]
    return max(matches, key=lambda row: str(row.get("crawled_at") or "")) if matches else None


def _room_availability(
    client: Client,
    room_id: str,
    check_in: date,
    check_out: date,
) -> int:
    """Return booking-aware inventory for one room type and stay interval."""
    result = client.rpc(
        "get_room_availability",
        {
            "p_room_id": room_id,
            "p_check_in_date": check_in.isoformat(),
            "p_check_out_date": check_out.isoformat(),
        },
    ).execute().data
    return max(int(result or 0), 0)


def _normalize_agoda_nearby_attractions(value: Any) -> Any:
    """Turn Agoda's text-only nearby entries into the public detail shape.

    Agoda supplies a place name plus a preformatted distance, but no reliable
    attraction coordinates.  Keep that factual data and explicitly expose a
    null coordinate so clients can render the distance list without creating a
    false map ray.
    """
    if not isinstance(value, list):
        return value

    normalized: list[Any] = []
    for entry in value:
        if not isinstance(entry, str):
            normalized.append(entry)
            continue
        text = entry.strip()
        match = _AGODA_NEARBY_DISTANCE.match(text)
        if match is None:
            normalized.append({"name": text, "coordinates": None})
            continue
        distance = float(match["value"].replace(",", "."))
        if match["unit"].casefold() == "m":
            distance /= 1000
        normalized.append(
            {
                "name": match["name"].strip(),
                "distance_km": distance,
                "distance_text": match["distance_text"].strip(),
                "coordinates": None,
            }
        )
    return normalized


def get_hotel_detail(
    hotel_id: str, check_in: date | None = None, check_out: date | None = None
) -> dict[str, Any] | None:
    """Fetch a hotel, rooms, prices, and booking-aware inventory.

    Inventory applies to the requested stay.  Without a requested stay it is
    calculated for today through tomorrow, which makes the detail response's
    ``available_room_count`` a current value rather than static capacity.
    """
    try:
        client = _get_supabase_client()
        hotel_rows = (
            client.table("hotels").select(_HOTEL_FIELDS).eq("id", hotel_id).limit(1).execute().data or []
        )
        if not hotel_rows:
            return None
        hotel = dict(hotel_rows[0])
        if str(hotel.get("source_platform") or "").casefold() == "agoda":
            hotel["nearby_attractions"] = _normalize_agoda_nearby_attractions(
                hotel.get("nearby_attractions")
            )
        rooms = client.table("rooms").select(_ROOM_FIELDS).eq("hotel_id", hotel_id).execute().data or []
        room_ids = [str(room["id"]) for room in rooms if room.get("id")]
        prices: list[dict[str, Any]] = []
        if room_ids:
            query = client.table("room_prices").select(_PRICE_FIELDS).in_("room_id", room_ids)
            if check_in is not None and check_out is not None:
                query = query.eq("check_in_date", check_in.isoformat()).eq("check_out_date", check_out.isoformat())
            else:
                query = query.eq("sold_out", False)
            prices = query.execute().data or []
        availability_check_in = check_in or date.today()
        availability_check_out = check_out or availability_check_in + timedelta(days=1)
        availability_by_room = {
            room_id: _room_availability(
                client, room_id, availability_check_in, availability_check_out
            )
            for room_id in room_ids
        }
    except Exception:
        logger.exception("Failed to fetch hotel detail for %s", hotel_id)
        raise

    prices_by_room: dict[str, list[dict[str, Any]]] = {}
    for price in prices:
        if price.get("room_id"):
            prices_by_room.setdefault(str(price["room_id"]), []).append(price)
    hotel["rooms"] = []
    hotel["available_room_count"] = 0
    for room in rooms:
        room_detail = dict(room)
        selected = _choose_price(prices_by_room.get(str(room.get("id")), []), check_in, check_out)
        room_detail["price"] = _price_payload(selected) if selected else None
        room_detail["available_room_count"] = availability_by_room.get(str(room.get("id")), 0)
        hotel["available_room_count"] += room_detail["available_room_count"]
        hotel["rooms"].append(room_detail)
    return hotel


def get_attraction_detail(attraction_id: str) -> dict[str, Any] | None:
    """Fetch a single attraction without interacting with chat-session state."""
    try:
        rows = (
            _get_supabase_client().table("attractions").select(_ATTRACTION_FIELDS)
            .eq("id", attraction_id).limit(1).execute().data or []
        )
    except Exception:
        logger.exception("Failed to fetch attraction detail for %s", attraction_id)
        raise
    return dict(rows[0]) if rows else None
