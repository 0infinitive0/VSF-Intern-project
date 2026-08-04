"""Text and payload formatting for trip plans and hotel option lists.

Pure functions only — no file I/O, no agent wiring. `format_trip_response_from_json`
and `format_hotel_options` render the chat-text shown to the user; `to_trip_plan_payload`
and `to_hotel_options_payload` render the structured JSON Phase 3's API returns.
"""

from __future__ import annotations

from typing import Any

from src.i18n import t
from src.services.trip_scheduler import PlaceCandidate, normalize_day_themes


def parse_duration_to_days(duration_str: str) -> int:
    """Parse Vietnamese duration string (e.g. '1 tuần', '2 ngày', '1 tháng', 'một tuần') into integer days."""
    if not duration_str:
        return 3

    s = duration_str.lower().strip()

    if "tuần" in s or "tuan" in s:
        if "hai" in s or "2" in s:
            return 14
        if "ba" in s or "3" in s:
            return 21
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0:
            return digits[0] * 7
        return 7

    if "tháng" in s or "thang" in s:
        if "hai" in s or "2" in s:
            return 60
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0:
            return digits[0] * 30
        return 30

    if "ngày" in s or "ngay" in s:
        if "một" in s or "mot" in s:
            return 1
        if "hai" in s:
            return 2
        if "ba" in s:
            return 3
        if "bốn" in s or "bon" in s:
            return 4
        if "năm" in s or "nam" in s:
            return 5
        digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
        if digits and digits[0] > 0:
            return digits[0]

    digits = [int(word) for word in s.replace("-", " ").split() if word.isdigit()]
    if digits and digits[0] > 0:
        return digits[0]

    return 3


def build_natural_activity_string(name: str, category: str = "") -> str:
    """Format activity text naturally in Vietnamese based on attraction name and category."""
    if not name:
        return "Tham quan điểm du lịch"

    s = name.strip()
    s_lower = s.lower()
    cat_lower = (category or "").lower()

    for verb in ["tham quan", "trải nghiệm", "vui chơi", "thưởng thức", "khám phá", "ghé", "dạo"]:
        if s_lower.startswith(verb):
            return s

    if any(k in s_lower for k in ["lặn biển", "tắm biển", "chèo sup", "tour", "camp", "diving", "surfing", "chèo thuyền"]):
        return f"Trải nghiệm {s}"
    elif any(k in s_lower for k in ["coffee", "cà phê", "quán", "nhà hàng", "quán ăn", "ẩm thực"]) or "food" in cat_lower or "drink" in cat_lower:
        return f"Ghé {s}"
    elif any(k in s_lower for k in ["chợ", "phố"]):
        return f"Dạo {s}"
    elif any(k in s_lower for k in ["đảo", "vịnh", "núi", "hang"]):
        return f"Khám phá {s}"
    else:
        return f"Tham quan {s}"


