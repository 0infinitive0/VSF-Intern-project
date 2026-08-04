"""Hotel OTA data pipeline: Extract -> Validate -> Normalize -> Dedupe -> Load -> QualityCheck.

Loads the Agoda/Booking hotel JSON dumps (`data/agoda.json`, `data/booking.json`)
into the flat, per-OTA-listing `hotels`/`rooms`/`room_prices` tables (one row per
`(source_platform, source_hotel_id)` — a physical hotel listed on both Agoda and
Booking stays as two separate rows, since price/policy differ per OTA and the
chatbot needs to compare them; see scripts/database_schema.sql).

Cross-OTA physical-hotel grouping (same physical hotel found on both Agoda and
Booking) never merges `hotels` DB rows — both listings are always kept. It is
computed as a separate `canonical_hotel_key`/`review_status` for AI/RAG
presentation only; see `group_physical_hotels()` and
plans/260724-0925-hotel-normalize-dedupe-for-vector-rag/phase-03-dedupe-canonical-identity.md.
"""

import json
import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import Json

from osm_pipeline import get_or_create_destination

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference data (source-specific text -> canonical value)
# ---------------------------------------------------------------------------

COUNTRY_MAP = {
    "việt nam": "VN",
    "vietnam": "VN",
    "vn": "VN",
}

CITY_ALIASES = {
    "hồ chí minh": "Hồ Chí Minh",
    "tp. hồ chí minh": "Hồ Chí Minh",
    "tp hồ chí minh": "Hồ Chí Minh",
    "thành phố hồ chí minh": "Hồ Chí Minh",
    "ho chi minh": "Hồ Chí Minh",
    "hcmc": "Hồ Chí Minh",
}

AGODA_ACCOMMODATION_TYPE_MAP = {
    "khách sạn": "hotel",
    "căn hộ dịch vụ": "apartment",
    "nhà nghỉ": "guest_house",
    "căn hộ": "apartment",
    "khách sạn con nhộng": "capsule_hotel",
    "nhà khách / nhà nghỉ b&b": "bed_and_breakfast",
}

BOOKING_ACCOMMODATION_TYPE_MAP = {
    "hotel": "hotel",
    "apartment": "apartment",
    "aparthotel": "aparthotel",
    "hostel": "hostel",
    "guest_house": "guest_house",
    "bed_and_breakfast": "bed_and_breakfast",
    "capsule_hotel": "capsule_hotel",
    "homestay": "homestay",
}


