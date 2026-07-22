import math
import re
import unicodedata
import uuid
from collections import defaultdict
from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CATEGORY_ORDER = (
    "Museums & culture",
    "Nature & outdoor",
    "Entertainment & tickets",
    "Workshops & classes",
    "Food & drink experiences",
    "Sightseeing tours",
    "Restaurants & cafes",
    "Other activities",
)


def parse_coordinates(value: str) -> Tuple[float, float]:
    """Parse a ``latitude,longitude`` input and reject out-of-range values."""
    try:
        latitude_text, longitude_text = value.split(",", 1)
        latitude = float(latitude_text.strip())
        longitude = float(longitude_text.strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Coordinates must use the format 'latitude,longitude'.") from exc

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Coordinates are outside the valid latitude/longitude range.")
    return latitude, longitude


def haversine_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_meters = 6_371_000.0
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return earth_radius_meters * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _point_on_segment(
    longitude: float,
    latitude: float,
    point_a: Sequence[float],
    point_b: Sequence[float],
    tolerance: float = 1e-10,
) -> bool:
    ax, ay = point_a[:2]
    bx, by = point_b[:2]
    cross = (longitude - ax) * (by - ay) - (latitude - ay) * (bx - ax)
    if abs(cross) > tolerance:
        return False
    return (
        min(ax, bx) - tolerance <= longitude <= max(ax, bx) + tolerance
        and min(ay, by) - tolerance <= latitude <= max(ay, by) + tolerance
    )


def _point_in_ring(latitude: float, longitude: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False

    previous = ring[-1]
    for current in ring:
        if _point_on_segment(longitude, latitude, previous, current):
            return True
        current_lon, current_lat = current[:2]
        previous_lon, previous_lat = previous[:2]
        crosses = (current_lat > latitude) != (previous_lat > latitude)
        if crosses:
            intersection_lon = (
                (previous_lon - current_lon)
                * (latitude - current_lat)
                / (previous_lat - current_lat)
                + current_lon
            )
            if longitude < intersection_lon:
                inside = not inside
        previous = current
    return inside


def _point_in_polygon(
    latitude: float,
    longitude: float,
    polygon: Sequence[Sequence[Sequence[float]]],
) -> bool:
    if not polygon or not _point_in_ring(latitude, longitude, polygon[0]):
        return False
    return not any(_point_in_ring(latitude, longitude, hole) for hole in polygon[1:])


def point_in_geometry(latitude: float, longitude: float, geometry: Dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return _point_in_polygon(latitude, longitude, coordinates)
    if geometry_type == "MultiPolygon":
        return any(
            _point_in_polygon(latitude, longitude, polygon) for polygon in coordinates
        )
    return False


def is_coordinate_allowed(
    latitude: Optional[float],
    longitude: Optional[float],
    location_context: Dict[str, Any],
) -> bool:
    if latitude is None or longitude is None:
        return False
    if location_context.get("mode") == "radius":
        distance = haversine_meters(
            location_context["latitude"],
            location_context["longitude"],
            latitude,
            longitude,
        )
        return distance <= location_context["radius_meters"]
    if location_context.get("mode") == "boundary":
        return point_in_geometry(latitude, longitude, location_context["geometry"])
    raise ValueError("Unknown location filtering mode.")


def normalize_text(value: str) -> str:
    value = (value or "").replace("Đ", "D").replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


_ALLOWED_NAME_PUNCTUATION = set(" &'’.,()/-:+")


def sanitize_attraction_name(value: str) -> str:
    """Keep Latin-script place names and ordinary name punctuation."""
    normalized = unicodedata.normalize("NFC", str(value or ""))
    kept: List[str] = []
    previous_was_latin = False
    for character in normalized:
        category = unicodedata.category(character)
        is_latin = category.startswith("L") and "LATIN" in unicodedata.name(
            character,
            "",
        )
        if is_latin:
            kept.append(character)
            previous_was_latin = True
        elif category.startswith("M") and previous_was_latin:
            kept.append(character)
        elif character.isascii() and character.isdigit():
            kept.append(character)
            previous_was_latin = False
        elif character in _ALLOWED_NAME_PUNCTUATION or character.isspace():
            kept.append(character)
            previous_was_latin = False
        else:
            kept.append(" ")
            previous_was_latin = False

    name = " ".join("".join(kept).split())
    name = re.sub(r"\(\s*\)", " ", name)
    name = re.sub(r"\s+([,.;:)])", r"\1", name)
    name = re.sub(r"([(])\s+", r"\1", name)
    name = " ".join(name.split())
    return name.strip(" &'’.,/-:+")


def normalize_category(name: str, description: str = "", is_tour: bool = False) -> str:
    searchable = normalize_text(f"{name} {description}")
    category_keywords = (
        ("Museums & culture", ("museum", "gallery", "heritage", "culture", "temple", "pagoda", "historic")),
        ("Nature & outdoor", ("waterfall", "beach", "island", "snorkel", "diving", "hiking", "nature", "mountain", "park")),
        ("Entertainment & tickets", ("show", "theater", "theatre", "puppet", "theme park", "water park", "concert", "ticket", "admission")),
        ("Workshops & classes", ("workshop", "class", "lesson", "craft", "cooking class")),
        ("Food & drink experiences", ("food tour", "tasting", "dining experience", "buffet", "coffee experience")),
        ("Restaurants & cafes", ("restaurant", "cafe", "coffee shop", "bar")),
    )
    for category, keywords in category_keywords:
        if any(keyword in searchable for keyword in keywords):
            return category
    if is_tour or any(keyword in searchable for keyword in ("tour", "cruise", "excursion", "trip")):
        return "Sightseeing tours"
    return "Other activities"


def parse_duration_minutes(text: str) -> Optional[int]:
    normalized = normalize_text(text)
    day_match = re.search(r"(\d+(?:\.\d+)?)\s*days?", normalized)
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)", normalized)
    minute_match = re.search(r"(\d+)\s*(?:minutes?|mins?)", normalized)
    if not any((day_match, hour_match, minute_match)):
        return None
    total = 0
    if day_match:
        total += round(float(day_match.group(1)) * 24 * 60)
    if hour_match:
        total += round(float(hour_match.group(1)) * 60)
    if minute_match:
        total += int(minute_match.group(1))
    return total or None


def _canonical_name(item: Dict[str, Any]) -> str:
    name = normalize_text(item.get("name", ""))
    removable = {
        "admission",
        "entry",
        "entrance",
        "experience",
        "skip",
        "line",
        "ticket",
        "tickets",
    }
    return " ".join(word for word in name.split() if word not in removable)


def _completeness_score(item: Dict[str, Any]) -> Tuple[int, int, int]:
    populated = sum(
        bool(item.get(field))
        for field in (
            "description",
            "address",
            "latitude",
            "longitude",
            "estimated_duration_minutes",
            "ticket_price_adult",
            "rating",
            "review_count",
            "images",
        )
    )
    return (
        populated,
        int(item.get("review_count") or 0),
        len(item.get("description") or ""),
    )


def _are_duplicates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if bool(left.get("is_tour")) != bool(right.get("is_tour")):
        return False
    same_source_id = (
        bool(left.get("source_id"))
        and left.get("source") == right.get("source")
        and left.get("source_id") == right.get("source_id")
    )
    left_name = _canonical_name(left)
    right_name = _canonical_name(right)
    exact_name = left_name == right_name
    left_tokens = set(left_name.split())
    right_tokens = set(right_name.split())
    shared_tokens = left_tokens & right_tokens
    token_similarity = (
        len(shared_tokens) / len(left_tokens | right_tokens)
        if left_tokens and right_tokens
        else 0.0
    )
    similar_name = (
        SequenceMatcher(None, left_name, right_name).ratio() >= 0.84
        or (len(shared_tokens) >= 2 and token_similarity >= 0.7)
    )
    if not same_source_id and not exact_name and not similar_name:
        return False
    if (
        not same_source_id
        and not exact_name
        and left.get("category") != right.get("category")
    ):
        return False
    if left.get("is_tour"):
        if same_source_id:
            return True
        return (
            left.get("estimated_duration_minutes")
            == right.get("estimated_duration_minutes")
            and normalize_text(left.get("address", ""))
            == normalize_text(right.get("address", ""))
        )
    coordinates = (
        left.get("latitude"),
        left.get("longitude"),
        right.get("latitude"),
        right.get("longitude"),
    )
    if same_source_id:
        return True
    if any(value is None for value in coordinates):
        return False
    return haversine_meters(*coordinates) <= 300


def _merge_duplicate(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    primary, secondary = sorted((left, right), key=_completeness_score, reverse=True)
    merged = deepcopy(primary)
    for key, value in secondary.items():
        if not merged.get(key) and value:
            merged[key] = deepcopy(value)
    merged["images"] = list(
        dict.fromkeys((primary.get("images") or []) + (secondary.get("images") or []))
    )
    if int(secondary.get("review_count") or 0) > int(primary.get("review_count") or 0):
        merged["review_count"] = secondary.get("review_count")
        merged["rating"] = secondary.get("rating")
    sources = set(primary.get("sources") or [primary.get("source")])
    sources.update(secondary.get("sources") or [secondary.get("source")])
    merged["sources"] = sorted(source for source in sources if source)
    return merged


def deduplicate_attractions(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduplicated: List[Dict[str, Any]] = []
    for candidate in candidates:
        for index, existing in enumerate(deduplicated):
            if _are_duplicates(existing, candidate):
                deduplicated[index] = _merge_duplicate(existing, candidate)
                break
        else:
            deduplicated.append(deepcopy(candidate))
    return deduplicated


def select_diverse_attractions(
    candidates: Iterable[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        buckets[candidate.get("category") or "Other activities"].append(candidate)
    for bucket in buckets.values():
        bucket.sort(
            key=lambda item: (
                int(item.get("review_count") or 0),
                float(item.get("rating") or 0),
                len(item.get("description") or ""),
            ),
            reverse=True,
        )

    categories = [category for category in CATEGORY_ORDER if buckets.get(category)]
    categories.extend(category for category in buckets if category not in categories)
    selected: List[Dict[str, Any]] = []
    per_category = defaultdict(int)
    soft_category_cap = max(1, math.ceil(limit * 0.4)) if len(categories) > 1 else limit

    while len(selected) < limit:
        made_progress = False
        for category in categories:
            if len(selected) >= limit:
                break
            if per_category[category] >= soft_category_cap or not buckets[category]:
                continue
            selected.append(buckets[category].pop(0))
            per_category[category] += 1
            made_progress = True
        if not made_progress:
            break

    # The cap is intentionally soft: when the available category mix cannot
    # fill the requested limit under 40%, relax it evenly instead of letting
    # the globally highest-scored category consume every remaining slot.
    while len(selected) < limit:
        available = [category for category in categories if buckets[category]]
        if not available:
            break
        available.sort(
            key=lambda category: (
                per_category[category],
                categories.index(category),
            )
        )
        for category in available:
            if len(selected) >= limit:
                break
            selected.append(buckets[category].pop(0))
            per_category[category] += 1
    return selected


def stable_attraction_id(item: Dict[str, Any]) -> str:
    source = item.get("source") or "combined"
    source_id = item.get("source_id") or _canonical_name(item)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vsf:{source}:{source_id}"))
