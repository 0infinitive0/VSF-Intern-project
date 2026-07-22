"""Shared primitives for normalizing Booking.com and Agoda hotel datasets.

The two scrapers disagree on almost every convention: currency codes, city
spelling, coordinate packing, accommodation-type vocabulary and rating labels.
Every rule that resolves such a disagreement lives here so the per-source
adapters stay pure shape-shifters.
"""

import hashlib
import math
import re
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any

# Deterministic UUID namespace. Re-running the pipeline must reproduce the same
# primary keys, otherwise ON CONFLICT upserts silently duplicate every row.
UUID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "vsf.v-ota-ai-chat")

# Booking emits both "US" and "US$" inside a single run; neither is ISO 4217.
CURRENCY_ALIASES = {
    "US": "USD",
    "US$": "USD",
    "USD": "USD",
    "$": "USD",
    "VND": "VND",
    "₫": "VND",
    "VNĐ": "VND",
}

# Accent-free lowercase city text -> destination slug.
CITY_ALIASES = {
    "ho chi minh city": "ho-chi-minh",
    "ho chi minh": "ho-chi-minh",
    "thanh pho ho chi minh": "ho-chi-minh",
    "tp. ho chi minh": "ho-chi-minh",
    "saigon": "ho-chi-minh",
    "ha noi": "ha-noi",
    "hanoi": "ha-noi",
    "da nang": "da-nang",
    "danang": "da-nang",
    "nha trang": "nha-trang",
    "hue": "hue",
    "thanh pho hue": "hue",
}

# Display metadata for destinations created from the datasets.
DESTINATION_META = {
    "ho-chi-minh": {"name": "Hồ Chí Minh", "region": "Nam Bộ", "coordinates": "10.7769,106.7009"},
    "ha-noi": {"name": "Hà Nội", "region": "Bắc Bộ", "coordinates": "21.0278,105.8342"},
    "da-nang": {"name": "Đà Nẵng", "region": "Trung Bộ", "coordinates": "16.0544,108.2022"},
    "nha-trang": {"name": "Nha Trang", "region": "Nam Trung Bộ", "coordinates": "12.2388,109.1967"},
    "hue": {"name": "Huế", "region": "Trung Bộ", "coordinates": "16.4637,107.5909"},
}

# Booking uses a finer vocabulary than Agoda, so Booking's enum is canonical.
# Agoda collapses guest houses and hostels into a single label; the mapping is
# lossy in that direction and callers should treat it as low confidence.
ACCOMMODATION_TYPES = {
    "hotel": "hotel",
    "khach san": "hotel",
    "resort": "resort",
    "khu nghi duong": "resort",
    "apartment": "apartment",
    "can ho": "apartment",
    "guest_house": "guest_house",
    "guesthouse": "guest_house",
    "nha nghi": "guest_house",
    "hostel": "hostel",
    "homestay": "homestay",
    "villa": "villa",
    "biet thu": "villa",
    "motel": "motel",
}

# Mainland plus islands. Coordinates outside this box are scraper noise.
VIETNAM_LAT_RANGE = (8.0, 23.5)
VIETNAM_LNG_RANGE = (102.0, 110.0)

# Generic words carry no identity signal when comparing two property names.
_NAME_STOPWORDS = {
    "hotel", "khach", "san", "resort", "hostel", "nha", "nghi", "guest", "house",
    "guesthouse", "homestay", "motel", "villa", "the", "a", "an", "and", "va",
}

_SIZE_PATTERN = re.compile(r"^\s*\d+([.,]\d+)?\s*m²\s*$")
_TIME_PATTERN = re.compile(r"(\d{1,2}):(\d{2})")
_LEADING_INT_PATTERN = re.compile(r"(\d+)")


def strip_accents(text: str) -> str:
    """Return `text` without Vietnamese diacritics, including the đ/Đ pair."""
    replaced = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", replaced)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def fold(text: str | None) -> str:
    """Lowercase, accent-free, single-spaced form used for every lookup key."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", strip_accents(str(text)).lower()).strip()


def clean_text(value: Any) -> str | None:
    """Trim a scalar into a database-friendly string, or None when empty."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_list(values: Iterable[Any] | None) -> list[str]:
    """Flatten to trimmed strings, drop blanks, de-duplicate keeping order."""
    cleaned = []
    for value in values or []:
        text = clean_text(value)
        if text:
            cleaned.append(text)
    return list(dict.fromkeys(cleaned))


def city_slug(raw_city: str | None) -> str | None:
    """Map a raw city string to a destination slug, or None when unknown.

    Unknown cities must fail loudly upstream instead of silently producing a
    hotel with a NULL destination_id.
    """
    key = fold(raw_city)
    if not key:
        return None
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    # Datasets append administrative suffixes such as "Hue City".
    trimmed = re.sub(r"\b(city|province|tinh|thanh pho)\b", "", key).strip()
    return CITY_ALIASES.get(re.sub(r"\s+", " ", trimmed))


def normalize_currency(raw_currency: str | None) -> str | None:
    """Map a scraper currency token to ISO 4217, or None when unrecognized."""
    if not raw_currency:
        return None
    token = str(raw_currency).strip().upper()
    return CURRENCY_ALIASES.get(token)


def normalize_accommodation_type(raw_type: str | None) -> str | None:
    """Map either vocabulary onto Booking's finer accommodation enum."""
    key = fold(raw_type).replace("-", " ")
    return ACCOMMODATION_TYPES.get(key) or ACCOMMODATION_TYPES.get(key.replace(" ", "_"))