def normalize_country(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().casefold()
    return COUNTRY_MAP.get(key, raw.strip().upper() if len(raw.strip()) <= 3 else raw.strip())


def normalize_city(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().casefold()
    return CITY_ALIASES.get(key, raw.strip())


def normalize_accommodation_type(raw: Optional[str], source_platform: str) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().casefold()
    if source_platform == "agoda":
        return AGODA_ACCOMMODATION_TYPE_MAP.get(key, raw.strip())
    if source_platform == "booking":
        return BOOKING_ACCOMMODATION_TYPE_MAP.get(key, raw.strip())
    return raw.strip()


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def _nfc_deep(value: Any) -> Any:
    """Normalize every string to Unicode NFC.

    Agoda ships NFC, Booking ships NFD for at least `city` (precomposed vs.
    base letter + combining accent). Left alone, casefold-equal strings
    compare unequal downstream (city/country alias matching, dedupe keys).
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc_deep(v) for v in value]
    if isinstance(value, dict):
        return {
            (unicodedata.normalize("NFC", k) if isinstance(k, str) else k): _nfc_deep(v)
            for k, v in value.items()
        }
    return value


# Canonical source_platform vocabulary. Every writer of this field (this
# module, sync_hotels_rest.py) must emit one of these exact values — a second
# vocabulary (e.g. "booking.com") mints a different point_id for the same
# hotel and duplicates it instead of overwriting it.
CANONICAL_SOURCE_PLATFORMS = frozenset({"agoda", "booking"})


def extract_source(path: str, source_platform: str) -> List[Dict[str, Any]]:
    if source_platform not in CANONICAL_SOURCE_PLATFORMS:
        raise ValueError(f"Unknown source_platform: {source_platform!r}")
    with Path(path).open(encoding="utf-8") as f:
        records = json.load(f)
    records = [_nfc_deep(record) for record in records]
    for record in records:
        record["source_platform"] = source_platform
    logger.info("extract: %s -> %d records from %s", source_platform, len(records), path)
    return records


def extract_hotels(agoda_path: str, booking_path: str) -> List[Dict[str, Any]]:
    return extract_source(agoda_path, "agoda") + extract_source(booking_path, "booking")


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------

@dataclass
class ValidationStats:
    total: int = 0
    valid: int = 0
    rejected: int = 0
    rejected_samples: List[str] = field(default_factory=list)


def _is_valid_raw_hotel(record: Dict[str, Any]) -> Optional[str]:
    """Return an error message if invalid, None if valid.

    Must catch every condition that would otherwise violate a DB constraint
    at load time (hotels.star_rating CHECK, rooms.name NOT NULL) — the whole
    batch loads in one transaction, so a constraint violation here aborts
    every hotel in the run, not just the offending record.
    """
    hotel_id = record.get("hotel_id")
    if hotel_id is None or not isinstance(hotel_id, int):
        return f"hotel_id missing or not an int (got {hotel_id!r})"
    if not record.get("hotel_name"):
        return "hotel_name missing or empty"
    star_rating = record.get("star_rating")
    if star_rating is not None and not (0 <= star_rating <= 5):
        return f"star_rating out of range (got {star_rating!r})"
    for room in record.get("rooms") or []:
        if room.get("room_id") is None or not isinstance(room.get("room_id"), int):
            return f"room_id missing or not an int (got {room.get('room_id')!r})"
        if not room.get("name"):
            return f"room {room.get('room_id')}: name missing or empty"
    return None


def validate_hotels(raw_records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], ValidationStats]:
    stats = ValidationStats(total=len(raw_records))
    validated: List[Dict[str, Any]] = []

    for record in raw_records:
        error = _is_valid_raw_hotel(record)
        if error is None:
            validated.append(record)
            stats.valid += 1
        else:
            stats.rejected += 1
            msg = f"{record.get('source_platform', '?')}:{record.get('hotel_id', '?')} -> {error}"
            stats.rejected_samples.append(msg)
            logger.warning("validate: rejected record %s", msg)

    logger.info("validate: %d/%d records passed (%d rejected)", stats.valid, stats.total, stats.rejected)
    return validated, stats


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

_SIZE_RE = re.compile(r"([\d.]+)\s*m")
_AGODA_ADULTS_RE = re.compile(r"(\d+)")


def parse_room_size_sqm(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    match = _SIZE_RE.search(raw)
    return float(match.group(1)) if match else None


def parse_max_guests(raw: Optional[str], source_platform: str) -> Optional[int]:
    """Agoda text counts adults only; Booking is a plain total-guests number.
    Both land in the same `max_guests` column but are NOT comparable across
    sources (see docs/data_dictionary.md 1.3)."""
    if not raw:
        return None
    if source_platform == "agoda":
        match = _AGODA_ADULTS_RE.search(raw)
        return int(match.group(1)) if match else None
    if raw.strip().isdigit():
        return int(raw.strip())
    return None


def flatten_amenity_groups(groups: Optional[Dict[str, List[str]]]) -> List[str]:
    if not groups:
        return []
    flat: List[str] = []
    seen: set = set()
    for items in groups.values():
        for item in items or []:
            if item not in seen:
                seen.add(item)
                flat.append(item)
    return flat


def parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        logger.warning("normalize: could not parse date %r", raw)
        return None


def parse_datetime(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("normalize: could not parse datetime %r", raw)
        return None


def normalize_room(
    raw_room: Dict[str, Any],
    source_platform: str,
    hotel_currency: Optional[str],
    hotel_price_check_in: Optional[date],
    hotel_price_check_out: Optional[date],
    hotel_source_url: Optional[str],
    hotel_scraped_at: Optional[datetime],
) -> Dict[str, Any]:
    if source_platform == "agoda":
        room_facilities = flatten_amenity_groups(raw_room.get("amenity_groups"))
        amenity_groups = raw_room.get("amenity_groups")
    else:
        room_facilities = raw_room.get("amenities") or []
        amenity_groups = None

    price = {
        "price": raw_room.get("price_per_night"),
        "currency": raw_room.get("currency") or hotel_currency,
        "check_in_date": hotel_price_check_in,
        "check_out_date": hotel_price_check_out,
        "sold_out": bool(raw_room.get("sold_out", False)),
        "crossed_out": bool(raw_room.get("crossed_out", False)),
        "review_score": raw_room.get("review_score"),
        "review_text": raw_room.get("review_text"),
        "source_url": hotel_source_url,
        "crawled_at": hotel_scraped_at,
    }

    return {
        "source_room_id": raw_room["room_id"],
        "name": raw_room.get("name"),
        "bed_description": raw_room.get("bed"),
        "room_size_sqm": parse_room_size_sqm(raw_room.get("size")),
        "max_occupancy_raw": raw_room.get("max_occupancy"),
        "max_guests": parse_max_guests(raw_room.get("max_occupancy"), source_platform),
        "view": raw_room.get("view"),
        "room_facilities": room_facilities,
        "amenity_groups": amenity_groups,
        "images": raw_room.get("images") or [],
        "image_count": raw_room.get("image_count"),
        "prices": [price],
    }


# ---------------------------------------------------------------------------
# Canonical / retrieval helpers (Phase 2: field normalize contract)
#
# These build the "canonical" (stable filter values) and "retrieval"
# (embedding text, Qdrant payload, grounding facts) layers described in
# plans/260724-0925-hotel-normalize-dedupe-for-vector-rag. They are additive:
# _HOTEL_COLUMNS does not include "canonical"/"retrieval", so DB upsert is
# unaffected by these keys (see _jsonb_fields filtering by column allowlist).
# ---------------------------------------------------------------------------

_NAME_KEY_STOPWORDS = {"hotel", "resort", "apartment", "khach", "san", "the", "a", "an", "and"}
_NAME_KEY_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")
_COORDINATES_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")

# VND-only for now: current corpus is VND-priced. Other currencies get no tier
# rather than a misleading one built on the wrong scale.
_PRICE_TIER_THRESHOLDS_VND = (800_000, 2_500_000)  # (budget_max, mid_range_max); above mid_range_max is luxury

_DESCRIPTION_MAX_CHARS = 500
_EMBEDDING_TOP_AMENITIES = 10
_EMBEDDING_TOP_HIGHLIGHTS = 5
_EMBEDDING_TOP_NEARBY = 5


def normalize_name_key(name: Optional[str]) -> Optional[str]:
    """Ascii-folded, stopword-stripped blocking key for cross-OTA name matching
    (Phase 3 uses this to find candidate physical-hotel duplicates)."""
    if not name:
        return None
    folded = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    ascii_only = _NAME_KEY_PUNCT_RE.sub(" ", ascii_only.casefold())
    tokens = [t for t in ascii_only.split() if t and t not in _NAME_KEY_STOPWORDS]
    return " ".join(tokens) if tokens else None


def parse_coordinates(raw: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Parse the raw `"lat,lon"` string into numeric (lat, lon).
    Rejects malformed or out-of-range values rather than guessing."""
    if not raw:
        return None, None
    match = _COORDINATES_RE.match(raw)
    if not match:
        logger.warning("normalize: could not parse coordinates %r", raw)
        return None, None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.warning("normalize: coordinates out of range %r", raw)
        return None, None
    return lat, lon


def normalize_text_list(items: Optional[List[str]]) -> List[str]:
    """Trim, drop empties, dedupe while preserving first-seen order."""
    if not items:
        return []
    seen: set = set()
    result: List[str] = []
    for item in items:
        if not item:
            continue
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def normalize_url_list(urls: Optional[List[str]], cap: Optional[int] = None) -> List[str]:
    """Dedupe, keep only http(s) URLs, optionally cap the result count."""
    if not urls:
        return []
    seen: set = set()
    result: List[str] = []
    for url in urls:
        if not url:
            continue
        text = url.strip()
        if text.startswith(("http://", "https://")) and text not in seen:
            seen.add(text)
            result.append(text)
        if cap is not None and len(result) >= cap:
            break
    return result


def compute_price_tier(price: Optional[float], currency: Optional[str]) -> Optional[str]:
    """Coarse price band for Qdrant filtering. Returns None for missing price
    or non-VND currency rather than mixing incompatible scales."""
    if price is None or currency != "VND":
        return None
    low, high = _PRICE_TIER_THRESHOLDS_VND
    if price < low:
        return "budget"
    if price <= high:
        return "mid_range"
    return "luxury"


def compute_amenity_keys(amenities: List[str], cap: int = 20) -> List[str]:
    """Ascii-folded, lowercase, underscore-joined filter tokens for Qdrant
    payload filtering (e.g. "Hồ bơi" -> "ho_boi")."""
    seen: set = set()
    keys: List[str] = []
    for amenity in amenities:
        folded = unicodedata.normalize("NFKD", amenity)
        ascii_only = "".join(c for c in folded if not unicodedata.combining(c)).strip().casefold()
        key = _WHITESPACE_RE.sub("_", ascii_only)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
        if len(keys) >= cap:
            break
    return keys


def _clean_description(raw: Optional[str]) -> str:
    if not raw:
        return ""
    text = _WHITESPACE_RE.sub(" ", raw).strip()
    return text[:_DESCRIPTION_MAX_CHARS]


def _select_nearby_names(nearby: Any) -> List[str]:
    """Agoda ships `list[str]`; Booking ships `list[object]` with a "name" key."""
    if not nearby:
        return []
    names: List[str] = []
    for item in nearby:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(item["name"])
    return normalize_text_list(names)[:_EMBEDDING_TOP_NEARBY]


def build_hotel_embedding_text(hotel: Dict[str, Any]) -> str:
    """Deterministic embedding input built only from stable, user-facing fields.
    Excludes volatile data: exact price, source URL, scraped timestamp, room
    IDs, and large raw JSON — those live in `payload`/`grounding_facts` instead."""
    lines = [f"Hotel: {hotel['name']}"]

    destination = ", ".join(p for p in (hotel.get("destination_name"), hotel.get("area_name")) if p)
    if destination:
        lines.append(f"Destination: {destination}")

    type_stars = "; ".join(
        p
        for p in (
            f"Type: {hotel['accommodation_type']}" if hotel.get("accommodation_type") else "",
            f"Stars: {hotel['star_rating']}" if hotel.get("star_rating") is not None else "",
        )
        if p
    )
    if type_stars:
        lines.append(type_stars)

    description = _clean_description(hotel.get("description"))
    if description:
        lines.append(f"Description: {description}")

    amenities = normalize_text_list(hotel.get("amenities"))[:_EMBEDDING_TOP_AMENITIES]
    if amenities:
        lines.append(f"Amenities: {', '.join(amenities)}")

    highlights = normalize_text_list(hotel.get("highlights"))[:_EMBEDDING_TOP_HIGHLIGHTS]
    if highlights:
        lines.append(f"Highlights: {', '.join(highlights)}")

    nearby = _select_nearby_names(hotel.get("nearby_attractions"))
    if nearby:
        lines.append(f"Nearby: {', '.join(nearby)}")

    return "\n".join(lines)


def build_hotel_payload(hotel: Dict[str, Any]) -> Dict[str, Any]:
    """Small, stable Qdrant filter payload — ids, destination, star, price
    tier/min price, amenity keys, lat/lon, source metadata. No large/raw JSON
    (amenity_groups, category_scores, nearby_*)."""
    canonical = hotel["canonical"]
    return {
        "source_platform": hotel["source_platform"],
        "source_hotel_id": hotel["source_hotel_id"],
        "name": hotel["name"],
        "destination_name": hotel.get("destination_name"),
        "area_name": hotel.get("area_name"),
        "country": hotel.get("country"),
        "star_rating": hotel.get("star_rating"),
        "accommodation_type": hotel.get("accommodation_type"),
        "min_price": hotel.get("lowest_price"),
        "currency": hotel.get("currency"),
        "price_tier": canonical["price_tier"],
        "amenity_keys": canonical["amenity_keys"],
        "lat": canonical["lat"],
        "lon": canonical["lon"],
    }


def build_grounding_facts(hotel: Dict[str, Any]) -> Dict[str, Any]:
    """Exact source facts an AI answer may cite: source listing, price, room
    context (see `hotel["rooms"]`), and crawl timestamp."""
    return {
        "source_platform": hotel["source_platform"],
        "source_hotel_id": hotel["source_hotel_id"],
        "source_url": hotel.get("source_url"),
        "name": hotel["name"],
        "address": hotel.get("address"),
        "lowest_price": hotel.get("lowest_price"),
        "currency": hotel.get("currency"),
        "price_check_in_date": hotel.get("price_check_in_date"),
        "price_check_out_date": hotel.get("price_check_out_date"),
        "star_rating": hotel.get("star_rating"),
        "review_score": hotel.get("review_score"),
        "review_count": hotel.get("review_count"),
        "warnings": hotel.get("warnings") or [],
        "scraped_at": hotel.get("scraped_at"),
    }


def normalize_hotel(raw: Dict[str, Any]) -> Dict[str, Any]:
    source_platform = raw["source_platform"]
    scraped_at = parse_datetime(raw.get("scraped_at"))
    price_check_in = parse_date(raw.get("check_in"))
    price_check_out = parse_date(raw.get("check_out"))
    source_url = raw.get("property_url")

    rooms = [
        normalize_room(
            room,
            source_platform,
            hotel_currency=raw.get("currency"),
            hotel_price_check_in=price_check_in,
            hotel_price_check_out=price_check_out,
            hotel_source_url=source_url,
            hotel_scraped_at=scraped_at,
        )
        for room in (raw.get("rooms") or [])
    ]

    hotel = {
        "source_platform": source_platform,
        "source_hotel_id": raw["hotel_id"],
        "source_url": source_url,
        "name": raw["hotel_name"],
        "accommodation_type": normalize_accommodation_type(raw.get("accommodation_type"), source_platform),
        "description": raw.get("description"),
        "star_rating": raw.get("star_rating"),
        "address": raw.get("address"),
        "city": raw.get("city"),
        "area_name": raw.get("area_name"),
        "country": normalize_country(raw.get("country")),
        "location_highlight": raw.get("location_highlight"),
        "coordinates": raw.get("coordinates"),
        "amenities": raw.get("amenities") or [],
        "amenity_groups": raw.get("amenity_groups"),
        "highlights": raw.get("highlights") or [],
        "awards": raw.get("awards") or [],
        "warnings": raw.get("warnings") or [],
        "review_score": raw.get("review_score"),
        "review_count": raw.get("review_count"),
        "category_scores": raw.get("category_scores"),
        "check_in_time": raw.get("check_in_time"),
        "check_in_until": raw.get("check_in_until"),
        "check_out_time": raw.get("check_out_time"),
        "reception_open_until": raw.get("reception_open_until"),
        "image_url": raw.get("image_url"),
        "images": raw.get("all_images") or [],
        "image_count": raw.get("image_count"),
        "nearby_attractions": raw.get("nearby_attractions"),
        "nearby_essentials": raw.get("nearby_essentials"),
        "lowest_price": raw.get("price"),
        "currency": raw.get("currency"),
        "price_check_in_date": price_check_in,
        "price_check_out_date": price_check_out,
        "rooms_available": _coerce_rooms_available(raw.get("rooms_available")),
        "scraped_at": scraped_at,
        "destination_name": normalize_city(raw.get("city")),
        "rooms": rooms,
    }

    lat, lon = parse_coordinates(hotel["coordinates"])
    hotel["canonical"] = {
        "name_key": normalize_name_key(hotel["name"]),
        "destination_key": hotel["destination_name"],
        "country_code": hotel["country"],
        "lat": lat,
        "lon": lon,
        "price_tier": compute_price_tier(hotel["lowest_price"], hotel["currency"]),
        "amenity_keys": compute_amenity_keys(normalize_text_list(hotel["amenities"])),
    }
    hotel["retrieval"] = {
        "embedding_text": build_hotel_embedding_text(hotel),
        "payload": build_hotel_payload(hotel),
        "grounding_facts": build_grounding_facts(hotel),
    }

    return hotel


def _coerce_rooms_available(value: Any) -> Optional[bool]:
    """Agoda sends a real boolean; Booking sends an integer room count."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    return None


def normalize_hotels(validated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records = [normalize_hotel(raw) for raw in validated]
    logger.info("normalize: %d hotels normalized", len(records))
    return records


# ---------------------------------------------------------------------------
# Dedupe (within-batch only; does not merge hotels across Agoda/Booking)
# ---------------------------------------------------------------------------

@dataclass
class DedupeStats:
    hotels_removed: int = 0
    rooms_removed: int = 0
    prices_removed: int = 0


def _is_newer(candidate: Optional[datetime], current: Optional[datetime]) -> bool:
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate > current


def _dedupe_rooms(rooms: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    by_key: Dict[int, Dict[str, Any]] = {}
    removed = 0
    for room in rooms:
        existing = by_key.get(room["source_room_id"])
        if existing is None:
            by_key[room["source_room_id"]] = room
            continue
        removed += 1
        new_ts = room["prices"][0]["crawled_at"] if room["prices"] else None
        old_ts = existing["prices"][0]["crawled_at"] if existing["prices"] else None
        if _is_newer(new_ts, old_ts):
            by_key[room["source_room_id"]] = room
    return list(by_key.values()), removed


def _dedupe_prices(prices: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    by_key: Dict[tuple, Dict[str, Any]] = {}
    removed = 0
    for price in prices:
        key = (
            price["check_in_date"],
            price["check_out_date"],
            price["source_url"] or "",
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = price
            continue
        removed += 1
        if _is_newer(price["crawled_at"], existing["crawled_at"]):
            by_key[key] = price
    return list(by_key.values()), removed


def dedupe_hotels(hotels: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], DedupeStats]:
    stats = DedupeStats()
    by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}

    for hotel in hotels:
        key = (hotel["source_platform"], hotel["source_hotel_id"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = hotel
            continue
        stats.hotels_removed += 1
        if _is_newer(hotel["scraped_at"], existing["scraped_at"]):
            by_key[key] = hotel

    deduped = list(by_key.values())
    for hotel in deduped:
        hotel["rooms"], rooms_removed = _dedupe_rooms(hotel["rooms"])
        stats.rooms_removed += rooms_removed
        for room in hotel["rooms"]:
            room["prices"], prices_removed = _dedupe_prices(room["prices"])
            stats.prices_removed += prices_removed

    logger.info(
        "dedupe: removed %d duplicate hotels, %d rooms, %d prices",
        stats.hotels_removed, stats.rooms_removed, stats.prices_removed,
    )
    return deduped, stats


# ---------------------------------------------------------------------------
# Cross-OTA physical-hotel grouping (Phase 3: dedupe canonical identity)
#
# This NEVER merges `hotels` DB rows — same-source dedupe above stays the only
# thing that removes rows. This stage only assigns a `canonical_hotel_key` +
# `review_status` into each hotel's `canonical` dict for AI/RAG presentation,
# per plans/260724-0925-hotel-normalize-dedupe-for-vector-rag/phase-03-dedupe-canonical-identity.md.
# Persisting groups to hotel_identity_groups/hotel_identity_members is deferred
# (see that phase file's risk section); computing them here first lets tests
# prove the grouping is trustworthy before any load-path change.
# ---------------------------------------------------------------------------

AUTO_APPROVED = "auto_approved"
PENDING_REVIEW = "pending_review"

_AUTO_GROUP_THRESHOLD = 0.86
_REVIEW_BAND_LOW = 0.72
_REVIEW_OVERRIDE_MAX_DISTANCE_M = 80.0
_COORD_PROXIMITY_FULL_SCORE_M = 30.0
_COORD_PROXIMITY_ZERO_SCORE_M = 250.0

_SCORE_WEIGHTS = {
    "name": 0.45,
    "coordinate": 0.25,
    "address": 0.12,
    "star_type": 0.08,
    "amenities": 0.05,
    "completeness": 0.05,
}


@dataclass
class PhysicalMatchStats:
    candidate_pairs: int = 0
    auto_grouped_pairs: int = 0
    review_pairs: int = 0
    groups_created: int = 0
    groups_pending_review: int = 0


def coordinate_distance_m(
    lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]
) -> Optional[float]:
    """Great-circle distance in meters; None if either point is missing."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(min(1.0, a)))


def _name_similarity(name_key_a: Optional[str], name_key_b: Optional[str]) -> float:
    if not name_key_a or not name_key_b:
        return 0.0
    tokens_a, tokens_b = set(name_key_a.split()), set(name_key_b.split())
    ratio = SequenceMatcher(None, name_key_a, name_key_b).ratio()
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if (tokens_a or tokens_b) else 0.0
    subset = 1.0 if tokens_a and tokens_b and (tokens_a <= tokens_b or tokens_b <= tokens_a) else 0.0
    return max(ratio, jaccard, subset)


def _coordinate_proximity_score(distance_m: Optional[float]) -> float:
    if distance_m is None:
        return 0.0
    if distance_m <= _COORD_PROXIMITY_FULL_SCORE_M:
        return 1.0
    if distance_m >= _COORD_PROXIMITY_ZERO_SCORE_M:
        return 0.0
    span = _COORD_PROXIMITY_ZERO_SCORE_M - _COORD_PROXIMITY_FULL_SCORE_M
    return 1.0 - (distance_m - _COORD_PROXIMITY_FULL_SCORE_M) / span


def _text_token_overlap(a: Optional[str], b: Optional[str]) -> float:
    key_a, key_b = normalize_name_key(a), normalize_name_key(b)
    if not key_a or not key_b:
        return 0.0
    tokens_a, tokens_b = set(key_a.split()), set(key_b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _star_type_compatibility(hotel_a: Dict[str, Any], hotel_b: Dict[str, Any]) -> float:
    score = 0.0
    star_a, star_b = hotel_a.get("star_rating"), hotel_b.get("star_rating")
    if star_a is not None and star_b is not None and abs(star_a - star_b) <= 0.5:
        score += 0.5
    type_a, type_b = hotel_a.get("accommodation_type"), hotel_b.get("accommodation_type")
    if type_a and type_b and type_a == type_b:
        score += 0.5
    return score


def _amenity_overlap(hotel_a: Dict[str, Any], hotel_b: Dict[str, Any]) -> float:
    keys_a = set(hotel_a["canonical"]["amenity_keys"])
    keys_b = set(hotel_b["canonical"]["amenity_keys"])
    if not keys_a or not keys_b:
        return 0.0
    return len(keys_a & keys_b) / len(keys_a | keys_b)


def _completeness_similarity(hotel_a: Dict[str, Any], hotel_b: Dict[str, Any]) -> float:
    """Weak tie-break only (weight 0.05) — never decisive on its own."""

    def _score(hotel: Dict[str, Any]) -> float:
        return sum(
            (
                1 if hotel.get("review_count") else 0,
                1 if hotel.get("images") else 0,
                1 if hotel.get("description") else 0,
            )
        ) / 3

    return 1.0 - abs(_score(hotel_a) - _score(hotel_b))


def score_physical_hotel_pair(hotel_a: Dict[str, Any], hotel_b: Dict[str, Any]) -> float:
    """Weighted pair score per the Phase 3 scoring table. Coordinate proximity
    is a secondary signal only (0.25 weight) — it never dominates, and
    candidates are never generated from coordinates alone (see blocking)."""
    canonical_a, canonical_b = hotel_a["canonical"], hotel_b["canonical"]
    distance_m = coordinate_distance_m(
        canonical_a["lat"], canonical_a["lon"], canonical_b["lat"], canonical_b["lon"]
    )
    return (
        _SCORE_WEIGHTS["name"] * _name_similarity(canonical_a["name_key"], canonical_b["name_key"])
        + _SCORE_WEIGHTS["coordinate"] * _coordinate_proximity_score(distance_m)
        + _SCORE_WEIGHTS["address"] * _text_token_overlap(hotel_a.get("address"), hotel_b.get("address"))
        + _SCORE_WEIGHTS["star_type"] * _star_type_compatibility(hotel_a, hotel_b)
        + _SCORE_WEIGHTS["amenities"] * _amenity_overlap(hotel_a, hotel_b)
        + _SCORE_WEIGHTS["completeness"] * _completeness_similarity(hotel_a, hotel_b)
    )


def _blocking_tokens(hotel: Dict[str, Any]) -> set:
    """Name tokens usable for blocking: the destination's own name doesn't
    count as a "strong token" (every hotel in the same city mentions the city),
    so two unrelated hotels in the same dense city never collide on it alone."""
    canonical = hotel["canonical"]
    name_key = canonical["name_key"]
    if not name_key:
        return set()
    destination_name_key = normalize_name_key(hotel.get("destination_name"))
    destination_tokens = set(destination_name_key.split()) if destination_name_key else set()
    return set(name_key.split()) - destination_tokens


def _generate_candidate_pairs(hotels: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """Block by (destination_key, name token) so comparison is O(candidates),
    not O(n^2). Two hotels never become a candidate pair on coordinates alone —
    they must share a destination and at least one strong, non-destination name
    token first."""
    buckets: Dict[Tuple[str, str], List[int]] = {}
    for idx, hotel in enumerate(hotels):
        canonical = hotel["canonical"]
        destination_key = canonical["destination_key"]
        if not destination_key:
            continue
        for token in _blocking_tokens(hotel):
            buckets.setdefault((destination_key, token), []).append(idx)

    seen: set = set()
    pairs: List[Tuple[int, int]] = []
    for indices in buckets.values():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                pair = (indices[i], indices[j])
                if pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
    return pairs


def group_physical_hotels(
    hotels: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], PhysicalMatchStats]:
    """Assign cross-OTA canonical groups by hotel index. `hotels` rows are
    never merged or removed. Score bands: >=0.86 auto-groups; 0.72-0.86 is
    held as `pending_review` unless name is an exact match within 80m
    (dense-city near-misses with different names never even reach scoring —
    blocking requires a shared name token)."""
    stats = PhysicalMatchStats()
    parent = list(range(len(hotels)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    review_pairs: List[Tuple[int, int, float]] = []
    candidate_pairs = _generate_candidate_pairs(hotels)
    stats.candidate_pairs = len(candidate_pairs)

    for i, j in candidate_pairs:
        hotel_a, hotel_b = hotels[i], hotels[j]
        score = score_physical_hotel_pair(hotel_a, hotel_b)
        canonical_a, canonical_b = hotel_a["canonical"], hotel_b["canonical"]
        exact_name = (
            canonical_a["name_key"] is not None and canonical_a["name_key"] == canonical_b["name_key"]
        )
        distance_m = coordinate_distance_m(
            canonical_a["lat"], canonical_a["lon"], canonical_b["lat"], canonical_b["lon"]
        )
        review_override = (
            exact_name and distance_m is not None and distance_m <= _REVIEW_OVERRIDE_MAX_DISTANCE_M
        )
        if score >= _AUTO_GROUP_THRESHOLD or (_REVIEW_BAND_LOW <= score < _AUTO_GROUP_THRESHOLD and review_override):
            union(i, j)
            stats.auto_grouped_pairs += 1
        elif score >= _REVIEW_BAND_LOW:
            review_pairs.append((i, j, score))
            stats.review_pairs += 1

    groups: Dict[int, Dict[str, Any]] = {}
    components: Dict[int, List[int]] = {}
    for idx in range(len(hotels)):
        components.setdefault(find(idx), []).append(idx)

    group_seq = 0
    for members in components.values():
        if len(members) < 2:
            continue
        group_seq += 1
        stats.groups_created += 1
        group_key = f"grp-{group_seq:06d}"
        for idx in members:
            groups[idx] = {
                "canonical_hotel_key": group_key,
                "member_count": len(members),
                "review_status": AUTO_APPROVED,
                "confidence": None,
            }

    for i, j, score in review_pairs:
        if i in groups or j in groups:
            continue  # an auto-approved group already covers one side; that wins.
        group_seq += 1
        stats.groups_created += 1
        stats.groups_pending_review += 1
        group_key = f"grp-{group_seq:06d}"
        for idx in (i, j):
            groups[idx] = {
                "canonical_hotel_key": group_key,
                "member_count": 2,
                "review_status": PENDING_REVIEW,
                "confidence": round(score, 3),
            }

    logger.info(
        "physical_match: %d candidate pairs, %d auto-grouped, %d pending review, %d groups",
        stats.candidate_pairs, stats.auto_grouped_pairs, stats.groups_pending_review, stats.groups_created,
    )
    return groups, stats


def assign_physical_hotel_groups(hotels: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], PhysicalMatchStats]:
    """Compute and attach cross-OTA canonical groups onto each hotel's
    `canonical` dict. Ungrouped hotels get `canonical_hotel_key=None`,
    `review_status="ungrouped"` — deterministic and idempotent across reruns
    given the same input batch."""
    groups, stats = group_physical_hotels(hotels)
    for idx, hotel in enumerate(hotels):
        group_info = groups.get(idx)
        hotel["canonical"]["canonical_hotel_key"] = group_info["canonical_hotel_key"] if group_info else None
        hotel["canonical"]["group_review_status"] = group_info["review_status"] if group_info else "ungrouped"
        hotel["canonical"]["group_confidence"] = group_info["confidence"] if group_info else None
    return hotels, stats


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

@dataclass
class LoadStats:
    hotels_upserted: int = 0
    rooms_upserted: int = 0
    prices_upserted: int = 0


# Cột của bảng hotels. `country` và `highlights` có trong bản ghi đã normalize nhưng KHÔNG nằm ở
# đây: chúng chỉ phục vụ dedupe/payload/embedding trong ETL, bảng hotels không có cột tương ứng.
_HOTEL_COLUMNS = [
    "destination_id", "source_platform", "source_hotel_id", "source_url", "name",
    "accommodation_type", "description", "star_rating", "address", "city", "area_name",
    "location_highlight", "coordinates", "amenities", "amenity_groups",
    "awards", "warnings", "review_score", "review_count",
    "category_scores", "check_in_time", "check_in_until",
    "check_out_time", "reception_open_until", "image_url", "images", "image_count",
    "nearby_attractions", "nearby_essentials", "lowest_price", "currency",
    "price_check_in_date", "price_check_out_date", "rooms_available",
    "scraped_at",
]

_HOTEL_UPDATE_COLUMNS = [c for c in _HOTEL_COLUMNS if c not in ("source_platform", "source_hotel_id")]

_ROOM_COLUMNS = [
    "hotel_id", "source_room_id", "name", "bed_description", "room_size_sqm",
    "max_occupancy_raw", "max_guests", "view", "room_facilities", "amenity_groups",
    "images", "image_count",
]

_ROOM_UPDATE_COLUMNS = [c for c in _ROOM_COLUMNS if c not in ("hotel_id", "source_room_id")]

_PRICE_COLUMNS = [
    "room_id", "price", "currency", "check_in_date", "check_out_date", "sold_out",
    "crossed_out", "review_score", "review_text", "source_url", "crawled_at",
]

_PRICE_UPDATE_COLUMNS = [
    "price", "currency", "sold_out", "crossed_out", "review_score", "review_text", "crawled_at",
]


def _jsonb_fields(row: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {k: (Json(v) if isinstance(v, (dict, list)) and k not in _ARRAY_JSONB_EXCEPTIONS else v) for k, v in row.items() if k in keys}


# amenity_groups/category_scores/nearby_attractions/nearby_essentials are JSONB;
# amenities/awards/warnings/images are native Postgres TEXT[] arrays and must NOT be wrapped in
# Json(), psycopg2 adapts Python lists of str to TEXT[] directly.
_ARRAY_JSONB_EXCEPTIONS = {"amenities", "awards", "warnings", "images", "room_facilities"}


def _upsert_hotel(cursor, hotel: Dict[str, Any], destination_id: Optional[str]) -> str:
    row = {**hotel, "destination_id": destination_id}
    columns = _HOTEL_COLUMNS
    values = _jsonb_fields(row, columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _HOTEL_UPDATE_COLUMNS)
    query = f"""
        INSERT INTO hotels ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (source_platform, source_hotel_id) DO UPDATE SET
            {update_clause},
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
    """
    cursor.execute(query, values)
    return str(cursor.fetchone()[0])


def _upsert_room(cursor, room: Dict[str, Any], hotel_id: str) -> str:
    row = {**room, "hotel_id": hotel_id}
    columns = _ROOM_COLUMNS
    values = _jsonb_fields(row, columns)
    placeholders = ", ".join(f"%({c})s" for c in columns)
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _ROOM_UPDATE_COLUMNS)
    query = f"""
        INSERT INTO rooms ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (hotel_id, source_room_id) DO UPDATE SET
            {update_clause},
            updated_at = CURRENT_TIMESTAMP
        RETURNING id;
    """
    cursor.execute(query, values)
    return str(cursor.fetchone()[0])


def _upsert_price(cursor, price: Dict[str, Any], room_id: str) -> None:
    row = {**price, "room_id": room_id}
    columns = _PRICE_COLUMNS
    values = {k: v for k, v in row.items() if k in columns}
    placeholders = ", ".join(f"%({c})s" for c in columns)
    update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in _PRICE_UPDATE_COLUMNS)
    query = f"""
        INSERT INTO room_prices ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT (room_id, check_in_date, check_out_date, COALESCE(source_url, ''))
        DO UPDATE SET {update_clause};
    """
    cursor.execute(query, values)


def load_hotels_to_db(hotels: List[Dict[str, Any]], db_conn_kwargs: Dict[str, str]) -> LoadStats:
    stats = LoadStats()
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()

        destination_ids: Dict[str, Optional[str]] = {}
        for hotel in hotels:
            destination_name = hotel["destination_name"]
            if destination_name not in destination_ids:
                destination_ids[destination_name] = (
                    get_or_create_destination(destination_name, "", db_conn_kwargs)
                    if destination_name
                    else None
                )
            destination_id = destination_ids[destination_name]

            hotel_id = _upsert_hotel(cursor, hotel, destination_id)
            stats.hotels_upserted += 1

            for room in hotel["rooms"]:
                room_id = _upsert_room(cursor, room, hotel_id)
                stats.rooms_upserted += 1

                for price in room["prices"]:
                    _upsert_price(cursor, price, room_id)
                    stats.prices_upserted += 1

        conn.commit()
    except Exception as e:
        print(f"Database insertion error in load_hotels_to_db: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    logger.info(
        "load: upserted %d hotels, %d rooms, %d prices",
        stats.hotels_upserted, stats.rooms_upserted, stats.prices_upserted,
    )
    return stats


# ---------------------------------------------------------------------------
# Quality Check
# ---------------------------------------------------------------------------

def _sanity_checks(hotels: List[Dict[str, Any]]) -> List[str]:
    issues = []
    for hotel in hotels:
        label = f"{hotel['source_platform']}:{hotel['source_hotel_id']}"
        star_rating = hotel.get("star_rating")
        if star_rating is not None and not (0 <= star_rating <= 5):
            issues.append(f"{label}: star_rating out of range ({star_rating})")
        for room in hotel["rooms"]:
            for price in room["prices"]:
                if price["price"] is not None and price["price"] <= 0:
                    issues.append(f"{label}/room {room['source_room_id']}: price <= 0 ({price['price']})")
    return issues


def _vector_quality_metrics(hotels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Phase 2 gate metrics: coordinate coverage, embedding-text emptiness,
    Qdrant payload size, and per-source field coverage for Agoda-only fields."""
    missing_coordinates = 0
    empty_embedding_text = 0
    payload_sizes: List[int] = []
    description_coverage: Dict[str, List[int]] = {}

    for hotel in hotels:
        canonical = hotel.get("canonical") or {}
        retrieval = hotel.get("retrieval") or {}
        if canonical.get("lat") is None or canonical.get("lon") is None:
            missing_coordinates += 1
        if not (retrieval.get("embedding_text") or "").strip():
            empty_embedding_text += 1
        payload = retrieval.get("payload")
        if payload is not None:
            payload_sizes.append(len(json.dumps(payload, default=str)))

        counts = description_coverage.setdefault(hotel["source_platform"], [0, 0])
        counts[1] += 1
        if hotel.get("description"):
            counts[0] += 1

    return {
        "total": len(hotels),
        "missing_coordinates": missing_coordinates,
        "empty_embedding_text": empty_embedding_text,
        "max_payload_bytes": max(payload_sizes) if payload_sizes else 0,
        "avg_payload_bytes": round(sum(payload_sizes) / len(payload_sizes), 1) if payload_sizes else 0,
        "description_coverage_by_source": {
            src: f"{with_desc}/{total}" for src, (with_desc, total) in sorted(description_coverage.items())
        },
    }


def quality_check_hotels(
    validation_stats: ValidationStats,
    dedupe_stats: DedupeStats,
    physical_match_stats: PhysicalMatchStats,
    load_stats: LoadStats,
    hotels: List[Dict[str, Any]],
    reports_dir: str,
) -> str:
    issues = _sanity_checks(hotels)
    vector_metrics = _vector_quality_metrics(hotels)

    by_source: Dict[str, int] = {}
    for hotel in hotels:
        by_source[hotel["source_platform"]] = by_source.get(hotel["source_platform"], 0) + 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    report_path = reports_path / f"hotel_quality_report_{timestamp}.md"

    lines = [
        f"# Hotel Pipeline Quality Report — {timestamp}",
        "",
        "## Validate & Clean",
        f"- Total extracted: {validation_stats.total}",
        f"- Passed validation: {validation_stats.valid}",
        f"- Rejected: {validation_stats.rejected}",
    ]
    if validation_stats.rejected_samples:
        lines.append("- Rejected samples:")
        lines += [f"  - {s}" for s in validation_stats.rejected_samples[:20]]

    lines += [
        "",
        "## Deduplicate (within-batch only, does not merge across OTAs)",
        f"- Duplicate hotels removed: {dedupe_stats.hotels_removed}",
        f"- Duplicate rooms removed: {dedupe_stats.rooms_removed}",
        f"- Duplicate prices removed: {dedupe_stats.prices_removed}",
        "",
        "## Cross-OTA physical-hotel grouping (AI/RAG presentation only, hotels rows never merged)",
        f"- Candidate pairs evaluated: {physical_match_stats.candidate_pairs}",
        f"- Auto-approved groups (score >= {_AUTO_GROUP_THRESHOLD}): {physical_match_stats.groups_created - physical_match_stats.groups_pending_review}",
        f"- Groups pending manual review (score {_REVIEW_BAND_LOW}-{_AUTO_GROUP_THRESHOLD}): {physical_match_stats.groups_pending_review}",
        "",
        "## Load",
        f"- Hotels upserted: {load_stats.hotels_upserted}",
        f"- Rooms upserted: {load_stats.rooms_upserted}",
        f"- Prices upserted: {load_stats.prices_upserted}",
        "",
        "## Hotels by source",
    ]
    lines += [f"- {source}: {count}" for source, count in sorted(by_source.items())]

    lines += [
        "",
        "## Vector/RAG quality",
        f"- Hotels missing coordinates: {vector_metrics['missing_coordinates']}/{vector_metrics['total']}",
        f"- Hotels with empty embedding_text: {vector_metrics['empty_embedding_text']}/{vector_metrics['total']}",
        f"- Payload size (bytes): max {vector_metrics['max_payload_bytes']}, avg {vector_metrics['avg_payload_bytes']}",
        "- Description coverage by source (Agoda-only field):",
    ]
    lines += [f"  - {src}: {cov}" for src, cov in vector_metrics["description_coverage_by_source"].items()]

    lines += ["", "## Sanity check issues"]
    if issues:
        lines += [f"- {issue}" for issue in issues[:50]]
        if len(issues) > 50:
            lines.append(f"- ... and {len(issues) - 50} more")
    else:
        lines.append("- None found")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("quality_check: report written to %s", report_path)
    return str(report_path)


# ---------------------------------------------------------------------------
# End-to-end runner (standalone entrypoint, mirrors the Airflow task sequence)
# ---------------------------------------------------------------------------

def run_hotel_pipeline(
    agoda_path: str,
    booking_path: str,
    db_conn_kwargs: Dict[str, str],
    reports_dir: str,
) -> str:
    raw_records = extract_hotels(agoda_path, booking_path)
    validated, validation_stats = validate_hotels(raw_records)
    normalized = normalize_hotels(validated)
    deduped, dedupe_stats = dedupe_hotels(normalized)
    deduped, physical_match_stats = assign_physical_hotel_groups(deduped)
    load_stats = load_hotels_to_db(deduped, db_conn_kwargs)
    return quality_check_hotels(
        validation_stats, dedupe_stats, physical_match_stats, load_stats, deduped, reports_dir
    )
