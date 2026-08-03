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

import logging
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

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


class ItineraryItem(BaseModel):
    order_index: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    activity: str | None = None
    kind: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None


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
    """Structured trip plan for the React UI.  Null until a hotel is picked."""

    status: str | None = Field(default=None, description="Draft | Finalized")
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
    missing: list[str] = Field(
        default_factory=list,
        description="Names of fields still needed: 'destination', 'duration', 'start_date', 'people'",
    )

    @classmethod
    def from_state(cls, intake_state: Any) -> IntakeStatus:
        """Build from a TripIntakeState without importing it here."""
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
            missing=missing,
        )


# ---------------------------------------------------------------------------
# Planner chat models (Phase 3 extended)
# ---------------------------------------------------------------------------


class ChatSuggestion(BaseModel):
    label: str = Field(..., description="Chữ hiển thị trên nút gợi ý")
    value: str = Field(..., description="Nội dung gửi đi khi bấm nút")


class PlannerChatRequest(BaseModel):
    # session_id typed as UUID so malformed ids are rejected at the pydantic
    # boundary (422) rather than silently treated as valid. Safe for GET /chat
    # which generates ids with crypto.randomUUID() (RT-6).
    session_id: UUID = Field(..., description="UUID phiên chat do trình duyệt tự sinh")
    message: str = Field(..., min_length=1, max_length=5000, description="Tin nhắn từ user")


class PlannerChatResponse(BaseModel):
    session_id: str = Field(..., description="UUID phiên đang hoạt động")
    reply: str = Field(..., description="Phản hồi từ trip planner")
    suggestions: list[ChatSuggestion] = Field(
        default_factory=list,
        description=(
            "Các lựa chọn bấm nhanh cho lượt kế tiếp. Rỗng nghĩa là lượt này chờ "
            "người dùng nhập tự do — UI không được tự suy ra nút từ nội dung trả lời."
        ),
    )
    stage: str = Field(
        default="intake",
        description="intake | hotel_options | planned | modified | finalized | error",
    )
    hotel_options: list[HotelOption] = Field(
        default_factory=list,
        description="Danh sách khách sạn khi stage=hotel_options; rỗng ở các stage khác",
    )
    trip_plan: TripPlanPayload | None = Field(
        default=None,
        description="Kế hoạch chuyến đi có cấu trúc; null cho đến khi chọn xong khách sạn",
    )
    intake: IntakeStatus | None = Field(
        default=None,
        description="Trạng thái thu thập thông tin; null sau khi intake hoàn thành",
    )


# ---------------------------------------------------------------------------
# Converter helpers  (called from routes.py, not re-implemented per branch)
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


def sanitize_system_error(text: str, *, session_id: str | None = None) -> str:
    """Return a safe user-facing string for a SYSTEM ERROR: prefixed reply.

    If the message matches one of the hand-written Vietnamese strings it is
    returned as-is (it contains no internal detail).  Any other SYSTEM ERROR:
    string — which may carry Supabase table names, column names, or connection
    strings — is replaced with a generic Vietnamese message, and the original
    is logged at error level here (keyed by session_id) so a sanitised reply
    is still debuggable from logs instead of requiring a live repro.
    """
    if not text.startswith("SYSTEM ERROR:"):
        return text
    for prefix in _SAFE_ERROR_PREFIXES:
        if text.startswith(prefix):
            return text
    logger.error("Sanitizing SYSTEM ERROR for session %s: %s", session_id, text)
    return f"SYSTEM ERROR: {_GENERIC_ERROR_MSG}"


def to_hotel_options_payload(pending: dict[str, Any] | None) -> list[HotelOption]:
    """Convert session.pending_hotel_selection to a list of HotelOption.

    Must produce indices that agree with suggestions_for() — both are derived
    from pending["options"] in the same 1-based order.  A test asserts this.
    """
    if not pending:
        return []
    options = []
    for index, option in enumerate(pending.get("options") or [], start=1):
        name = str(option.get("name") or "").strip()
        if not name:
            continue
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
            )
        )
    return options


def to_trip_plan_payload(trip_data: dict[str, Any] | None) -> TripPlanPayload | None:
    """Convert session.trip_data to a TripPlanPayload, or None if absent."""
    if trip_data is None:
        return None
    if not isinstance(trip_data, dict):
        return None

    itinerary = (trip_data.get("itineraries") or [{}])[0] if trip_data.get("itineraries") else {}
    hotel_raw = itinerary.get("hotel") if isinstance(itinerary, dict) else None

    hotel = None
    if isinstance(hotel_raw, dict):
        hotel = TripPlanHotel(
            id=str(hotel_raw.get("id") or ""),
            name=str(hotel_raw.get("name") or ""),
            star_rating=hotel_raw.get("star_rating"),
            description=hotel_raw.get("description"),
            matched_rooms=list(hotel_raw.get("matched_room_names") or []),
            coordinates=hotel_raw.get("coordinates"),
        )

    days_raw = itinerary.get("days") or [] if isinstance(itinerary, dict) else []
    days = []
    for day_raw in days_raw:
        if not isinstance(day_raw, dict):
            continue
        items = []
        for item_raw in day_raw.get("items") or []:
            if not isinstance(item_raw, dict):
                continue
            items.append(
                ItineraryItem(
                    order_index=item_raw.get("order_index"),
                    start_time=item_raw.get("start_time"),
                    end_time=item_raw.get("end_time"),
                    activity=item_raw.get("activity"),
                    kind=item_raw.get("kind"),
                    reference_type=item_raw.get("reference_type"),
                    reference_id=str(item_raw.get("reference_id") or ""),
                )
            )
        days.append(
            DayPlan(
                day_number=day_raw.get("day_number"),
                theme=day_raw.get("theme"),
                items=items,
            )
        )

    # Top-level fields may be on the itinerary or on trip_data directly
    destination = (
        (isinstance(itinerary, dict) and itinerary.get("destination"))
        or trip_data.get("destination")
        or None
    )
    duration_days_raw = (
        (isinstance(itinerary, dict) and itinerary.get("duration_days"))
        or trip_data.get("duration_days")
        or None
    )
    try:
        duration_days = int(duration_days_raw) if duration_days_raw is not None else None
    except (TypeError, ValueError):
        duration_days = None

    number_of_adults_raw = (
        (isinstance(itinerary, dict) and itinerary.get("number_of_adults"))
        or trip_data.get("number_of_adults")
        or None
    )
    try:
        number_of_adults = int(number_of_adults_raw) if number_of_adults_raw is not None else None
    except (TypeError, ValueError):
        number_of_adults = None

    status = (isinstance(itinerary, dict) and itinerary.get("status")) or trip_data.get("status")
    start_date = (isinstance(itinerary, dict) and itinerary.get("start_date")) or trip_data.get("start_date")
    end_date = (isinstance(itinerary, dict) and itinerary.get("end_date")) or trip_data.get("end_date")

    adjustments_raw = trip_data.get("adjustments") or []
    adjustments = [str(a) for a in adjustments_raw if a]

    return TripPlanPayload(
        status=str(status) if status else None,
        destination=str(destination) if destination else None,
        duration_days=duration_days,
        start_date=str(start_date) if start_date else None,
        end_date=str(end_date) if end_date else None,
        number_of_adults=number_of_adults,
        hotel=hotel,
        days=days,
        adjustments=adjustments,
    )