def normalize_star_rating(raw_stars: Any) -> int | None:
    """Return 1-5 or None. Agoda encodes "unrated" as 0, Booking as null."""
    try:
        stars = int(raw_stars)
    except (TypeError, ValueError):
        return None
    return stars if 1 <= stars <= 5 else None


def parse_coordinates(latitude: Any, longitude: Any) -> tuple[float | None, float | None]:
    """Parse a lat/lng pair and reject anything outside Vietnam."""
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return None, None
    if not VIETNAM_LAT_RANGE[0] <= lat <= VIETNAM_LAT_RANGE[1]:
        return None, None
    if not VIETNAM_LNG_RANGE[0] <= lng <= VIETNAM_LNG_RANGE[1]:
        return None, None
    return lat, lng


def split_coordinate_string(raw: str | None) -> tuple[float | None, float | None]:
    """Parse Agoda's packed "lat,lng" string."""
    if not raw or "," not in str(raw):
        return None, None
    lat_text, _, lng_text = str(raw).partition(",")
    return parse_coordinates(lat_text, lng_text)


def format_coordinates(latitude: float | None, longitude: float | None) -> str | None:
    """Render coordinates for the VARCHAR(50) column with a fixed precision."""
    if latitude is None or longitude is None:
        return None
    return f"{latitude:.6f},{longitude:.6f}"


def parse_time_of_day(raw: str | None) -> str | None:
    """Pull the first HH:MM out of a free-text policy blob.

    Booking glues the check-in time to the following sentence, for example
    "Từ 14:00Khách được yêu cầu xuất trình giấy tờ tùy thân".
    """
    if not raw:
        return None
    match = _TIME_PATTERN.search(str(raw))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_first_int(raw: str | None) -> int | None:
    """Pull the first integer out of text such as "Tối đa 2 người lớn"."""
    if raw is None:
        return None
    match = _LEADING_INT_PATTERN.search(str(raw))
    return int(match.group(1)) if match else None


def looks_like_room_size(value: str) -> bool:
    """True for Booking room facilities that actually encode an area."""
    return bool(_SIZE_PATTERN.match(value))


# Agoda amenity groups that do not describe a facility. "Ngôn ngữ được sử dụng"
# lists the languages reception speaks; storing those as hotel amenities makes
# "Tiếng Anh" searchable as if it were a pool or a gym.
_NON_AMENITY_GROUPS = frozenset({"ngon ngu duoc su dung"})


def is_amenity_group(group_name: str | None) -> bool:
    """True when an Agoda amenity group really lists facilities."""
    return fold(group_name) not in _NON_AMENITY_GROUPS


def strip_url_query(url: str | None) -> str | None:
    """Drop the query string so a hotel URL is stable across crawl dates.

    Booking bakes check-in, check-out and currency into the product URL, which
    would otherwise make the same hotel look like a new identity every run.
    """
    if not url:
        return None
    return str(url).split("?", 1)[0].split("#", 1)[0]


def normalize_property_name(name: str | None) -> str:
    """Comparable form of a property name for duplicate detection."""
    folded = fold(name)
    folded = re.sub(r"\(.*?\)", " ", folded)
    tokens = [token for token in re.split(r"[^a-z0-9]+", folded) if token and token not in _NAME_STOPWORDS]
    return " ".join(tokens)


def token_set_ratio(left: str, right: str) -> float:
    """Order-insensitive similarity in the 0-100 range.

    Mirrors the classic token-set ratio: compare the shared token core against
    each side's remainder so "alba hotel hue" and "hue alba" still match.
    """
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    shared = " ".join(sorted(left_tokens & right_tokens))
    left_rest = f"{shared} {' '.join(sorted(left_tokens - right_tokens))}".strip()
    right_rest = f"{shared} {' '.join(sorted(right_tokens - left_tokens))}".strip()
    candidates = (
        SequenceMatcher(None, shared, left_rest).ratio(),
        SequenceMatcher(None, shared, right_rest).ratio(),
        SequenceMatcher(None, left_rest, right_rest).ratio(),
    )
    return round(max(candidates) * 100, 2)


def token_sort_ratio(left: str, right: str) -> float:
    """Order-insensitive similarity that still penalizes extra tokens.

    Unlike `token_set_ratio`, a name that is a strict subset of another scores
    low. "Nicecy" and "Nicecy Ben Thanh" are different properties of one chain,
    and only this measure separates them.
    """
    left_sorted = " ".join(sorted(left.split()))
    right_sorted = " ".join(sorted(right.split()))
    if not left_sorted or not right_sorted:
        return 0.0
    return round(SequenceMatcher(None, left_sorted, right_sorted).ratio() * 100, 2)


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def stable_uuid(*parts: Any) -> str:
    """Deterministic UUID from the given identity parts."""
    return str(uuid.uuid5(UUID_NAMESPACE, "|".join(str(part) for part in parts)))


def file_digest(path: str, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file, used to skip byte-identical dataset re-exports."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_signature(parts: Sequence[str | None]) -> str:
    """Build the stable package label used inside the room_prices unique key.

    Never returns NULL: PostgreSQL treats NULL as distinct inside a UNIQUE
    constraint, so a null package would defeat the price upsert entirely.
    """
    labels = sorted({text for text in (clean_text(part) for part in parts) if text})
    return "|".join(labels) if labels else "standard"


def destination_payload(slug: str) -> dict[str, str]:
    """Display name, region and centre coordinates for a destination slug."""
    return DESTINATION_META[slug]
