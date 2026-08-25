"""Read-only detail lookups for hotel and attraction focus views."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from supabase import Client, create_client

from src.config import get_settings
from src.services.amenity_catalog import query_all_approved_amenities_by_ids

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


def _average_price(
    prices: list[dict[str, Any]], check_in: date | None, check_out: date | None
) -> dict[str, Any] | None:
    """Average this room's per-night price snapshots across the requested stay.

    `room_prices` holds one row per crawled NIGHT (each row's `check_in_date`
    is that night; see hotel_pipeline.py's `normalize_room`, which stores the
    crawler's own `price_per_night`) — never one row spanning a whole
    multi-night stay. So a 3-night stay's room price is the average of each
    of those 3 nights' own snapshots, not a single row lookup. Restricted to
    `[check_in, check_out)` when a stay is given; averages every known night
    otherwise (a representative nightly rate for the detail view with no
    stay picked yet).

    A night re-crawled more than once keeps only its freshest (max
    `crawled_at`) snapshot -- picked BEFORE checking `sold_out`, not after:
    an admin closing a night writes a new row with `sold_out=True`, and that
    row must win the freshest-snapshot comparison against an older OTA row
    for the same night even though the OTA row is `sold_out=False` -- the
    same class of bug `count_priced_open_nights()`
    (20260824_fix_sold_out_freshest_row_precedence.sql) fixes on the search
    side. A night whose freshest snapshot IS sold_out is simply absent from
    the average — never fabricated (same "no invented data" stance as the
    rest of this module). Returns None when nothing in range has a usable
    price at all — the caller shows "price on request", never falls back to
    hotel-level pricing.

    The average is computed in `Decimal` and rounded to a whole VND (VND has
    no real subunit) rather than left as a raw float division — VNPay's own
    gateway settles/reports transactions in whole VND, so a fractional-đồng
    total here would silently propagate into `booking.total_amount` and
    `payments.amount`, then mismatch the whole-VND `vnp_Amount` VNPay's IPN
    reports back, permanently failing `vnpay_ipn`'s amount check
    (`RspCode 04`) for a real, successful payment -- exactly how an earlier
    version of this function (plain `float` division, no rounding) broke
    checkout right after per-night averaging shipped.
    """
    candidates = [row for row in prices if row.get("check_in_date")]
    if check_in is not None and check_out is not None:
        check_in_value, check_out_value = check_in.isoformat(), check_out.isoformat()
        candidates = [
            row for row in candidates if check_in_value <= row["check_in_date"] < check_out_value
        ]

    freshest_by_night: dict[str, dict[str, Any]] = {}
    for row in candidates:
        night = row["check_in_date"]
        current = freshest_by_night.get(night)
        if current is None or str(row.get("crawled_at") or "") > str(current.get("crawled_at") or ""):
            freshest_by_night[night] = row

    # sold_out is checked on the freshest row per night, not on every raw
    # row before picking the freshest -- see the docstring above.
    priced_nights = [
        row for row in freshest_by_night.values() if row.get("price") is not None and not row.get("sold_out", False)
    ]
    if not priced_nights:
        return None

    average_total = sum(Decimal(str(row["price"])) for row in priced_nights)
    average_amount = float(
        (average_total / len(priced_nights)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    latest = max(priced_nights, key=lambda row: str(row.get("crawled_at") or ""))
    return {
        "amount": average_amount,
        "currency": latest.get("currency"),
        "check_in_date": check_in.isoformat() if check_in else min(freshest_by_night),
        "check_out_date": check_out.isoformat() if check_out else None,
        "sold_out": False,
        # The current schema has no package-detail column; preserve null.
        "package_details": None,
    }


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


def _room_amenities_from_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join each returned room facility ID to its approved catalog row once."""
    amenity_ids = list(dict.fromkeys(
        facility
        for room in rooms
        for facility in room.get("room_facilities") or []
        if isinstance(facility, str)
    ))
    if not amenity_ids:
        return []
    by_id = {
        entry.id: {
            "id": entry.id,
            "label_vi": entry.label,
            "label_en": entry.label_en,
            "category": entry.category,
            "icon_key": entry.icon_key,
        }
        for entry in query_all_approved_amenities_by_ids(amenity_ids)
        if entry.scope in {"room", "both"}
    }
    return [by_id[amenity_id] for amenity_id in amenity_ids if amenity_id in by_id]


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
            # One row per crawled night (see _average_price's docstring) --
            # a requested stay is a NIGHT RANGE, not a single exact
            # check_in/check_out row, so this fetches every night in
            # [check_in, check_out) for averaging rather than looking for
            # one row spanning the whole stay.
            #
            # Deliberately NOT `.eq("sold_out", False)` here -- that would
            # drop a sold_out=True row before _average_price ever sees it,
            # defeating its freshest-row-decides-sold_out logic for exactly
            # the case that logic exists for (a newer sold_out row must be
            # able to beat an older, still-available one for the same
            # night). _average_price does its own sold_out filtering, on
            # the freshest row per night, after this fetch.
            query = client.table("room_prices").select(_PRICE_FIELDS).in_("room_id", room_ids)
            if check_in is not None and check_out is not None:
                query = query.gte("check_in_date", check_in.isoformat()).lt(
                    "check_in_date", check_out.isoformat()
                )
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
        room_detail["price"] = _average_price(prices_by_room.get(str(room.get("id")), []), check_in, check_out)
        room_detail["available_room_count"] = availability_by_room.get(str(room.get("id")), 0)
        hotel["available_room_count"] += room_detail["available_room_count"]
        hotel["rooms"].append(room_detail)
    hotel["room_amenities"] = _room_amenities_from_rooms(hotel["rooms"])
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