def format_trip_response_from_json(trip_data: dict[str, Any], language: str = "vi") -> str:
    """Format structured trip JSON into concise user text response."""
    hotel = trip_data.get("hotel", {})
    itineraries = trip_data.get("itineraries", [])
    if isinstance(itineraries, dict):
        itineraries = [itineraries]
    itinerary_items = trip_data.get("itinerary_items", [])

    output = []

    hotel_name = hotel.get("name", t("Khách sạn chưa xác định", language))
    star_rating = hotel.get("star_rating")
    stars_str = t(" ({star_rating} sao)", language, star_rating=star_rating) if star_rating else ""
    description = hotel.get("description", "")

    matched_rooms = (hotel.get("matched_rooms") or hotel.get("matched_room_names") or [])[:2]
    rooms_str = (
        t(" | Phòng gợi ý: {rooms}", language, rooms=", ".join(matched_rooms)) if matched_rooms else ""
    )

    output.append(f"Hotel: {hotel_name}{stars_str}{rooms_str}")
    if description:
        output.append(t("Tóm tắt: {description}", language, description=description))
    output.append("------")

    day_themes: dict[int, str] = {}
    stored_day_themes = []
    if itineraries and isinstance(itineraries[0], dict):
        stored_day_themes = itineraries[0].get("day_themes", [])
    raw_day_themes = [theme for theme in (stored_day_themes or []) if isinstance(theme, dict)]
    if any(theme.get("query") for theme in raw_day_themes):
        theme_day_numbers = [
            int(theme["day_number"])
            for theme in raw_day_themes
            if str(theme.get("day_number") or "").isdigit()
        ]
        normalized_themes = normalize_day_themes(
            raw_day_themes,
            max(theme_day_numbers, default=1),
        )
        for theme in normalized_themes:
            day_themes[theme.day_number] = theme.title
    for theme in raw_day_themes:
        if theme.get("query"):
            continue
        if isinstance(theme, dict) and theme.get("day_number") and theme.get("title"):
            day_themes[int(theme["day_number"])] = str(theme["title"])
    for itin in itineraries:
        if isinstance(itin, dict):
            d_num = itin.get("day_number", 1)
            title = itin.get("title") or itin.get("description")
            if title:
                day_themes[d_num] = title

    items_by_day: dict[int, list[dict[str, Any]]] = {}
    for item in itinerary_items:
        day = item.get("day_number") or item.get("day", 1)
        if day not in items_by_day:
            items_by_day[day] = []
        items_by_day[day].append(item)

    duration_days = len(itineraries) if itineraries and len(itineraries) > 1 else 1
    if itineraries and isinstance(itineraries[0], dict) and "duration_days" in itineraries[0]:
        duration_days = itineraries[0].get("duration_days", 1)

    max_days = max(duration_days, max(items_by_day.keys()) if items_by_day else 1)

    for day_num in range(1, max_days + 1):
        theme_suffix = f" - {day_themes[day_num]}" if day_num in day_themes else ""
        output.append(t("Ngày {day_num}{theme_suffix}:", language, day_num=day_num, theme_suffix=theme_suffix))

        day_items = sorted(items_by_day.get(day_num, []), key=lambda x: x.get("order_index", 1))
        if day_items:
            for item in day_items:
                start_time = item.get("start_time") or item.get("time", "08:00:00")
                end_time = item.get("end_time")
                start_text = start_time[:5] if len(start_time) >= 5 else start_time
                end_text = end_time[:5] if isinstance(end_time, str) and len(end_time) >= 5 else None
                time_str = f"{start_text}-{end_text}" if end_text else start_text
                activity = item.get("activity") or item.get("name") or t("Tham quan điểm du lịch", language)
                output.append(f"{time_str} - {activity}")
        else:
            output.append(t("Chưa có hoạt động hợp lệ cho ngày này.", language))
        output.append("------")

    adjustments = [str(value) for value in trip_data.get("adjustments", []) if value]
    if adjustments:
        output.append(t("Điều chỉnh tự động:", language))
        output.extend(f"- {adjustment}" for adjustment in adjustments)

    return "\n".join(output)


def format_hotel_options(options: list[tuple[dict[str, Any], PlaceCandidate]], language: str = "vi") -> str:
    """Render a ranked hotel candidate list as numbered Vietnamese chat text."""
    if not options:
        return t(
            "Không tìm thấy khách sạn phù hợp. Bạn thử mô tả khác hoặc đổi điểm đến xem sao.",
            language,
        )

<<<<<<< Updated upstream:backend/src/services/trip_formatter.py
    lines = ["Mình đã tìm được danh sách khách sạn phù hợp. Bạn xem và chọn trực tiếp khách sạn mong muốn trong tab Khách sạn để tạo lịch trình nhé!", "------"]
=======
    lines = [
        t("Mình tìm được vài khách sạn phù hợp, bạn chọn giúp mình nhé:", language),
        "------",
    ]
>>>>>>> Stashed changes:src/services/trip_formatter.py
    for data, _candidate in options:
        rank = data.get("rank", "?")
        name = data.get("name") or t("Khách sạn chưa xác định", language)
        star_rating = data.get("star_rating")
        stars_str = t(" ({star_rating} sao)", language, star_rating=star_rating) if star_rating else ""

        review_score = data.get("review_score")
        review_count = data.get("review_count")
        review_str = ""
        if review_score:
            review_str = t(" | Đánh giá: {review_score}/10", language, review_score=review_score)
            if review_count:
                review_str += t(" ({review_count} lượt)", language, review_count=review_count)

        average_nightly_price = data.get("average_nightly_price")
        total_stay_price = data.get("total_stay_price")
        stay_night_count = data.get("stay_night_count")
        lowest_price = data.get("lowest_price")
        price_str = ""
        if average_nightly_price is not None:
            currency = data.get("currency") or "VND"
            try:
                price_str = t(
                    " | {price:,.0f} {currency}/đêm",
                    language,
                    price=float(average_nightly_price),
                    currency=currency,
                )
                if total_stay_price is not None and stay_night_count:
                    price_str += t(
                        " · Tổng {nights} đêm: {total:,.0f} {currency}",
                        language,
                        nights=int(stay_night_count),
                        total=float(total_stay_price),
                        currency=currency,
                    )
            except (TypeError, ValueError):
                price_str = t(
                    " | {price} {currency}/đêm",
                    language,
                    price=average_nightly_price,
                    currency=currency,
                )
        elif lowest_price is not None:
            currency = data.get("currency") or "VND"
            try:
                price_str = t(
                    " | Giá từ: {price:,.0f} {currency}",
                    language,
                    price=float(lowest_price),
                    currency=currency,
                )
            except (TypeError, ValueError):
                price_str = t(
                    " | Giá từ: {price} {currency}",
                    language,
                    price=lowest_price,
                    currency=currency,
                )

        lines.append(f"{rank}. {name}{stars_str}{review_str}{price_str}")

        description = data.get("description")
        if description:
            lines.append(f"   {description}")

        matched_rooms = (data.get("matched_rooms") or [])[:2]
        if matched_rooms:
            lines.append(t("   Phòng gợi ý: {rooms}", language, rooms=", ".join(matched_rooms)))

        covered_meals = data.get("covered_meals") or []
        if covered_meals:
            lines.append(t("   Bữa ăn đã bao gồm: {meals}", language, meals=", ".join(covered_meals)))

        lines.append("------")

