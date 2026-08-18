"""Pydantic models for the API layer.

Phase 3 additions:
- PlannerChatRequest.session_id typed as UUID (RT-6: safe for GET /chat which
  uses crypto.randomUUID()).
- PlannerChatResponse extended with session_id, stage, hotel_options, trip_plan,
  intake — all new fields are Optional so the existing /api/v1/chat page keeps
  working without changes (D10).
- Payload models: HotelOption, TripPlanPayload, DayPlan, ItineraryItem,
  IntakeStatus.
- Converter helpers: to_hotel_options_payload(), to_trip_plan_payload() —
  live here so route handlers never re-implement serialisation logic.
  `IntakeStatus.from_state()` used to sit alongside them, building the status
  from a `TripIntakeState`; the graph plane derives it from `travel_state`
  instead (`agents/graph/response_payload.py`), and the last caller went away
  with the restore-endpoint rewrite.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.i18n import DEFAULT_LANGUAGE, t
from src.observability import log_sanitized_system_error
from src.services.amenity_catalog import query_all_approved_amenities_by_ids

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


class ResponsePayload(BaseModel):
    """Base for models the API only ever *sends*.

    `json_schema_serialization_defaults_required` makes a field with a default
    required in the response schema while leaving it optional for input. That
    matches reality: a response always carries every field, defaults included,
    so a generated client should see `days: Day[]`, not `days?: Day[]`. Without
    it every list-with-a-default became optional in `openapi.json`, and the
    frontend had to null-check collections the backend guarantees.

    Only for response models — a request model's defaults really are optional.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class MatchReasonPayload(ResponsePayload):
    """One piece of ranking evidence behind "AI đề xuất vì…".

    `code` is an i18n key the frontend owns (matchReason.*); `value` is the raw
    number or label it describes. The backend never sends display text — the
    shape `hotel_selection._match_reasons` has always produced, now declared so
    a generated client sees it instead of an open dict.
    """

    code: str
    value: float | str


class NearbyPlacePayload(ResponsePayload):
    """An entry of `hotels.nearby_attractions` (a jsonb column).

    `extra="allow"` because these rows are crawled data: the four fields below
    are the ones the UI reads and were confirmed against real rows, but the
    column may carry more and dropping it on serialization would be a silent
    lie of a different kind.

    `distance_text` is a pre-formatted Vietnamese string from the crawl — data,
    not a UI string. Clients should rebuild the figure from `distance_km` so it
    honours their locale.
    """

    model_config = ConfigDict(
        json_schema_serialization_defaults_required=True, extra="allow"
    )

    name: str | None = None
    category: str | None = None
    coordinates: str | None = None
    distance_km: float | None = None
    distance_text: str | None = None


class SuggestedPlacePayload(ResponsePayload):
    """One place a worker is pointing the map at this turn — an `attractions`
    table row, not a `NearbyPlacePayload` (that one is crawled
    `hotels.nearby_attractions` jsonb data, no stable `id`). `id` lets the
    frontend key map markers and tell two same-named places apart.

    Shared wire shape, not a `list_nearby`-only one: any worker that wants
    the map to show candidate places writes into `PlannerChatResponse.
    suggested_places` using this shape — `itinerary_node`'s `list_nearby`
    search is the first writer, an `edit_item` "suggest" reply is a plausible
    second one. One field, one frontend rendering/toggle path for both.
    """

    id: str
    name: str
    category: str | None = None
    coordinates: str | None = None
    description: str | None = None
    rating: float | None = None


class RoomPricePayload(ResponsePayload):
    amount: float | None = None
    currency: str | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    sold_out: bool | None = None
    package_details: str | None = None


class RoomDetailPayload(ResponsePayload):
    id: str
    name: str
    bed_description: str | None = None
    room_size_sqm: float | None = None
    max_guests: int | None = None
    view: str | None = None
    room_facilities: list[str] | None = None
    images: list[str] | None = None
    price: RoomPricePayload | None = None
    available_room_count: int | None = Field(
        default=None,
        ge=0,
        description="Booking-aware remaining room units for the requested stay",
    )


