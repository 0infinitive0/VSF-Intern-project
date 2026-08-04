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

from datetime import date
import logging
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from src.i18n import t, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)

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
    hotel_id: str = Field(..., description="UUID từ bảng hotels")
    name: str = Field(..., description="Tên khách sạn")
    destination_id: str | None = Field(default=None, description="UUID trỏ về điểm đến")
    star_rating: float | None = Field(default=None, description="Hạng sao")
    price_tier: str | None = Field(default=None, description="Mức giá")
    amenities: list[str] | None = Field(default=None, description="Danh sách tiện ích")


class RoomPayload(BaseModel):
    room_id: str = Field(..., description="UUID từ bảng rooms")
    hotel_id: str = Field(..., description="UUID trỏ về bảng hotels")
    name: str = Field(..., description="Tên phòng")
    max_guests: int | None = Field(default=None, description="Số khách tối đa")
    room_size_sqm: float | None = Field(default=None, description="Diện tích phòng")
    view: str | None = Field(default=None, description="Hướng nhìn")


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


class ItineraryItem(BaseModel):
    order_index: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    activity: str | None = None
    kind: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    coordinates: str | None = None


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


class TripPlanPayload(BaseModel):
    """Phase 3 payload for the trip plan right panel."""

    status: str | None = None
    destination: str | None = None
    duration_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    number_of_adults: int | None = None
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
<<<<<<< Updated upstream:backend/src/models/schemas.py
    session_id: UUID
    message: str | None = None
    stay_dates: StayDatesInput | None = None
    min_price: float | None = None
    max_price: float | None = None

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
    hotel_id: str
=======
    # session_id typed as UUID so malformed ids are rejected at the pydantic
    # boundary (422) rather than silently treated as valid. Safe for GET /chat
    # which generates ids with crypto.randomUUID() (RT-6).
    session_id: UUID = Field(..., description="UUID phiên chat do trình duyệt tự sinh")
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn từ user")
    language: Literal["vi", "en"] = Field(
        DEFAULT_LANGUAGE, description="UI language for this turn's reply (vi | en)"
    )
>>>>>>> Stashed changes:src/models/schemas.py


class PlannerChatResponse(BaseModel):
    session_id: str
    reply: str
    suggestions: list[SuggestionPayload] = Field(default_factory=list)
    stage: ChatStage
    hotel_options: list[HotelOption] = Field(default_factory=list)
    trip_plan: TripPlanPayload | None = None
    intake: IntakeStatus | None = None
    requires_stay_dates: bool = False


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
    logger.error("Sanitizing SYSTEM ERROR for session %s: %s", session_id, text)
    return f"SYSTEM ERROR: {t(_GENERIC_ERROR_MSG, language)}"

def to_hotel_options_payload(pending: dict[str, Any] | None) -> list[HotelOption]:
    """Convert session.pending_hotel_selection to a list of HotelOption."""
    if not pending or not isinstance(pending, dict):
        return []
    options = []
    for index, option in enumerate(pending.get("options") or [], start=1):
        name = str(option.get("name") or "").strip()
        if not name:
            continue
        coords = option.get("coordinates")
        if not coords and option.get("latitude") and option.get("longitude"):
            coords = f"{option.get('latitude')},{option.get('longitude')}"
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
