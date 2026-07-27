"""Pure, deterministic scheduling rules for the terminal trip planner."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

ItemKind = Literal["breakfast", "attraction", "lunch", "rest", "coffee", "dinner", "evening"]


@dataclass(frozen=True)
class PlanningPolicy:
    cluster_radii_km: tuple[float, ...] = (5.0, 10.0, 15.0)
    distance_score_limit_km: float = 15.0
    urban_speed_kmh: float = 25.0
    minimum_travel_minutes: int = 10
    playgrounds_per_trip: int = 1
    playgrounds_per_child_focused_day: int = 1
    long_activity_minutes: int = 150
    lunch_window_start: str = "11:00:00"
    lunch_preferred_time: str = "11:30:00"
    lunch_window_end: str = "12:30:00"
    beach_morning_cutoff: str = "10:30:00"
    beach_afternoon_start: str = "15:30:00"


@dataclass(frozen=True)
class PlaceCandidate:
    id: str
    name: str
    category: str = "Other activities"
    coordinates: str | tuple[float, float] | None = None
    similarity: float = 0.0
    rating: float | None = None
    opening_time: str | None = None
    closing_time: str | None = None
    estimated_duration_minutes: int | None = None
    is_tour: bool = False
    description: str | None = None
    covered_meals: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PlaceCandidate:
        return cls(
            id=str(value.get("id") or ""),
            name=str(value.get("name") or ""),
            category=str(value.get("category") or "Other activities"),
            coordinates=value.get("coordinates"),
            similarity=float(value.get("similarity") or 0.0),
            rating=float(value["rating"]) if value.get("rating") is not None else None,
            opening_time=value.get("opening_time"),
            closing_time=value.get("closing_time"),
            estimated_duration_minutes=(
                int(value["estimated_duration_minutes"])
                if value.get("estimated_duration_minutes")
                else None
            ),
            is_tour=bool(value.get("is_tour")),
            description=value.get("description"),
            covered_meals=(
                frozenset(str(meal) for meal in value.get("covered_meals") or [])
                or detect_covered_hotel_meals(value.get("amenities"), value.get("amenity_groups"))
            ),
        )

    @property
    def coordinate_pair(self) -> tuple[float, float] | None:
        return parse_coordinates(self.coordinates)


@dataclass(frozen=True)
class DayTheme:
    day_number: int
    title: str
    query: str


@dataclass(frozen=True)
class ScheduledItem:
    day_number: int
    order_index: int
    start_time: str
    end_time: str
    reference_type: Literal["Hotel", "Attraction", "Event"]
    reference_id: str
    activity: str
    kind: ItemKind
    place_name: str
    coordinates: tuple[float, float] | None
    duration_minutes: int
    category: str = ""
    opening_time: str | None = None
    closing_time: str | None = None
    is_playground: bool = False

    @classmethod
    def from_candidate(
        cls,
        day_number: int,
        order_index: int,
        candidate: PlaceCandidate,
        kind: ItemKind,
        start_time: str,
        duration_minutes: int | None = None,
    ) -> ScheduledItem:
        duration = duration_minutes or default_duration_minutes(candidate, kind)
        reference_type: Literal["Hotel", "Attraction", "Event"] = (
            "Hotel" if candidate.category.casefold() == "hotel" else "Attraction"
        )
        return cls(
            day_number=day_number,
            order_index=order_index,
            start_time=_minutes_to_time(_time_to_minutes(start_time)),
            end_time=_minutes_to_time(_time_to_minutes(start_time) + duration),
            reference_type=reference_type,
            reference_id=candidate.id,
            activity=_activity_label(candidate, kind),
            kind=kind,
            place_name=candidate.name,
            coordinates=candidate.coordinate_pair,
            duration_minutes=duration,
            category=candidate.category,
            opening_time=candidate.opening_time,
            closing_time=candidate.closing_time,
            is_playground=is_playground(candidate),
        )


@dataclass(frozen=True)
class TripChange:
    action: Literal["change_hotel", "replace_place", "reschedule", "add_place", "remove_place"]
    day_number: int | None = None
    order_index: int | None = None
    query: str | None = None
    requested_time: str | None = None


@dataclass
class ItinerarySchedule:
    themes: list[DayTheme]
    items: list[ScheduledItem]
    adjustments: list[str] = field(default_factory=list)

    def items_for_day(self, day_number: int) -> list[ScheduledItem]:
        return sorted(
            (item for item in self.items if item.day_number == day_number),
            key=lambda item: item.order_index,
        )


def infer_trip_change(modification_request: str) -> TripChange | None:
    """Classify explicit edit language before consulting a probabilistic model."""
    normalized = modification_request.casefold()
    day_match = re.search(r"(?:ngày|day)\s*(\d+)", normalized)
    order_match = re.search(r"(?:mục|hoạt động|item)\s*(\d+)", normalized)
    time_match = re.search(r"\b(\d{1,2})(?::|h)(\d{0,2})\b", normalized)
    requested_time = None
    if time_match:
        requested_time = f"{int(time_match.group(1)):02d}:{int(time_match.group(2) or 0):02d}"

    if any(keyword in normalized for keyword in ("khách sạn", "hotel", "resort", "đổi phòng")):
        action = "change_hotel"
    elif any(keyword in normalized for keyword in ("xóa", "bỏ", "remove")):
        action = "remove_place"
    elif any(keyword in normalized for keyword in ("thêm", "add")):
        action = "add_place"
    elif time_match:
        action = "reschedule"
    elif any(keyword in normalized for keyword in ("thay", "đổi điểm", "replace", "swap")):
        action = "replace_place"
    else:
        return None
    return TripChange(
        action=action,
        day_number=int(day_match.group(1)) if day_match else None,
        order_index=int(order_match.group(1)) if order_match else None,
        query=modification_request,
        requested_time=requested_time,
    )


def parse_coordinates(value: str | tuple[float, float] | None) -> tuple[float, float] | None:
    if isinstance(value, tuple) and len(value) == 2:
        latitude, longitude = value
    elif isinstance(value, str):
        try:
            latitude_text, longitude_text = value.split(",", maxsplit=1)
            latitude, longitude = float(latitude_text.strip()), float(longitude_text.strip())
        except (TypeError, ValueError):
            return None
    else:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return float(latitude), float(longitude)


def haversine_distance_km(left: tuple[float, float], right: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, left)
    lat2, lon2 = map(math.radians, right)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(value))


def default_duration_minutes(candidate: PlaceCandidate, kind: ItemKind = "attraction") -> int:
    if candidate.estimated_duration_minutes:
        return candidate.estimated_duration_minutes
    if kind == "breakfast":
        return 60
    if kind == "lunch":
        return 75
    if kind == "dinner":
        return 75
    if kind == "coffee":
        return 45
    if kind == "rest":
        return 90
    normalized = _normalize(f"{candidate.category} {candidate.name}")
    if candidate.is_tour or "tour" in normalized:
        return 180
    if any(term in normalized for term in ("nature", "outdoor", "entertainment", "ticket")):
        return 120
    return 90


def detect_covered_hotel_meals(*hotel_details: Any) -> frozenset[str]:
    """Return only meals whose inclusion is explicit in hotel metadata."""

    def flatten(value: Any, context: str = "") -> list[str]:
        if value is False or value is None:
            return []
        if value is True:
            return [context]
        if isinstance(value, dict):
            flattened = []
            for key, nested in value.items():
                nested_context = f"{context} {key}".strip()
                flattened.extend(flatten(nested, nested_context))
            return flattened
        if isinstance(value, (list, tuple, set, frozenset)):
            return [text for item in value for text in flatten(item, context)]
        return [f"{context} {value}".strip()]

    inclusion_terms = (
        "included",
        "inclusive",
        "complimentary",
        "covered",
        "free",
        "bao gom",
        "mien phi",
        "kem theo",
    )
    aliases = {
        "breakfast": ("breakfast", "bua sang"),
        "lunch": ("lunch", "bua trua"),
        "dinner": ("dinner", "bua toi", "evening meal"),
    }
    exclusion_terms = (
        "not included",
        "not free",
        "excluded",
        "additional charge",
        "extra charge",
        "surcharge",
        "khong bao gom",
        "khong mien phi",
        "co tinh phi",
        "phu thu",
    )
    covered: set[str] = set()
    for text in flatten(hotel_details):
        normalized = _normalize(text)
        if any(term in normalized for term in exclusion_terms):
            continue
        if any(term in normalized for term in ("all inclusive", "full board", "all meals included")):
            covered.update(aliases)
            continue
        if not any(term in normalized for term in inclusion_terms):
            continue
        for meal, meal_aliases in aliases.items():
            if any(alias in normalized for alias in meal_aliases):
                covered.add(meal)
    return frozenset(covered)


def fits_opening_hours(candidate: PlaceCandidate, start_time: str, duration_minutes: int) -> bool:
    if not candidate.opening_time or not candidate.closing_time:
        return True
    start = _time_to_minutes(start_time)
    end = start + duration_minutes
    opening = _time_to_minutes(candidate.opening_time)
    closing = _time_to_minutes(candidate.closing_time)
    if closing >= opening:
        return start >= opening and end <= closing
    return start >= opening or end <= closing


def estimated_travel_minutes(
    left: tuple[float, float] | None,
    right: tuple[float, float] | None,
    policy: PlanningPolicy,
) -> int:
    if not left or not right:
        return policy.minimum_travel_minutes
    distance = haversine_distance_km(left, right)
    raw_minutes = math.ceil((distance / policy.urban_speed_kmh) * 60 / 5) * 5
    return max(policy.minimum_travel_minutes, raw_minutes)


def _theme_title_from_query(query: str) -> str:
    normalized = _normalize(query)
    if any(term in normalized for term in ("beach", "coast", "sea")):
        return "Biển và thư giãn"
    if any(term in normalized for term in ("museum", "cultur", "heritage", "history", "pagoda")):
        return "Văn hóa và di sản"
    if any(term in normalized for term in ("food", "drink", "cuisine", "restaurant", "culinary")):
        return "Ẩm thực địa phương"
    if any(term in normalized for term in ("nature", "outdoor", "adventure", "scenic", "hiking")):
        return "Thiên nhiên và khám phá"
    if any(term in normalized for term in ("relax", "wellness", "leisure")):
        return "Thư giãn và nhịp sống địa phương"
    if any(term in normalized for term in ("market", "shopping", "entertainment", "nightlife", "city")):
        return "Khám phá thành phố và giải trí"
    return "Khám phá điểm đến địa phương"


def normalize_day_themes(
    raw_themes: Sequence[dict[str, Any]],
    number_of_days: int,
    preferences: Sequence[str] | None = None,
) -> list[DayTheme]:
    by_day: dict[int, DayTheme] = {}
    used: set[str] = set()
    for raw in raw_themes:
        try:
            day_number = int(raw.get("day_number"))
        except (TypeError, ValueError):
            continue
        query = str(raw.get("query") or "").strip()
        title = _theme_title_from_query(query)
        key = title.casefold()
        if 1 <= day_number <= number_of_days and query:
            duplicate_count = sum(existing.title.startswith(title) for existing in by_day.values())
            if duplicate_count:
                title = f"{title} - khu vực {duplicate_count + 1}"
                key = title.casefold()
            by_day[day_number] = DayTheme(day_number, title, query)
            used.add(key)

    fallback_pairs: list[tuple[str, str]] = []
    for preference in preferences or []:
        clean = str(preference).strip()
        if clean:
            fallback_pairs.append((f"Trải nghiệm {clean}", clean))
    fallback_pairs.extend(
        [
            ("Di sản và văn hóa", "museums culture heritage"),
            ("Thiên nhiên và cảnh đẹp", "nature outdoor scenic"),
            ("Biển và thư giãn", "beach coast relaxation"),
            ("Ẩm thực và đời sống địa phương", "local food neighbourhood life"),
            ("Giải trí và điểm đến nổi bật", "entertainment famous attractions"),
            ("Chợ và nhịp sống thành phố", "markets city local life"),
        ]
    )
    fallback_index = 0
    for day_number in range(1, number_of_days + 1):
        if day_number in by_day:
            continue
        while True:
            title, query = fallback_pairs[fallback_index % len(fallback_pairs)]
            cycle = fallback_index // len(fallback_pairs)
            fallback_index += 1
            if cycle:
                title = f"{title} - khu vực {cycle + 1}"
                query = f"{query} different area {cycle + 1}"
            if title.casefold() not in used:
                break
        by_day[day_number] = DayTheme(day_number, title, query)
        used.add(title.casefold())
    return [by_day[day] for day in range(1, number_of_days + 1)]


def serialize_day_themes(themes: Sequence[DayTheme]) -> list[dict[str, Any]]:
    """Return the stable JSONB representation stored on an itinerary."""
    return [
        {
            "day_number": theme.day_number,
            "title": theme.title,
            "query": theme.query,
        }
        for theme in themes
    ]


def build_itinerary(
    hotel: PlaceCandidate,
    themes: Sequence[DayTheme],
    themed_candidates: dict[int, Sequence[PlaceCandidate]],
    restaurants: Sequence[PlaceCandidate],
    cafes: Sequence[PlaceCandidate],
    breakfasts: Sequence[PlaceCandidate] | None = None,
    dinners: Sequence[PlaceCandidate] | None = None,
    child_focused: bool = False,
    policy: PlanningPolicy | None = None,
) -> ItinerarySchedule:
    policy = policy or PlanningPolicy()
    if not hotel.id or not hotel.coordinate_pair:
        raise ValueError("A real hotel with coordinates is required to build an itinerary.")

    used_ids: set[str] = set()
    playground_trip_count = 0
    all_items: list[ScheduledItem] = []
    adjustments: list[str] = []
    restaurants = [candidate for candidate in restaurants if _is_food(candidate)]
    cafes = [candidate for candidate in cafes if _is_food(candidate)]
    breakfasts = [candidate for candidate in (breakfasts or []) if _is_food(candidate)]
    dinners = [candidate for candidate in (dinners or []) if _is_food(candidate)]

    for theme in themes:
        day_playgrounds = 0
        day_pool = [candidate for candidate in themed_candidates.get(theme.day_number, []) if candidate.id]
        attraction_pool = [candidate for candidate in day_pool if not _is_food(candidate)]

        day_items: list[ScheduledItem] = []

        breakfast_covered = "breakfast" in hotel.covered_meals
        breakfast_candidate = None
        if not breakfast_covered:
            breakfast_candidate = _select_candidate(
                breakfasts,
                used_ids,
                hotel,
                anchor=hotel,
                start_time="07:00:00",
                kind="breakfast",
                policy=policy,
            )
        if breakfast_covered:
            breakfast_item = _hotel_item(theme.day_number, 1, hotel, "breakfast", "07:00:00", 60)
            adjustments.append(
                f"Ngày {theme.day_number}: bữa sáng đã được khách sạn bao gồm."
            )
        elif breakfast_candidate:
            breakfast_item = ScheduledItem.from_candidate(
                theme.day_number, 1, breakfast_candidate, "breakfast", "07:00:00"
            )
            used_ids.add(breakfast_candidate.id)
        else:
            breakfast_item = _hotel_item(theme.day_number, 1, hotel, "breakfast", "07:00:00", 60)
            adjustments.append(
                f"Ngày {theme.day_number}: không có điểm ăn sáng mở cửa phù hợp, dùng bữa tại khách sạn."
            )
        day_items.append(breakfast_item)

        morning_start = max(8 * 60 + 15, _time_to_minutes(breakfast_item.end_time))
        morning = _select_candidate(
            attraction_pool,
            used_ids,
            hotel,
            anchor=None,
            start_time=_minutes_to_time(morning_start),
            kind="attraction",
            policy=policy,
            playground_trip_count=playground_trip_count,
            playground_day_count=day_playgrounds,
            child_focused=child_focused,
        )
        if morning:
            morning_start = _next_start(breakfast_item, morning.coordinate_pair, morning_start, policy)
            if not fits_opening_hours(
                morning,
                _minutes_to_time(morning_start),
                default_duration_minutes(morning, "attraction"),
            ):
                morning = None
        if morning:
            morning_item = ScheduledItem.from_candidate(
                theme.day_number, 2, morning, "attraction", _minutes_to_time(morning_start)
            )
            day_items.append(morning_item)
            used_ids.add(morning.id)
            if morning_item.is_playground:
                playground_trip_count += 1
                day_playgrounds += 1
        else:
            morning_item = _hotel_item(
                theme.day_number, 2, hotel, "rest", _minutes_to_time(morning_start), 90
            )
            day_items.append(morning_item)
            adjustments.append(f"Ngày {theme.day_number}: không có điểm sáng hợp lệ, chuyển thành nghỉ tại khách sạn.")

        lunch_start = _next_start(
            day_items[-1],
            hotel.coordinate_pair,
            _time_to_minutes(policy.lunch_preferred_time),
            policy,
        )
        lunch_start = min(
            max(lunch_start, _time_to_minutes(policy.lunch_window_start)),
            _time_to_minutes(policy.lunch_window_end),
        )
        lunch_covered = "lunch" in hotel.covered_meals
        lunch_candidate = None
        if not lunch_covered:
            lunch_candidate = _select_candidate(
                restaurants,
                used_ids,
                hotel,
                anchor=morning or hotel,
                start_time=_minutes_to_time(lunch_start),
                kind="lunch",
                policy=policy,
            )
        if lunch_candidate:
            lunch_start = _next_start(day_items[-1], lunch_candidate.coordinate_pair, lunch_start, policy)
            if not fits_opening_hours(
                lunch_candidate,
                _minutes_to_time(lunch_start),
                default_duration_minutes(lunch_candidate, "lunch"),
            ):
                lunch_candidate = None
        if lunch_covered:
            lunch_item = _hotel_item(
                theme.day_number,
                3,
                hotel,
                "lunch",
                _minutes_to_time(_next_start(day_items[-1], hotel.coordinate_pair, lunch_start, policy)),
                75,
            )
            adjustments.append(f"Ngày {theme.day_number}: bữa trưa đã được khách sạn bao gồm.")
        elif lunch_candidate:
            lunch_item = ScheduledItem.from_candidate(
                theme.day_number, 3, lunch_candidate, "lunch", _minutes_to_time(lunch_start)
            )
            used_ids.add(lunch_candidate.id)
        else:
            lunch_item = _hotel_item(
                theme.day_number,
                3,
                hotel,
                "lunch",
                _minutes_to_time(_next_start(day_items[-1], hotel.coordinate_pair, lunch_start, policy)),
                75,
            )
            adjustments.append(f"Ngày {theme.day_number}: không có nhà hàng hợp lệ, dùng bữa tại khách sạn.")
        day_items.append(lunch_item)

        rest_start = _next_start(day_items[-1], hotel.coordinate_pair, 13 * 60, policy)
        rest_item = _hotel_item(theme.day_number, 4, hotel, "rest", _minutes_to_time(rest_start), 90)
        day_items.append(rest_item)

        afternoon_start = max(15 * 60 + 30, _time_to_minutes(rest_item.end_time))
        afternoon = _select_candidate(
            attraction_pool,
            used_ids,
            hotel,
            anchor=morning,
            start_time=_minutes_to_time(afternoon_start),
            kind="attraction",
            policy=policy,
            playground_trip_count=playground_trip_count,
            playground_day_count=day_playgrounds,
            child_focused=child_focused,
        )
        if afternoon:
            afternoon_start = _next_start(rest_item, afternoon.coordinate_pair, afternoon_start, policy)
            if not fits_opening_hours(
                afternoon,
                _minutes_to_time(afternoon_start),
                default_duration_minutes(afternoon, "attraction"),
            ):
                afternoon = None
        if afternoon:
            afternoon_item = ScheduledItem.from_candidate(
                theme.day_number, 5, afternoon, "attraction", _minutes_to_time(afternoon_start)
            )
            used_ids.add(afternoon.id)
            if afternoon_item.is_playground:
                playground_trip_count += 1
                day_playgrounds += 1
        else:
            afternoon_item = _hotel_item(
                theme.day_number, 5, hotel, "rest", _minutes_to_time(afternoon_start), 90
            )
            adjustments.append(f"Ngày {theme.day_number}: không có điểm chiều đủ gần, chuyển thành nghỉ tại khách sạn.")
        day_items.append(afternoon_item)

        coffee_start = max(17 * 60 + 45, _time_to_minutes(afternoon_item.end_time))
        coffee_candidate = _select_candidate(
            cafes,
            used_ids,
            hotel,
            anchor=afternoon or morning or hotel,
            start_time=_minutes_to_time(coffee_start),
            kind="coffee",
            policy=policy,
        )
        if coffee_candidate:
            coffee_start = _next_start(afternoon_item, coffee_candidate.coordinate_pair, coffee_start, policy)
            if not fits_opening_hours(
                coffee_candidate,
                _minutes_to_time(coffee_start),
                default_duration_minutes(coffee_candidate, "coffee"),
            ):
                coffee_candidate = None
        if coffee_candidate:
            coffee_item = ScheduledItem.from_candidate(
                theme.day_number, 6, coffee_candidate, "coffee", _minutes_to_time(coffee_start)
            )
            used_ids.add(coffee_candidate.id)
        else:
            coffee_item = _hotel_item(
                theme.day_number,
                6,
                hotel,
                "coffee",
                _minutes_to_time(_next_start(afternoon_item, hotel.coordinate_pair, coffee_start, policy)),
                45,
            )
            adjustments.append(f"Ngày {theme.day_number}: không có quán cà phê hợp lệ, chuyển thành nghỉ tại khách sạn.")
        day_items.append(coffee_item)

        dinner_start = max(18 * 60 + 45, _time_to_minutes(coffee_item.end_time))
        dinner_covered = "dinner" in hotel.covered_meals
        dinner_candidate = None
        if not dinner_covered:
            dinner_candidate = _select_candidate(
                dinners,
                used_ids,
                hotel,
                anchor=afternoon or morning or hotel,
                start_time=_minutes_to_time(dinner_start),
                kind="dinner",
                policy=policy,
            )
        if dinner_candidate:
            dinner_start = _next_start(coffee_item, dinner_candidate.coordinate_pair, dinner_start, policy)
            if not fits_opening_hours(
                dinner_candidate,
                _minutes_to_time(dinner_start),
                default_duration_minutes(dinner_candidate, "dinner"),
            ):
                dinner_candidate = None
        if dinner_covered:
            dinner_item = _hotel_item(
                theme.day_number,
                7,
                hotel,
                "dinner",
                _minutes_to_time(_next_start(coffee_item, hotel.coordinate_pair, dinner_start, policy)),
                75,
            )
            adjustments.append(f"Ngày {theme.day_number}: bữa tối đã được khách sạn bao gồm.")
        elif dinner_candidate:
            dinner_item = ScheduledItem.from_candidate(
                theme.day_number, 7, dinner_candidate, "dinner", _minutes_to_time(dinner_start)
            )
            used_ids.add(dinner_candidate.id)
        else:
            dinner_item = _hotel_item(
                theme.day_number,
                7,
                hotel,
                "dinner",
                _minutes_to_time(_next_start(coffee_item, hotel.coordinate_pair, dinner_start, policy)),
                75,
            )
            adjustments.append(
                f"Ngày {theme.day_number}: không có điểm ăn tối mở cửa phù hợp, dùng bữa tại khách sạn."
            )
        day_items.append(dinner_item)

        evening_start = max(20 * 60 + 15, _time_to_minutes(dinner_item.end_time))
        evening = _select_candidate(
            attraction_pool,
            used_ids,
            hotel,
            anchor=afternoon or morning,
            start_time=_minutes_to_time(evening_start),
            kind="evening",
            policy=policy,
            playground_trip_count=playground_trip_count,
            playground_day_count=day_playgrounds,
            child_focused=child_focused,
        )
        if evening and evening_start <= 20 * 60 + 30:
            duration = min(default_duration_minutes(evening, "evening"), 90)
            evening_start = _next_start(dinner_item, evening.coordinate_pair, evening_start, policy)
            if fits_opening_hours(evening, _minutes_to_time(evening_start), duration):
                evening_item = ScheduledItem.from_candidate(
                    theme.day_number, 8, evening, "evening", _minutes_to_time(evening_start), duration
                )
                day_items.append(evening_item)
                used_ids.add(evening.id)
                if evening_item.is_playground:
                    playground_trip_count += 1

        repaired, day_adjustments = validate_or_repair_day(
            day_items,
            hotel,
            policy,
            child_focused=child_focused,
            playground_allowance=(
                policy.playgrounds_per_child_focused_day if child_focused else policy.playgrounds_per_trip
            ),
        )
        all_items.extend(repaired)
        adjustments.extend(day_adjustments)

    return ItinerarySchedule(list(themes), all_items, adjustments)


def validate_or_repair_day(
    items: Sequence[ScheduledItem],
    hotel: PlaceCandidate,
    policy: PlanningPolicy | None = None,
    *,
    child_focused: bool = False,
    playground_allowance: int | None = None,
) -> tuple[list[ScheduledItem], list[str]]:
    policy = policy or PlanningPolicy()
    allowance = playground_allowance
    if allowance is None:
        allowance = (
            policy.playgrounds_per_child_focused_day if child_focused else policy.playgrounds_per_trip
        )
    adjustments: list[str] = []
    kept: list[ScheduledItem] = []
    playgrounds = 0
    for item in items:
        if item.is_playground:
            if playgrounds >= allowance:
                adjustments.append(f"Đã bỏ khu vui chơi trẻ em vượt giới hạn: {item.place_name}.")
                continue
            playgrounds += 1
        kept.append(item)

    normalized: list[ScheduledItem] = []
    for item in sorted(kept, key=lambda current: current.start_time):
        start = _time_to_minutes(item.start_time)
        if _is_beach_text(f"{item.place_name} {item.category}"):
            cutoff = _time_to_minutes(policy.beach_morning_cutoff)
            afternoon = _time_to_minutes(policy.beach_afternoon_start)
            if cutoff <= start < afternoon:
                start = afternoon
                adjustments.append(f"Đã chuyển hoạt động biển {item.place_name} ra khỏi khung giờ giữa trưa.")
        if normalized:
            previous = normalized[-1]
            earliest = _time_to_minutes(previous.end_time) + estimated_travel_minutes(
                previous.coordinates, item.coordinates, policy
            )
            if start < earliest:
                start = earliest
                adjustments.append(f"Đã dời {item.place_name} để tránh trùng giờ và dành thời gian di chuyển.")
        scheduled_item = item
        candidate = PlaceCandidate(
            id=item.reference_id,
            name=item.place_name,
            category=item.category,
            coordinates=item.coordinates,
            opening_time=item.opening_time,
            closing_time=item.closing_time,
        )
        if not fits_opening_hours(candidate, _minutes_to_time(start), item.duration_minutes):
            shifted_to_opening = False
            if item.opening_time:
                opening = _time_to_minutes(item.opening_time)
                if opening > start and fits_opening_hours(candidate, item.opening_time, item.duration_minutes):
                    start = opening
                    shifted_to_opening = True
                    adjustments.append(f"Đã dời {item.place_name} sang thời điểm mở cửa.")
            if not shifted_to_opening:
                fallback_kind: ItemKind = (
                    item.kind
                    if item.kind in {"breakfast", "lunch", "coffee", "dinner"}
                    else "rest"
                )
                fallback_duration = item.duration_minutes if fallback_kind != "rest" else 90
                if normalized:
                    previous = normalized[-1]
                    start = max(
                        start,
                        _time_to_minutes(previous.end_time)
                        + estimated_travel_minutes(previous.coordinates, hotel.coordinate_pair, policy),
                    )
                scheduled_item = ScheduledItem.from_candidate(
                    item.day_number,
                    item.order_index,
                    hotel,
                    fallback_kind,
                    _minutes_to_time(start),
                    fallback_duration,
                )
                adjustments.append(
                    f"Đã thay {item.place_name} bằng thời gian tại khách sạn vì giờ mở cửa không phù hợp."
                )
        normalized.append(
            replace(
                scheduled_item,
                order_index=len(normalized) + 1,
                start_time=_minutes_to_time(start),
                end_time=_minutes_to_time(start + scheduled_item.duration_minutes),
            )
        )
    return normalized, adjustments


def is_playground(candidate: PlaceCandidate) -> bool:
    normalized = _normalize(f"{candidate.name} {candidate.description or ''}")
    return any(
        term in normalized
        for term in ("playground", "kids play", "children play", "khu vui choi tre em", "san choi tre em")
    )


def _select_candidate(
    candidates: Sequence[PlaceCandidate],
    used_ids: set[str],
    hotel: PlaceCandidate,
    anchor: PlaceCandidate | None,
    start_time: str,
    kind: ItemKind,
    policy: PlanningPolicy,
    playground_trip_count: int = 0,
    playground_day_count: int = 0,
    child_focused: bool = False,
) -> PlaceCandidate | None:
    eligible: list[PlaceCandidate] = []
    for candidate in candidates:
        if not candidate.id or candidate.id in used_ids or not candidate.coordinate_pair:
            continue
        duration = default_duration_minutes(candidate, kind)
        if not fits_opening_hours(candidate, start_time, duration):
            continue
        if _is_beach_text(f"{candidate.name} {candidate.category}"):
            start = _time_to_minutes(start_time)
            if _time_to_minutes(policy.beach_morning_cutoff) <= start < _time_to_minutes(
                policy.beach_afternoon_start
            ):
                continue
        if is_playground(candidate):
            if child_focused and playground_day_count >= policy.playgrounds_per_child_focused_day:
                continue
            if not child_focused and playground_trip_count >= policy.playgrounds_per_trip:
                continue
        eligible.append(candidate)
    if not eligible:
        return None

    anchor_coords = anchor.coordinate_pair if anchor else None
    if anchor_coords:
        clustered: list[PlaceCandidate] = []
        for radius in policy.cluster_radii_km:
            clustered = [
                candidate
                for candidate in eligible
                if haversine_distance_km(anchor_coords, candidate.coordinate_pair) <= radius
            ]
            if clustered:
                eligible = clustered
                break
        if not clustered:
            return None
    return max(eligible, key=lambda candidate: _candidate_score(candidate, hotel, anchor, policy))


def _candidate_score(
    candidate: PlaceCandidate,
    hotel: PlaceCandidate,
    anchor: PlaceCandidate | None,
    policy: PlanningPolicy,
) -> float:
    hotel_distance = haversine_distance_km(hotel.coordinate_pair, candidate.coordinate_pair)
    hotel_score = _distance_score(hotel_distance, policy.distance_score_limit_km)
    rating_score = max(0.0, min(float(candidate.rating or 0.0) / 5.0, 1.0))
    similarity = max(0.0, min(candidate.similarity, 1.0))
    if anchor and anchor.coordinate_pair:
        anchor_distance = haversine_distance_km(anchor.coordinate_pair, candidate.coordinate_pair)
        return (
            0.45 * similarity
            + 0.35 * _distance_score(anchor_distance, policy.cluster_radii_km[0])
            + 0.10 * hotel_score
            + 0.10 * rating_score
        )
    hours_score = 1.0 if candidate.opening_time and candidate.closing_time else 0.0
    return 0.60 * similarity + 0.25 * hotel_score + 0.10 * rating_score + 0.05 * hours_score


def _distance_score(distance_km: float, limit_km: float) -> float:
    return max(0.0, 1.0 - distance_km / limit_km)


def _next_start(
    previous: ScheduledItem,
    next_coordinates: tuple[float, float] | None,
    preferred_minutes: int,
    policy: PlanningPolicy,
) -> int:
    travel = estimated_travel_minutes(previous.coordinates, next_coordinates, policy)
    return max(preferred_minutes, _time_to_minutes(previous.end_time) + travel)


def _hotel_item(
    day_number: int,
    order_index: int,
    hotel: PlaceCandidate,
    kind: ItemKind,
    start_time: str,
    duration_minutes: int,
) -> ScheduledItem:
    return ScheduledItem.from_candidate(day_number, order_index, hotel, kind, start_time, duration_minutes)


def _activity_label(candidate: PlaceCandidate, kind: ItemKind) -> str:
    if kind == "breakfast":
        if kind in candidate.covered_meals:
            return f"Ăn sáng đã bao gồm tại {candidate.name}"
        return f"Ăn sáng tại {candidate.name}"
    if kind == "lunch":
        if kind in candidate.covered_meals:
            return f"Ăn trưa đã bao gồm và nghỉ ngơi tại {candidate.name}"
        return (
            f"Ăn trưa tại {candidate.name}"
            if candidate.category.casefold() != "hotel"
            else f"Ăn trưa và nghỉ ngơi tại {candidate.name}"
        )
    if kind == "coffee":
        return (
            f"Thư giãn tại {candidate.name}"
            if candidate.category.casefold() != "hotel"
            else f"Nghỉ ngơi tại {candidate.name}"
        )
    if kind == "dinner":
        if kind in candidate.covered_meals:
            return f"Ăn tối đã bao gồm tại {candidate.name}"
        return f"Ăn tối tại {candidate.name}"
    if kind == "rest":
        return f"Nghỉ ngơi tại {candidate.name}"
    if kind == "evening":
        return f"Dạo chơi tại {candidate.name}"
    return f"Tham quan {candidate.name}"


def _is_food(candidate: PlaceCandidate) -> bool:
    normalized = _normalize(f"{candidate.category} {candidate.name}")
    return any(term in normalized for term in ("restaurant", "cafe", "coffee", "food", "drink"))


def _is_beach_text(value: str) -> bool:
    normalized = _normalize(value)
    return any(term in normalized for term in ("beach", "bai bien", "tam bien"))


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def _time_to_minutes(value: str) -> int:
    hour_text, minute_text, *_ = value.split(":")
    return int(hour_text) * 60 + int(minute_text)


def _minutes_to_time(minutes: int) -> str:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:00"