class HotelDetailPayload(ResponsePayload):
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
    nearby_attractions: list[NearbyPlacePayload] | None = None
    nearby_essentials: Any | None = None
    lowest_price: float | None = None
    currency: str | None = None
    available_room_count: int | None = Field(
        default=None,
        ge=0,
        description="Sum of booking-aware remaining room units across this hotel",
    )
    rooms: list[RoomDetailPayload] = Field(default_factory=list)
    room_amenities: list["AmenityCatalogPayload"] = Field(
        default_factory=list,
        description="Unique approved room amenity catalog records for all returned rooms",
    )
    source_platform: str | None = None  # 'agoda' | 'booking' — powers the OTA handoff button
    source_url: str | None = None  # original listing URL on the source OTA


class AttractionDetailPayload(ResponsePayload):
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


class HotelOption(ResponsePayload):
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
    match_reasons: list[MatchReasonPayload] = Field(default_factory=list)
    city: str | None = None


class RouteInfoPayload(ResponsePayload):
    distance_km: float
    duration_mins: float
    polyline: str
    profile: str | None = None

class ItineraryItem(ResponsePayload):
    # `int(item.get("order_index") or 0)` in trip_formatter — never absent.
    order_index: int
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


class DayPlan(ResponsePayload):
    # Both always set by trip_formatter: `day_number` comes from `range(1, n+1)`
    # and `theme` falls back to "" rather than None.
    day_number: int
    theme: str
    items: list[ItineraryItem] = Field(default_factory=list)


class TripPlanHotel(ResponsePayload):
    id: str | None = None
    name: str | None = None
    star_rating: float | None = None
    description: str | None = None
    matched_rooms: list[str] = Field(default_factory=list)
    coordinates: str | None = None
    image_url: str | None = None
    source_platform: str | None = None  # 'agoda' | 'booking' — powers the OTA handoff button
    source_url: str | None = None  # original listing URL on the source OTA


class TripPlanPayload(ResponsePayload):
    """Phase 3 payload for the trip plan right panel."""

    # `itinerary.get("status") or "Draft"` — always a string.
    status: str
    destination: str | None = None
    # `int(...)` over the itinerary or the day count — always an int.
    duration_days: int
    start_date: str | None = None
    end_date: str | None = None
    number_of_adults: int | None = None
    budget: float | None = None
    # `hotel.get("currency") or "VND"` — always a string.
    budget_currency: str
    hotel: TripPlanHotel | None = None
    days: list[DayPlan] = Field(default_factory=list)
    adjustments: list[str] = Field(default_factory=list)


class IntakeStatus(ResponsePayload):
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
    budget_skipped: bool = Field(
        default=False,
        description="True when the user explicitly opted out of a budget preference",
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Names of fields still needed: 'destination', 'people', 'start_date', 'end_date'",
    )


class SuggestionPayload(ResponsePayload):
    label: str = Field(..., description="Chữ hiển thị trên nút gợi ý")
    value: str = Field(..., description="Nội dung gửi đi khi bấm nút")


#: Every value here must be one `response_payload.derive_stage` can actually
#: return. `modified` and `finalized` were declared here for a long time with
#: no producer anywhere: `modified` came from the deleted `process_chat_turn`
#: cascade's `_STAGE_MAP`, and `finalized` from the same map's
#: `finalize_trip_plan` tool, which the graph plane has no counterpart for
#: (`booking_node` is unconditionally unroutable — `routing.py`'s
#: `_IMPOSSIBLE["booking_node"] = lambda s: True` — and declines rather than
#: completes when it does run). A declared-but-unreachable value is how
#: `stage === 'error'` sat in the frontend for months as dead code that looked
#: alive; do not add one back without its producer in the same change.
ChatStage = Literal["intake", "hotel_options", "planned", "error"]


