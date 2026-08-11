"""Pydantic models for the API layer.

Phase 3 additions:
- PlannerChatRequest.session_id typed as UUID (RT-6: safe for GET /chat which
  uses crypto.randomUUID()).
- PlannerChatResponse extended with session_id, stage, hotel_options, trip_plan,
  intake — all new fields are Optional so the existing /api/v1/chat page keeps
  working without changes (D10).
- Payload models: HotelOption, TripPlanPayload, DayPlan, ItineraryItem,
  IntakeStatus.
- Converter helpers: to_hotel_options_payload(), to_trip_plan_payload(),
  IntakeStatus.from_state() — live here so route handlers never re-implement
  serialisation logic.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from src.i18n import DEFAULT_LANGUAGE, t
from src.observability import log_sanitized_system_error

# ---------------------------------------------------------------------------
# Basic chat models (pre-Phase 3, unchanged)
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn từ user")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Phản hồi từ agent")
    analysis: str = Field(default="", description="Phân tích nội bộ")


class AttractionPayload(BaseModel):
    attraction_id: str = Field(..., description="UUID from PostgreSQL")
    name: str = Field(..., description="Tên điểm tham quan hoặc Tour")
    destination_id: str = Field(..., description="UUID trỏ về điểm đến")
    category: str = Field(..., description="Phân loại (e.g., Tour, Biển)")
    is_tour: bool = Field(default=False)
    ticket_price_range: str | None = Field(default=None, description="Mức giá")


class HotelPayload(BaseModel):
    hotel_id: str | int = Field(..., description="UUID từ bảng hotels")
    name: str = Field(..., description="Tên khách sạn")
    destination_id: str | None = Field(default=None, description="UUID trỏ về điểm đến")
    star_rating: float | None = Field(default=None, description="Hạng sao")
    price_tier: str | None = Field(default=None, description="Mức giá")
    amenities: list[str] | None = Field(default=None, description="Danh sách tiện ích")


class RoomPayload(BaseModel):
    room_id: str = Field(..., description="UUID từ bảng rooms")
    hotel_id: str | int = Field(..., description="UUID trỏ về bảng hotels")
    name: str = Field(..., description="Tên phòng")
    max_guests: int | None = Field(default=None, description="Số khách tối đa")
    room_size_sqm: float | None = Field(default=None, description="Diện tích phòng")
    view: str | None = Field(default=None, description="Hướng nhìn")


class RoomPricePayload(BaseModel):
    amount: float | None = None
    currency: str | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    sold_out: bool | None = None
    package_details: str | None = None


class RoomDetailPayload(BaseModel):
    id: str
    name: str
    bed_description: str | None = None
    room_size_sqm: float | None = None
    max_guests: int | None = None
    view: str | None = None
    room_facilities: list[str] | None = None
    images: list[str] | None = None
    price: RoomPricePayload | None = None


class HotelDetailPayload(BaseModel):
    id: str
    name: str
    star_rating: float | None = None
    description: str | None = None
    address: str | None = None
    city: str | None = None
    area_name: str | None = None
    location_highlight: str | None = None
    coordinates: str | None = None
    image_url: str | None = None
    images: list[str] | None = None
    amenities: list[str] | None = None
    amenity_groups: dict[str, Any] | None = None
    awards: list[str] | None = None
    warnings: list[str] | None = None
    review_score: float | None = None
    review_count: int | None = None
    category_scores: dict[str, Any] | None = None
    check_in_time: str | None = None
    check_in_until: str | None = None
    check_out_time: str | None = None
    reception_open_until: str | None = None
    nearby_attractions: Any | None = None
    nearby_essentials: Any | None = None
    lowest_price: float | None = None
    currency: str | None = None
    rooms: list[RoomDetailPayload] = Field(default_factory=list)


class AttractionDetailPayload(BaseModel):
    id: str
    name: str
    description: str | None = None
    category: str | None = None
    is_tour: bool | None = None
    estimated_duration_minutes: int | None = None
    opening_time: str | None = None
    closing_time: str | None = None
    ticket_price_adult: float | None = None
    ticket_price_child: float | None = None
    rating: float | None = None
    review_count: int | None = None
    coordinates: str | None = None
    images: list[str] | None = None


# ---------------------------------------------------------------------------
# Phase 3 payload models
# ---------------------------------------------------------------------------


class HotelOption(BaseModel):
    """One hotel in the pending selection list sent to the React UI.

    index is the 1-based ordinal that must equal suggestions[i].value (as int)
    for the same turn — they are two views of one list and must not disagree.
    """

    index: int = Field(..., description="Thứ tự 1-based; khớp với suggestions[i].value")
    id: str = Field(..., description="UUID khách sạn")
    name: str = Field(..., description="Tên khách sạn")
    star_rating: float | None = Field(default=None, description="Hạng sao")
    description: str | None = Field(default=None, description="Mô tả ngắn")
    matched_rooms: list[str] = Field(default_factory=list, description="Tên phòng phù hợp")
    average_nightly_price: float | None = Field(default=None, description="Giá trung bình mỗi đêm theo ngày ở")
    total_stay_price: float | None = Field(default=None, description="Tổng giá cho toàn bộ số đêm")
    stay_night_count: int | None = Field(default=None, description="Số đêm đã báo giá")
    currency: str | None = Field(default=None, description="Đơn vị tiền tệ của báo giá")
    coordinates: str | None = Field(default=None, description="Tọa độ lat,lng của khách sạn")
    address: str | None = None
    area_name: str | None = None
    image_url: str | None = None
    amenities: list[str] = Field(default_factory=list)
    display_amenities: list[str] = Field(
        default_factory=list,
        description="Tối đa bốn tiện ích nổi bật để hiển thị trên thẻ khách sạn",
    )
    review_score: float | None = None
    review_count: int | None = None
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    match_reasons: list[dict[str, float | str]] = Field(default_factory=list)
    city: str | None = None
    preferences: list[str] = Field(default_factory=list)


class RouteInfoPayload(BaseModel):
    distance_km: float
    duration_mins: float
    polyline: str
    profile: str | None = None

class ItineraryItem(BaseModel):
    order_index: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    activity: str | None = None
    kind: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    coordinates: str | None = None
    image_url: str | None = None
    route_to_next: RouteInfoPayload | None = None
    route_from_hotel: RouteInfoPayload | None = None


class DayPlan(BaseModel):
    day_number: int | None = None
    theme: str | None = None
    items: list[ItineraryItem] = Field(default_factory=list)


class TripPlanHotel(BaseModel):
    id: str | None = None
    name: str | None = None
    star_rating: float | None = None
    description: str | None = None
    matched_rooms: list[str] = Field(default_factory=list)
    coordinates: str | None = None
    image_url: str | None = None


class TripPlanPayload(BaseModel):
    """Phase 3 payload for the trip plan right panel."""

    status: str | None = None
    destination: str | None = None
    duration_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    number_of_adults: int | None = None
    budget: float | None = None
    budget_currency: str | None = None
    hotel: TripPlanHotel | None = None
    days: list[DayPlan] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)


class IntakeStatus(BaseModel):
    """Snapshot of what the intake gate has collected so far."""

    destination: str | None = None
    duration: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    people: str | None = None
    preferences: list[str] = Field(default_factory=list, description="Travel-style labels")
    companions: str | None = None
    pace: str | None = None
    day_rhythm: list[str] = Field(default_factory=list)
    notes: str = Field(default="", description="Free-text other needs")
    available_destinations: list[str] = Field(
        default_factory=list,
        description="Real destinations the intake picker may choose from",
    )
    budget_options: list[str] = Field(
        default_factory=list,
        description="Real budget/accommodation tier labels from hotel_selection",
    )
    min_price: float | None = None
    max_price: float | None = None
    missing: list[str] = Field(
        default_factory=list,
        description="Names of fields still needed: 'destination', 'people', 'start_date', 'end_date'",
    )

    @classmethod
    def from_state(cls, intake_state: Any, hotel_pref_state: Any = None) -> IntakeStatus:
        """Build from a TripIntakeState and optional HotelPreferenceState."""
        destination = getattr(intake_state, "destination", None)
        duration = getattr(intake_state, "duration", None)
        start_date = getattr(intake_state, "start_date", None)
        end_date = getattr(intake_state, "end_date", None)
        people = getattr(intake_state, "people", None)
        missing = [
            field
            for field, value in [
                ("destination", destination),
                ("duration", duration),
                ("start_date", start_date),
                ("people", people),
            ]
            if not value
        ]
        preferences = list(getattr(intake_state, "preferences", ()) or ())
        companions = getattr(intake_state, "companions", None)
        pace = getattr(intake_state, "pace", None)
        day_rhythm = list(getattr(intake_state, "day_rhythm", ()) or ())
        notes = getattr(intake_state, "notes", "") or ""
        min_price = getattr(hotel_pref_state, "min_price", None) if hotel_pref_state else None
        max_price = getattr(hotel_pref_state, "max_price", None) if hotel_pref_state else None
        return cls(
            destination=destination,
            duration=duration,
            start_date=start_date,
            end_date=end_date,
            people=people,
            preferences=preferences,
            companions=companions,
            pace=pace,
            day_rhythm=day_rhythm,
            notes=notes,
            available_destinations=_available_destination_names(),
            budget_options=_budget_tier_labels(),
            min_price=min_price,
            max_price=max_price,
            missing=missing,
        )


class SuggestionPayload(BaseModel):
    label: str = Field(..., description="Chữ hiển thị trên nút gợi ý")
    value: str = Field(..., description="Nội dung gửi đi khi bấm nút")


class StayDatesInput(BaseModel):
    """Date-range data emitted by the frontend control."""

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def end_date_must_follow_start_date(self) -> StayDatesInput:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


ChatStage = Literal["intake", "hotel_options", "planned", "modified", "finalized", "error"]


class PlannerChatRequest(BaseModel):
    session_id: UUID
    message: str | None = None
    stay_dates: StayDatesInput | None = None
    min_price: float | None = None
    max_price: float | None = None
    language: Literal["vi", "en"] = Field(
        DEFAULT_LANGUAGE, description="UI language for this turn's reply (vi | en)"
    )

    @model_validator(mode="after")
    def includes_message_or_stay_dates(self) -> PlannerChatRequest:
        if (
            not self.message
            and self.stay_dates is None
            and self.min_price is None
            and self.max_price is None
        ):
            raise ValueError(
                "Must specify at least one of message, stay_dates, min_price, or max_price."
            )
        return self


class SelectHotelRequest(BaseModel):
    session_id: UUID
    hotel_id: str | int
    selection_message: str | None = Field(default=None, min_length=1, max_length=5000)


class ChangeHotelRequest(BaseModel):
    session_id: UUID


class PreferencePayload(BaseModel):
    id: str
    label: str


class PlannerChatResponse(BaseModel):
    session_id: str
    reply: str
    suggestions: list[SuggestionPayload] = Field(default_factory=list)
    stage: ChatStage
    hotel_options: list[HotelOption] = Field(default_factory=list)
    trip_plan: TripPlanPayload | None = None
    intake: IntakeStatus | None = None
    requires_stay_dates: bool = False
    compound_min_price: float | None = None
    compound_max_price: float | None = None
    all_preferences: list[PreferencePayload] = Field(default_factory=list)
    active_preferences: list[PreferencePayload] = Field(default_factory=list)


class SessionSummaryPayload(BaseModel):
    session_id: str
    title: str | None = None
    destination: str | None = None
    duration_days: int | None = None
    status: Literal["draft", "completed"]
    created_at: str | None = None
    updated_at: str | None = None
    thumbnail_url: str | None = None


class SessionListPayload(BaseModel):
    sessions: list[SessionSummaryPayload] = Field(default_factory=list)
    page: int
    page_size: int
    has_more: bool


class RestoredMessagePayload(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    stage: str
    at: str


class SessionRestorePayload(BaseModel):
    session_id: str
    messages: list[RestoredMessagePayload] = Field(default_factory=list)
    suggestions: list[SuggestionPayload] = Field(default_factory=list)
    stage: str
    hotel_options: list[HotelOption] = Field(default_factory=list)
    trip_plan: TripPlanPayload | None = None
    intake: IntakeStatus | None = None


# ---------------------------------------------------------------------------
# Converters & Sanitizers
# ---------------------------------------------------------------------------


def _available_destination_names() -> list[str]:
    """Real, current destination list reused from the intake grounding source."""
    try:
        from src.services.trip_planner import _get_destination_names

        return [option.name for option in _get_destination_names() if option.name]
    except Exception:
        return []


def _budget_tier_labels() -> list[str]:
    """Real budget/accommodation tier labels, never a hardcoded copy."""
    try:
        from src.services.hotel_selection import budget_option_labels

        return list(budget_option_labels())
    except Exception:
        return []


_GENERIC_ERROR_MSG = "Đã xảy ra lỗi phía máy chủ. Vui lòng thử lại."

# Raw exception text must never reach the browser.  Any SYSTEM ERROR: string
# that is not one of the hand-written Vietnamese messages below is sanitised.
# Every entry here must be a static template (at most a validated, known-safe
# value like a destination name interpolated in) — never one that embeds a raw
# exception's `str(exc)`, which can carry Supabase table/column/connection info.
_SAFE_ERROR_PREFIXES = (
    "SYSTEM ERROR: Chưa có kế hoạch",
    "SYSTEM ERROR: Không thể hiểu",
    "SYSTEM ERROR: Mô hình hội thoại",
    "SYSTEM ERROR: Không nhận được",
    "SYSTEM ERROR: Không thể áp dụng",
    "SYSTEM ERROR: Cần có ngày bắt đầu",
    "SYSTEM ERROR: Ngày kết thúc phải sau",
    "SYSTEM ERROR: Không tìm thấy dữ liệu điểm đến",
    "SYSTEM ERROR: Không tìm thấy khách sạn có tọa độ hợp lệ",
    "SYSTEM ERROR: Không tìm thấy khách sạn với id",
    "SYSTEM ERROR: Chưa có danh sách khách sạn",
    "SYSTEM ERROR: Không còn kế hoạch chuyến đi",
    "SYSTEM ERROR: Thông tin thay đổi chuyến đi chưa đầy đủ",
    "SYSTEM ERROR: Không thể lưu danh sách khách sạn mới",
    "SYSTEM ERROR: Yêu cầu thay đổi thông tin chuyến đi không hợp lệ",
)


# English mirrors of the safe prefixes, so an "en" reply is matched (and
# passed through) in the language it was produced in. Each entry is a prefix
# of the corresponding English `t()` output for the same deterministic
# message — authoring both together keeps matching reliable.
_SAFE_ERROR_PREFIXES_EN = (
    "SYSTEM ERROR: There is no trip plan",
    "SYSTEM ERROR: There is no plan",
    "SYSTEM ERROR: Could not safely understand",
    "SYSTEM ERROR: The conversation model",
    "SYSTEM ERROR: No response was received",
    "SYSTEM ERROR: Could not apply",
    "SYSTEM ERROR: Valid start and end dates",
    "SYSTEM ERROR: The end date must be after",
    "SYSTEM ERROR: No destination data found",
    "SYSTEM ERROR: No hotel with valid coordinates",
    "SYSTEM ERROR: No hotel found with the given id",
    "SYSTEM ERROR: There is no hotel list",
    "SYSTEM ERROR: There is no longer a trip plan",
    "SYSTEM ERROR: Trip change information is incomplete",
    "SYSTEM ERROR: Could not save the new hotel list",
    "SYSTEM ERROR: The trip information change request is invalid",
)

_SAFE_ERROR_PREFIXES_BY_LANG: dict[str, tuple[str, ...]] = {
    "vi": _SAFE_ERROR_PREFIXES,
    "en": _SAFE_ERROR_PREFIXES_EN,
}


def sanitize_system_error(text: str, *, session_id: str | None = None, language: str = "vi") -> str:
    """Return a safe user-facing string for a SYSTEM ERROR: prefixed reply.

    If the message matches one of the hand-written strings (in the language it
    was produced in) it is returned as-is (it contains no internal detail).
    Any other SYSTEM ERROR: string — which may carry Supabase table names,
    column names, or connection strings — is replaced with a generic message
    localized to `language`, and the original is logged at error level here
    (keyed by session_id) so a sanitised reply is still debuggable from logs
    instead of requiring a live repro.
    """
    if not text.startswith("SYSTEM ERROR:"):
        return text
    prefixes = _SAFE_ERROR_PREFIXES_BY_LANG.get(language, _SAFE_ERROR_PREFIXES)
    for prefix in prefixes:
        if text.startswith(prefix):
            return text
    log_sanitized_system_error(session_id=session_id, raw_text=text)
    return f"SYSTEM ERROR: {t(_GENERIC_ERROR_MSG, language)}"

_DISPLAY_AMENITY_LIMIT = 4
_AMENITY_INTENT_ALIASES: dict[str, tuple[str, ...]] = {
    "pool": ("pool", "swimming pool", "ho boi", "be boi"),
    "private_beach": ("private beach", "bai bien rieng"),
    "sea_view": ("sea view", "ocean view", "nhin ra bien", "view bien"),
    "spa": ("spa", "sauna", "massage", "xong hoi"),
    "gym": ("gym", "fitness", "yoga"),
    "family": ("family room", "kids club", "playground", "phong gia dinh", "tre em"),
    "accessibility": ("wheelchair", "accessible", "tro nang", "xe lan"),
    "airport_transfer": ("airport transfer", "airport shuttle", "dua don san bay"),
    "breakfast": ("breakfast", "bua sang", "an sang"),
    "lunch": ("lunch", "bua trua", "an trua"),
    "dinner": ("dinner", "evening meal", "bua toi", "an toi"),
    "meal": ("restaurant", "dining", "buffet", "bar", "room service", "nha hang", "quan bar", "dich vu phong"),
    "wifi": ("wifi", "wi fi", "wireless internet"),
    "parking": ("parking", "bai do xe", "cho do xe"),
    "air_conditioning": ("air conditioning", "air conditioner", "dieu hoa"),
    "laundry": ("laundry", "giat ui"),
    "reception": ("reception", "front desk", "le tan"),
}

_AMENITY_DISPLAY_RULES: dict[str, tuple[str, int]] = {
    "pool": ("pool", 0),
    "private_beach": ("beach_view", 0),
    "sea_view": ("beach_view", 0),
    "spa": ("wellness", 0),
    "family": ("family", 1),
    "accessibility": ("accessibility", 1),
    "airport_transfer": ("transport", 1),
    "breakfast": ("meal", 2),
    "lunch": ("meal", 2),
    "dinner": ("meal", 2),
    "meal": ("meal", 2),
    "gym": ("fitness", 3),
    "wifi": ("connectivity", 4),
    "parking": ("convenience", 5),
    "air_conditioning": ("convenience", 5),
    "laundry": ("convenience", 5),
    "reception": ("convenience", 5),
}
_MEAL_INTENTS = frozenset({"breakfast", "lunch", "dinner", "meal"})


def _normalize_amenity(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).casefold().replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _contains_amenity_term(value: str, term: str) -> bool:
    return value == term or f" {term} " in f" {value} "


def _amenity_intents(value: Any) -> tuple[str, ...]:
    normalized = _normalize_amenity(value)
    return tuple(
        intent
        for intent, aliases in _AMENITY_INTENT_ALIASES.items()
        if any(_contains_amenity_term(normalized, alias) for alias in aliases)
    )


def _preference_intents(active_preferences: Any) -> list[str]:
    intents: list[str] = []
    seen: set[str] = set()
    for preference in active_preferences or []:
        if isinstance(preference, dict):
            values = (preference.get("id"), preference.get("label"))
        else:
            values = (preference,)

        recognized = next(
            (intent for value in values for intent in _amenity_intents(value)),
            None,
        )
        fallback = next((_normalize_amenity(value) for value in reversed(values) if _normalize_amenity(value)), "")
        intent = recognized or fallback
        if intent and intent not in seen:
            seen.add(intent)
            intents.append(intent)
    return intents


def _amenity_category(intents: tuple[str, ...], normalized: str) -> str:
    for intent in intents:
        if rule := _AMENITY_DISPLAY_RULES.get(intent):
            return rule[0]
    return f"other:{normalized}"


def _fallback_priority(intents: tuple[str, ...], *, covered_meals: set[str]) -> tuple[int, int]:
    intent_set = set(intents)
    meal_intents = intent_set & _MEAL_INTENTS
    if meal_intents:
        covered = bool(meal_intents & covered_meals)
        specific = bool(meal_intents & {"breakfast", "lunch", "dinner"})
        return (2, 0 if covered else 1 if specific else 2)
    rank = min((_AMENITY_DISPLAY_RULES[intent][1] for intent in intents if intent in _AMENITY_DISPLAY_RULES), default=6)
    return (rank, 0)


def _display_amenities(option: dict[str, Any], active_preferences: Any) -> list[str]:
    """Return a preference-first, category-diverse summary for a hotel card."""
    unique_amenities: list[str] = []
    seen: set[str] = set()
    raw_amenities = option.get("amenities")
    if not isinstance(raw_amenities, (list, tuple)):
        return []
    for amenity in raw_amenities:
        if not isinstance(amenity, str):
            continue
        label = amenity.strip()
        normalized = _normalize_amenity(label)
        if label and normalized and normalized not in seen:
            seen.add(normalized)
            unique_amenities.append(label)

    candidates = [
        {
            "label": label,
            "normalized": _normalize_amenity(label),
            "intents": _amenity_intents(label),
            "index": index,
        }
        for index, label in enumerate(unique_amenities)
    ]
    selected: list[dict[str, Any]] = []
    selected_labels: set[str] = set()

    for preference_intent in _preference_intents(active_preferences):
        match = next(
            (
                candidate
                for candidate in candidates
                if candidate["normalized"] not in selected_labels
                and (
                    preference_intent in candidate["intents"]
                    or _contains_amenity_term(candidate["normalized"], preference_intent)
                    or _contains_amenity_term(preference_intent, candidate["normalized"])
                )
            ),
            None,
        )
        if match is not None:
            selected.append(match)
            selected_labels.add(match["normalized"])
        if len(selected) == _DISPLAY_AMENITY_LIMIT:
            return [candidate["label"] for candidate in selected]

    covered_meals = {
        intent
        for value in option.get("covered_meals") or []
        for intent in _amenity_intents(value)
        if intent in _MEAL_INTENTS
    }
    used_categories = {
        _amenity_category(candidate["intents"], candidate["normalized"])
        for candidate in selected
    }
    fallback_candidates = sorted(
        (candidate for candidate in candidates if candidate["normalized"] not in selected_labels),
        key=lambda candidate: (
            _fallback_priority(candidate["intents"], covered_meals=covered_meals),
            candidate["index"],
        ),
    )
    for candidate in fallback_candidates:
        category = _amenity_category(candidate["intents"], candidate["normalized"])
        if category in used_categories:
            continue
        selected.append(candidate)
        selected_labels.add(candidate["normalized"])
        used_categories.add(category)
        if len(selected) == _DISPLAY_AMENITY_LIMIT:
            break

    return [candidate["label"] for candidate in selected]


def to_hotel_options_payload(pending: dict[str, Any] | None) -> list[HotelOption]:
    """Convert session.pending_hotel_selection to a list of HotelOption."""
    if not pending or not isinstance(pending, dict):
        return []
    active_preferences = pending.get("active_preferences") or []
    options = []
    for index, option in enumerate(pending.get("options") or [], start=1):
        name = str(option.get("name") or "").strip()
        if not name:
            continue
        coords = option.get("coordinates")
        if not coords and option.get("latitude") and option.get("longitude"):
            coords = f"{option.get('latitude')},{option.get('longitude')}"
        raw_amenities = option.get("amenities")
        amenities = (
            [item for item in raw_amenities if isinstance(item, str)]
            if isinstance(raw_amenities, (list, tuple))
            else []
        )
        options.append(
            HotelOption(
                index=index,
                id=str(option.get("id") or option.get("hotel_id") or ""),
                name=name,
                star_rating=option.get("star_rating"),
                description=option.get("description"),
                matched_rooms=list(option.get("matched_rooms") or option.get("matched_room_names") or []),
                average_nightly_price=option.get("average_nightly_price"),
                total_stay_price=option.get("total_stay_price"),
                stay_night_count=option.get("stay_night_count"),
                currency=option.get("currency"),
                coordinates=str(coords) if coords else None,
                address=option.get("address"),
                area_name=option.get("area_name"),
                image_url=option.get("image_url"),
                amenities=amenities,
                display_amenities=_display_amenities(option, active_preferences),
                review_score=option.get("review_score"),
                review_count=option.get("review_count"),
                match_score=option.get("match_score"),
                match_reasons=list(option.get("match_reasons") or []),
                city=option.get("city"),
                preferences=list(option.get("preferences") or []),
            )
        )
    return options


def to_trip_plan_payload(trip_data: dict[str, Any] | None) -> TripPlanPayload | None:
    """Convert session.trip_data to a TripPlanPayload, or None if absent."""
    if not trip_data or not isinstance(trip_data, dict):
        return None
    from src.services.trip_formatter import to_trip_plan_payload as format_trip_plan
    dict_payload = format_trip_plan(trip_data)
    if not dict_payload:
        return None
    return TripPlanPayload.model_validate(dict_payload)