<<<<<<< Updated upstream:backend/src/services/trip_formatter.py
    lines.append("Bạn hãy nhấn nút 'Chọn khách sạn này' ở tab Khách sạn để tiếp tục tạo lịch trình.")
=======
    lines.append(t("Trả lời bằng số thứ tự hoặc tên khách sạn để chọn.", language))
>>>>>>> Stashed changes:src/services/trip_formatter.py
    return "\n".join(lines)


def to_trip_plan_payload(trip_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Render a `current_trip_plan.json`-shaped bundle into Phase 3's `trip_plan` payload.

    Returns None for an empty/missing bundle so callers can pass it straight through
    as the API's `trip_plan: null`.
    """
    if not trip_data:
        return None

    hotel = trip_data.get("hotel") or {}
    itineraries = trip_data.get("itineraries") or []
    if isinstance(itineraries, dict):
        itineraries = [itineraries]
    itinerary = itineraries[0] if itineraries and isinstance(itineraries[0], dict) else {}

    items_by_day: dict[int, list[dict[str, Any]]] = {}
    for item in trip_data.get("itinerary_items") or []:
        day_number = int(item.get("day_number") or 1)
        items_by_day.setdefault(day_number, []).append(item)

    day_theme_by_number = {
        int(theme["day_number"]): str(theme.get("title") or "")
        for theme in itinerary.get("day_themes") or []
        if isinstance(theme, dict) and str(theme.get("day_number") or "").isdigit()
    }

    duration_days = int(itinerary.get("duration_days") or (max(items_by_day.keys(), default=1)))

    days = []
    for day_number in range(1, duration_days + 1):
        day_items = sorted(
            items_by_day.get(day_number, []),
            key=lambda item: int(item.get("order_index") or 0),
        )
        days.append(
            {
                "day_number": day_number,
                "theme": day_theme_by_number.get(day_number, ""),
                "items": [
                    {
                        "order_index": int(item.get("order_index") or 0),
                        "start_time": item.get("start_time"),
                        "end_time": item.get("end_time"),
                        "activity": item.get("activity"),
                        "kind": item.get("item_kind") or item.get("kind"),
                        "reference_type": item.get("reference_type"),
                        "reference_id": item.get("reference_id"),
                        "coordinates": (
                            f"{item.get('coordinates')[0]},{item.get('coordinates')[1]}"
                            if isinstance(item.get("coordinates"), (list, tuple)) and len(item.get("coordinates")) == 2
                            else str(item.get("coordinates")) if item.get("coordinates") else None
                        ),
                    }
                    for item in day_items
                ],
            }
        )

    return {
        "status": itinerary.get("status") or "Draft",
        "destination": (itinerary.get("preferences") or [None])[0],
        "duration_days": duration_days,
        "start_date": itinerary.get("start_date"),
        "end_date": itinerary.get("end_date"),
        "number_of_adults": itinerary.get("number_of_adults"),
        "hotel": {
            "id": hotel.get("id"),
            "name": hotel.get("name"),
            "star_rating": hotel.get("star_rating"),
            "description": hotel.get("description"),
            "matched_rooms": hotel.get("matched_rooms") or hotel.get("matched_room_names") or [],
            "coordinates": hotel.get("coordinates"),
        },
        "days": days,
        "adjustments": [str(value) for value in trip_data.get("adjustments") or [] if value],
    }


def to_hotel_options_payload(
    pending_hotel_selection: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Render a `pending_hotel_selection.json`-shaped bundle into Phase 3's
    `hotel_options[]` payload. Empty list when nothing is pending."""
    if not pending_hotel_selection:
        return []

    options = []
    for index, option in enumerate(pending_hotel_selection.get("options") or [], start=1):
        if not isinstance(option, dict):
            continue
        payload = {
            "index": index,
            "id": option.get("id"),
            "name": option.get("name"),
            "star_rating": option.get("star_rating"),
            "description": option.get("description"),
            "matched_rooms": option.get("matched_rooms") or option.get("matched_room_names") or [],
        }
        for price_field in (
            "average_nightly_price",
            "total_stay_price",
            "stay_night_count",
            "currency",
        ):
            if option.get(price_field) is not None:
                payload[price_field] = option[price_field]
        options.append(payload)
    return options