class PlannerChatRequest(BaseModel):
    """A chat turn. Every field here reaches the graph.

    `stay_dates`, `min_price` and `max_price` used to be declared alongside
    `message`, guarded by a validator demanding "at least one of" them — and
    then dropped: `_run_turn_via_graph` only ever forwarded `message`. No
    client sent them either, so the contract was dead at both ends.

    They were deleted rather than connected. Feeding structured values into
    `travel_state` means a path around `extract_patch -> validate_patch ->
    apply_patch`, and that pipeline is where ambiguity gets resolved (an
    unclear date pauses the turn to ask) and where every write is checked
    against `ALLOWED_PATHS`. A side door for three fields nobody uses is not
    worth a second, unvalidated way into the same slots. The widget's existing
    route — compose a sentence, let the extractor parse it — is slower by one
    LLM call and correct by construction. A fast structured path is a real
    design problem for its own plan, not a dormant field woken up.

    `message` is required now, which is what the old validator was trying to
    say the long way around.
    """

    session_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)
    language: Literal["vi", "en"] = Field(
        DEFAULT_LANGUAGE, description="UI language for this turn's reply (vi | en)"
    )


class SelectHotelRequest(BaseModel):
    session_id: UUID
    hotel_id: str | int
    selection_message: str | None = Field(default=None, min_length=1, max_length=5000)


class ChangeHotelRequest(BaseModel):
    session_id: UUID


class BookingReservationRequest(BaseModel):
    room_id: UUID
    temporary_user_ref: str = Field(min_length=1, max_length=128)
    check_in_date: date
    check_in_time: time = time(14, 0)
    check_out_date: date
    check_out_time: time = time(12, 0)
    room_count: int = Field(default=1, ge=1, le=20)
    total_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=16)

    @model_validator(mode="after")
    def check_out_must_follow_check_in(self) -> BookingReservationRequest:
        if self.check_out_date <= self.check_in_date:
            raise ValueError("check_out_date must be after check_in_date")
        return self


class BookingOwnershipRequest(BaseModel):
    temporary_user_ref: str = Field(min_length=1, max_length=128)


class BookingPayload(BaseModel):
    id: UUID
    room_id: UUID
    check_in_date: date
    check_in_time: time
    check_out_date: date
    check_out_time: time
    room_count: int
    status: Literal["PENDING", "RESERVED", "CONFIRMED", "CANCELLED", "EXPIRED"]
    expires_at: datetime | None = None
    total_amount: Decimal | None = None
    currency: str | None = None


# ---- VNPay payment (plan 260818-vnpay-payment-and-email-confirmation) -----


class CreateVnpayPaymentRequest(BaseModel):
    """One payment covers every booking in a hold group — a guest can hold
    several distinct room types at once (frontend's use-room-hold.ts), but
    VNPay has exactly one vnp_TxnRef per transaction."""

    booking_ids: list[UUID] = Field(min_length=1, max_length=20)
    temporary_user_ref: str = Field(min_length=1, max_length=128)
    guest_name: str = Field(min_length=1, max_length=200)
    guest_email: EmailStr
    guest_phone: str | None = Field(default=None, max_length=32)


class CreateVnpayPaymentResponse(BaseModel):
    payment_id: UUID
    pay_url: str


class PaymentPayload(BaseModel):
    id: UUID
    booking_ids: list[UUID]
    amount: Decimal
    currency: str
    status: Literal["PENDING", "PAID", "FAILED", "CANCELLED"]
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    vnp_transaction_no: str | None = None
    paid_at: datetime | None = None
    created_at: datetime


class PreferencePayload(BaseModel):
    id: str
    label: str


class AmenityCatalogPayload(ResponsePayload):
    """Approved hotel amenity exposed to the browser for filters and pills."""

    id: str
    label_vi: str
    label_en: str
    category: str
    icon_key: str | None = None


class PlannerChatResponse(ResponsePayload):
    session_id: str
    reply: str
    suggestions: list[SuggestionPayload] = Field(default_factory=list)
    stage: ChatStage
    hotel_options: list[HotelOption] = Field(default_factory=list)
    hotel_amenities: list[AmenityCatalogPayload] = Field(
        default_factory=list,
        description="Unique approved amenity catalog records for all returned hotel options",
    )
    trip_plan: TripPlanPayload | None = None
    intake: IntakeStatus | None = None
    requires_stay_dates: bool = False
    compound_min_price: float | None = None
    compound_max_price: float | None = None
    all_preferences: list[PreferencePayload] = Field(default_factory=list)
    active_preferences: list[PreferencePayload] = Field(default_factory=list)
    # Set only on a turn whose worker wrote one (see
    # `response_payload.suggested_places_from_task_results`); empty on every
    # other turn so a stale result never leaks onto a later, unrelated reply.
    suggested_places: list[SuggestedPlacePayload] = Field(default_factory=list)


class SessionSummaryPayload(ResponsePayload):
    session_id: str
    title: str | None = None
    destination: str | None = None
    duration_days: int | None = None
    status: Literal["draft", "completed"]
    created_at: str | None = None
    updated_at: str | None = None
    thumbnail_url: str | None = None


class SessionListPayload(ResponsePayload):
    sessions: list[SessionSummaryPayload] = Field(default_factory=list)
    page: int
    page_size: int
    has_more: bool


class RestoredMessagePayload(ResponsePayload):
    role: Literal["user", "assistant"]
    text: str
    # The same vocabulary a live turn uses. `session_store.restored_messages`
    # currently reports "intake" for every restored row (chat_messages has no
    # stage column), but the type is the contract, not that limitation.
    stage: ChatStage
    at: str


class SessionRestorePayload(ResponsePayload):
    session_id: str
    messages: list[RestoredMessagePayload] = Field(default_factory=list)
    suggestions: list[SuggestionPayload] = Field(default_factory=list)
    stage: str
    hotel_options: list[HotelOption] = Field(default_factory=list)
    hotel_amenities: list[AmenityCatalogPayload] = Field(default_factory=list)
    trip_plan: TripPlanPayload | None = None
    intake: IntakeStatus | None = None


# ---------------------------------------------------------------------------
# Converters & Sanitizers
# ---------------------------------------------------------------------------


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
    raw_options = [option for option in pending.get("options") or [] if isinstance(option, dict)]
    options = []
    for index, option in enumerate(raw_options, start=1):
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
            )
        )
    return options


def hotel_amenities_from_hotel_options(
    hotel_options: list[HotelOption] | list[dict[str, Any]],
) -> list[AmenityCatalogPayload]:
    """Join the unique amenity IDs from all returned hotel cards once.

    Card payloads deliberately retain only canonical IDs.  The shared catalog
    lives beside ``hotel_options`` in the response, avoiding the same catalog
    row being serialized repeatedly for every hotel that has that amenity.
    """
    amenity_ids: list[str] = []
    for hotel in hotel_options:
        if isinstance(hotel, HotelOption):
            values = [*hotel.amenities, *hotel.display_amenities]
        else:
            values = [*(hotel.get("amenities") or []), *(hotel.get("display_amenities") or [])]
        amenity_ids.extend(value for value in values if isinstance(value, str))
    ordered_ids = list(dict.fromkeys(amenity_ids))
    if not ordered_ids:
        return []
    by_id = {
        entry.id: AmenityCatalogPayload(
            id=entry.id,
            label_vi=entry.label,
            label_en=entry.label_en,
            category=entry.category,
            icon_key=entry.icon_key,
        )
        for entry in query_all_approved_amenities_by_ids(ordered_ids)
        if entry.scope in {"hotel", "both"}
    }
    return [by_id[amenity_id] for amenity_id in ordered_ids if amenity_id in by_id]


def to_trip_plan_payload(trip_data: dict[str, Any] | None) -> TripPlanPayload | None:
    """Convert session.trip_data to a TripPlanPayload, or None if absent."""
    if not trip_data or not isinstance(trip_data, dict):
        return None
    from src.services.trip_formatter import to_trip_plan_payload as format_trip_plan
    dict_payload = format_trip_plan(trip_data)
    if not dict_payload:
        return None
    return TripPlanPayload.model_validate(dict_payload)
