"""API route handlers for the trip planner.

Phase 3 changes:
- One module-level SessionRegistry replaces the bare _CHAT_SESSIONS dict.
- planner_chat: registry.get() + 404 (never auto-creates); per-session lock;
  sanitised errors; one-place PlannerChatResponse assembly (built by the
  `respond` node now — the TurnResult carrier this once referred to went away
  with the process_chat_turn cascade).
- Three new endpoints: POST /chat/session, GET /chat/{session_id}/plan,
  DELETE /chat/{session_id}.
- All handlers are plain `def` (not async def) so FastAPI runs them in the
  worker thread pool — Supabase/Ollama calls are blocking and must not stall
  the event loop. The one exception is POST /planner_chat/stream: it is
  `async def` (required to yield SSE frames) but runs the blocking turn in
  the worker pool via run_in_executor, so the rule above still holds.

Plan 260814-supabase-auth-and-per-user-history changes:
- Every session-scoped handler gains `current_user: AuthenticatedUser | None
  = Depends(get_current_user)`. None is a real, expected value (not an
  error) whenever AUTH_REQUIRED is False and the caller sent no/an invalid
  token — see src.auth.dependencies' module docstring for the full rollout
  contract.
- `_owned_session_or_404` replaces the repeated `registry.get()` + 404 block
  that used to appear at every one of these call sites, adding an ownership
  check on top of the existence check it already did.
- `GET /chat/sessions` now scopes to the caller instead of listing every
  persisted session in the database (a real privacy bug the ownership work
  fixes, independent of whatever AUTH_REQUIRED is set to).
"""

import asyncio
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.agents.graph.nodes.load_context import load_context
from src.agents.graph.phase_facts import phase_facts
from src.agents.graph.prompts import INTAKE_QA_NO_ANSWER_SENTINEL
from src.agents.graph.phase_keys import (
    PHASE_KEY_BY_NODE,
    STREAMING_NODES,
    SUBGRAPH_STREAMING_NODE,
)
from src.agents.graph.response_payload import (
    derive_stage,
    durable_hotel_options,
    intake_status_from_travel_state,
    last_worker_from_task_results,
)
from src.agents.session import (
    SessionRegistry,
    debug_persist_hook,
    supabase_persist_hook,
)
from src.api.streaming import (
    STREAM_HEADERS,
    TurnEmitter,
    collecting_trace,
    emit_delta,
    emit_phase,
    emit_reasoning,
    record_step,
    emitting_to,
    sse_stream,
)
from src.auth import AuthenticatedUser, get_current_user
from src.config import get_settings
from src.domain.travel_state import TravelState
from src.models.schemas import (
    AmenityCatalogPayload,
    AttractionDetailPayload,
    BookingOwnershipRequest,
    BookingPayload,
    BookingReceiptPayload,
    BookingReservationRequest,
    ChangeHotelRequest,
    CreateVnpayPaymentRequest,
    CreateVnpayPaymentResponse,
    FinalizeTripPayload,
    HotelDetailPayload,
    hotel_amenities_from_hotel_options,
    PaymentPayload,
    PlannerChatRequest,
    PlannerChatResponse,
    SelectHotelRequest,
    SessionListPayload,
    SessionRestorePayload,
    SessionSummaryPayload,
    sanitize_system_error,
    to_trip_plan_payload,
)
from src.services import payment_service, session_store, vnpay_service
from src.services.amenity_catalog import query_approved_amenities
from src.services.llm import reasoning_text, response_text
from src.services.booking_service import (
    BookingError,
    cancel_booking,
    cancel_reserved_bookings_for_session,
    confirm_booking,
    get_booking,
    reserve_booking,
)
from src.services.email_service import EmailError, send_booking_confirmation_email
from src.services.place_details import get_attraction_detail, get_hotel_detail
from src.services.trip_finalize import FinalizeTripError, finalize_session_trip, is_trip_finalized
from src.services.suggestions import (
    SuggestionContext,
    SuggestionHotelCard,
    generate_next_chat_suggestions,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Module-level session registry (replaces bare _CHAT_SESSIONS dict)
# ---------------------------------------------------------------------------

_settings = get_settings()

_persistence_enabled = _settings.session_persistence_enabled
_persist_hook = (
    supabase_persist_hook
    if _persistence_enabled
    else debug_persist_hook if _settings.debug_trip_plan_file else None
)

registry = SessionRegistry(
    ttl_seconds=_settings.session_ttl_seconds,
    cap=_settings.max_sessions,
    persist_hook=_persist_hook,
    load_hook=session_store.load if _persistence_enabled else None,
    delete_hook=session_store.delete if _persistence_enabled else None,
)
# `registry.set_checkpointer(...)` is called from src/main.py's lifespan --
# this module is imported (and `registry` constructed) before the lifespan
# runs, so the app-wide LangGraph checkpointer cannot be threaded through
# __init__ above.


def _owned_session_or_404(session_id: str, current_user: AuthenticatedUser | None):
    """registry.get() + 404, plus an ownership check.

    A session with no owner_user_id — rows persisted before this plan shipped,
    or created outside the HTTP API (the CLI never sets one) — is treated as
    accessible to any caller, matching exactly what happened before ownership
    existed. A session that DOES have an owner is only accessible to that same
    owner. Either way, a mismatch raises the same 404 as "doesn't exist" —
    never 403, which would itself leak "this session_id is real, just not
    yours" (a session-enumeration side channel).
    """
    session = registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    if session.owner_user_id is not None and (current_user is None or session.owner_user_id != current_user.id):
        raise HTTPException(status_code=404, detail="Phiên chat không tồn tại.")
    return session


# ---------------------------------------------------------------------------
# Sessionless detail endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.get("/hotel-amenities", response_model=list[AmenityCatalogPayload])
def hotel_amenity_catalog() -> list[AmenityCatalogPayload]:
    """Return approved hotel-scoped catalog entries for client-side filtering."""
    return [
        AmenityCatalogPayload(
            id=entry.id,
            label_vi=entry.label,
            label_en=entry.label_en,
            category=entry.category,
            icon_key=entry.icon_key,
        )
        for entry in query_approved_amenities()
        if entry.scope in {"hotel", "both"}
    ]


@router.get("/hotels/{hotel_id}", response_model=HotelDetailPayload)
def hotel_detail(
    hotel_id: UUID, check_in: date | None = None, check_out: date | None = None
) -> HotelDetailPayload:
    if (check_in is None) != (check_out is None) or (
        check_in is not None and check_out is not None and check_out <= check_in
    ):
        raise HTTPException(status_code=422, detail="check_in and check_out must form a valid stay.")
    try:
        detail = get_hotel_detail(str(hotel_id), check_in, check_out)
    except Exception:
        logger.exception("hotel_detail lookup failed for %s", hotel_id)
        raise HTTPException(status_code=500, detail="Unable to retrieve hotel detail.")
    if detail is None:
        raise HTTPException(status_code=404, detail="Hotel not found.")
    return HotelDetailPayload.model_validate(detail)


@router.get("/attractions/{attraction_id}", response_model=AttractionDetailPayload)
def attraction_detail(attraction_id: UUID) -> AttractionDetailPayload:
    try:
        detail = get_attraction_detail(str(attraction_id))
    except Exception:
        logger.exception("attraction_detail lookup failed for %s", attraction_id)
        raise HTTPException(status_code=500, detail="Unable to retrieve attraction detail.")
    if detail is None:
        raise HTTPException(status_code=404, detail="Attraction not found.")
    return AttractionDetailPayload.model_validate(detail)


def _booking_http_error(exc: BookingError) -> HTTPException:
    if str(exc) == "booking_not_found":
        return HTTPException(status_code=404, detail="Booking not found.")
    if str(exc) == "invalid_booking_request":
        return HTTPException(status_code=422, detail=str(exc))
    if str(exc) in {
        "insufficient_room_availability",
        "booking_reservation_expired",
        "booking_not_confirmable",
        "guest_already_holding_elsewhere",
    }:
        return HTTPException(status_code=409, detail=str(exc))
    logger.exception("Booking operation failed", exc_info=exc)
    return HTTPException(status_code=500, detail="Unable to process booking.")


@router.post("/bookings", response_model=BookingPayload, status_code=201)
def create_booking(request: BookingReservationRequest) -> BookingPayload:
    try:
        booking = reserve_booking(**request.model_dump())
        return BookingPayload.model_validate(booking)
    except BookingError as exc:
        raise _booking_http_error(exc) from exc


@router.post("/bookings/{booking_id}/confirm", response_model=BookingPayload)
def confirm_booking_endpoint(booking_id: UUID, request: BookingOwnershipRequest) -> BookingPayload:
    try:
        return BookingPayload.model_validate(
            confirm_booking(booking_id=booking_id, temporary_user_ref=request.temporary_user_ref)
        )
    except BookingError as exc:
        raise _booking_http_error(exc) from exc


@router.post("/bookings/{booking_id}/cancel", response_model=BookingPayload)
def cancel_booking_endpoint(booking_id: UUID, request: BookingOwnershipRequest) -> BookingPayload:
    try:
        return BookingPayload.model_validate(
            cancel_booking(booking_id=booking_id, temporary_user_ref=request.temporary_user_ref)
        )
    except BookingError as exc:
        raise _booking_http_error(exc) from exc


# ---------------------------------------------------------------------------
# VNPay payment (plan 260818-vnpay-payment-and-email-confirmation)
#
# Not verified against a real VNPay sandbox yet -- no merchant credentials
# configured (see the plan's "Việc cần chuẩn bị" section). Written to
# VNPay's documented "Payment via Payment Platform" spec and covered by
# self-consistency signature tests; re-check against VNPay's own sample
# project once vnp_TmnCode/vnp_HashSecret exist.
# ---------------------------------------------------------------------------


def _send_confirmation_email_best_effort(payment: dict[str, Any]) -> None:
    """Never lets an email failure affect the payment/booking outcome — by
    the time this is called the booking is already CONFIRMED and the
    payment already PAID; losing the email is real but strictly smaller
    than losing/duplicating that."""
    guest_email = payment.get("guest_email")
    if not guest_email:
        return
    booking_ids = payment.get("booking_ids") or []
    if not booking_ids:
        return
    summary = payment_service.booking_summary_for_email([UUID(str(b)) for b in booking_ids])
    try:
        send_booking_confirmation_email(
            to_email=guest_email,
            guest_name=payment.get("guest_name") or "",
            hotel_name=(summary or {}).get("hotel_name") or "",
            hotel_image_url=(summary or {}).get("hotel_image_url"),
            booking_code=str(payment["id"])[:8].upper(),
            check_in_date=str((summary or {}).get("check_in_date") or ""),
            check_out_date=str((summary or {}).get("check_out_date") or ""),
            rooms=(summary or {}).get("rooms") or [],
            total_amount=Decimal(str(payment["amount"])) if payment.get("amount") is not None else None,
            currency=payment.get("currency"),
        )
    except EmailError:
        logger.exception("Failed to send booking confirmation email for payment %s", payment["id"])


@router.post("/payments/vnpay", response_model=CreateVnpayPaymentResponse, status_code=201)
def create_vnpay_payment(payload: CreateVnpayPaymentRequest, http_request: Request) -> CreateVnpayPaymentResponse:
    settings = get_settings()
    if not settings.vnpay_tmn_code or not settings.vnpay_hash_secret:
        raise HTTPException(status_code=503, detail="Payment gateway is not configured.")

    total = Decimal("0")
    currency = "VND"
    for booking_id in payload.booking_ids:
        booking = get_booking(booking_id)
        if booking is None or booking.get("temporary_user_ref") != payload.temporary_user_ref:
            raise HTTPException(status_code=404, detail="Booking not found.")
        if booking.get("status") != "RESERVED":
            raise HTTPException(status_code=409, detail="booking_not_confirmable")
        expires_at = booking.get("expires_at")
        if expires_at:
            expires_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expires_dt <= datetime.now(UTC):
                raise HTTPException(status_code=409, detail="booking_reservation_expired")
        if booking.get("total_amount") is not None:
            total += Decimal(str(booking["total_amount"]))
        if booking.get("currency"):
            currency = booking["currency"]

    payment = payment_service.create_payment(
        booking_ids=payload.booking_ids,
        temporary_user_ref=payload.temporary_user_ref,
        amount=total,
        currency=currency,
        guest_name=payload.guest_name,
        guest_email=payload.guest_email,
        guest_phone=payload.guest_phone,
    )

    client_ip = http_request.client.host if http_request.client else "127.0.0.1"
    pay_url = vnpay_service.build_payment_url(
        pay_url=settings.vnpay_pay_url,
        tmn_code=settings.vnpay_tmn_code,
        hash_secret=settings.vnpay_hash_secret,
        amount=total,
        txn_ref=str(payment["id"]).replace("-", ""),
        order_info=f"Thanh toan dat phong {str(payment['id'])[:8]}",
        return_url=settings.vnpay_return_url,
        ip_addr=client_ip,
    )
    return CreateVnpayPaymentResponse(payment_id=payment["id"], pay_url=pay_url)


@router.get("/payments/vnpay/ipn")
def vnpay_ipn(request: Request) -> dict[str, str]:
    """The ONLY trusted payment confirmation source — see the module doc
    comment above. VNPay reads RspCode/Message from this response to decide
    whether to retry; "00" means "I received and processed this
    notification", independent of whether the underlying transaction itself
    succeeded (that's read from vnp_ResponseCode/vnp_TransactionStatus)."""
    settings = get_settings()
    params = dict(request.query_params)

    if not vnpay_service.verify_signature(params, settings.vnpay_hash_secret):
        return {"RspCode": "97", "Message": "Invalid signature"}

    txn_ref = params.get("vnp_TxnRef", "")
    try:
        payment = payment_service.get_payment(UUID(txn_ref))
    except ValueError:
        payment = None
    if payment is None:
        return {"RspCode": "01", "Message": "Order not found"}

    try:
        received_amount = vnpay_service.vnpay_amount_to_decimal(params.get("vnp_Amount", ""))
    except Exception:
        return {"RspCode": "04", "Message": "Invalid amount"}
    if received_amount != Decimal(str(payment["amount"])):
        return {"RspCode": "04", "Message": "Invalid amount"}

    if payment["status"] != "PENDING":
        # Already processed -- either a real retry (idempotent, correct) or
        # a forged replay of an old notification (harmless: no state change
        # happens either way).
        return {"RspCode": "02", "Message": "Order already confirmed"}

    response_code = params.get("vnp_ResponseCode", "")
    transaction_status = params.get("vnp_TransactionStatus", "")
    transaction_no = params.get("vnp_TransactionNo", "")

    if response_code == "00" and transaction_status == "00":
        updated = payment_service.mark_payment_paid(
            payment_id=payment["id"], vnp_transaction_no=transaction_no, vnp_response_code=response_code,
        )
        if updated is None:
            # Lost the race to a concurrent IPN retry that already flipped
            # this payment to PAID/FAILED -- still fine, not our job to redo.
            return {"RspCode": "02", "Message": "Order already confirmed"}
        for booking_id in payment["booking_ids"]:
            try:
                confirm_booking(booking_id=UUID(str(booking_id)), temporary_user_ref=payment["temporary_user_ref"])
            except BookingError:
                logger.exception(
                    "Failed to confirm booking %s after VNPay payment %s", booking_id, payment["id"]
                )
        _send_confirmation_email_best_effort(updated)
        return {"RspCode": "00", "Message": "Confirm Success"}

    payment_service.mark_payment_failed(payment_id=payment["id"], vnp_response_code=response_code)
    return {"RspCode": "00", "Message": "Confirm Success"}


@router.get("/payments/{payment_id}", response_model=PaymentPayload)
def get_payment_endpoint(payment_id: UUID, temporary_user_ref: str = Query(...)) -> PaymentPayload:
    payment = payment_service.get_payment_for_owner(payment_id, temporary_user_ref)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found.")
    return PaymentPayload.model_validate(payment)


@router.get("/chat/{session_id}/booking-receipt", response_model=BookingReceiptPayload)
def get_booking_receipt(
    session_id: str, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> BookingReceiptPayload:
    """"Reopen a past session's booking" (plan 260818-vnpay-payment-and-
    email-confirmation's addendum 4) — roomHold, the frontend's only other
    source for booking details, is a single global hold that only ever
    reflects whichever session most recently held/paid (use-room-hold.ts's
    module doc comment), so a guest revisiting an OLDER paid session needs
    this real, independent lookup instead. Ownership is the session's own
    (same `_owned_session_or_404` every other /chat/{session_id}/... route
    uses) — not `temporary_user_ref`, which a guest checkout session has no
    reliable way to supply for a session that isn't the currently active
    one. 404 both when the session itself doesn't exist/isn't the caller's,
    and when it exists but has no CONFIRMED booking (never held anything,
    hold expired unpaid, or payment failed) — same "don't distinguish who
    is asking" posture booking_service's own 404s already use."""
    _owned_session_or_404(session_id, current_user)
    receipt = payment_service.get_booking_receipt_for_session(session_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="No confirmed booking for this session.")
    return BookingReceiptPayload.model_validate(receipt)


@router.post("/chat/{session_id}/finalize", response_model=FinalizeTripPayload)
def finalize_trip(
    session_id: str, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> FinalizeTripPayload:
    """Lock a session's itinerary and save it as a reusable, embedded
    template — the user-facing entry point for the previously-orphaned
    `finalize_trip_data` (see `services/trip_finalize.py`'s module
    docstring: nothing called it before this route existed).

    Payment-gated by product decision: 409 unless the session already has a
    CONFIRMED booking, checked the same way `get_booking_receipt` above
    does — `get_booking_receipt_for_session` returning non-None IS "this
    session is paid," so no second query/table is needed to express that.
    Also 409 for no trip plan yet, or an itinerary already `Finalized`
    (`finalize_session_trip` raises `FinalizeTripError` for both — a
    genuine double-submit is a no-op success at the store layer, but this
    route surfaces it as 409 so the frontend never shows a misleading
    "saving" state for a click that changes nothing).

    Writes the mutated `trip_data` back into checkpointed graph state via
    `update_state` rather than running a graph turn — finalizing carries no
    user chat text and touches no other turn-scoped field, so invoking the
    full `load_context -> ... -> respond` pipeline for it would be pure
    overhead. `_persist_turn` (this module, below) is reused verbatim for
    the checkpoint write so `ui_summary.status` recomputes exactly the way
    every other mutating route already achieves it.
    """
    _owned_session_or_404(session_id, current_user)
    if payment_service.get_booking_receipt_for_session(session_id) is None:
        raise HTTPException(status_code=409, detail="Cần đặt phòng và thanh toán trước khi hoàn tất lịch trình.")

    app = _get_graph_v2()
    config = {"configurable": {"thread_id": session_id}}
    trip_data = (app.get_state(config).values or {}).get("trip_data")
    if not trip_data:
        raise HTTPException(status_code=409, detail="Chưa có kế hoạch để hoàn tất.")

    try:
        result = finalize_session_trip(trip_data)
    except FinalizeTripError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.update_state(config, {"trip_data": result["trip_data"]})
    _persist_turn(session_id, app, config)
    return FinalizeTripPayload(
        status=result["status"], summary=result["summary"], embedding_saved=result["embedding_saved"]
    )


# ---------------------------------------------------------------------------
# Session lifecycle endpoints (Phase 3)
# ---------------------------------------------------------------------------


@router.post("/chat/session")
def create_session(current_user: AuthenticatedUser | None = Depends(get_current_user)) -> dict:
    """Tạo một phiên chat mới và trả về session_id do server cấp.

    Deliberately does NOT persist here. It used to, so the session would show
    up as its own row in the history rail right away — but an unstarted
    session (no chat turn yet) has nothing to summarize, so every one of
    those rows rendered as an indistinguishable, contentless "Chuyến đi mới"
    entry — the accumulating-empty-history bug this fixes. The in-memory
    registry entry created below already makes every other "+ Chuyến đi mới"
    click behave correctly (a fresh, empty main chat panel); the first *real*
    persisted row appears once a chat turn runs, written by `_persist_turn`
    below. (Until that writer existed, this docstring pointed at
    `persist_hook(session)` and "process_chat_turn and friends" — a cascade
    the graph cutover deleted, which is exactly how the history rail came to
    be permanently empty with no test failing.) list_sessions() additionally
    requires at least one chat_messages row per session, so any
    already-persisted empty rows from before this change stay hidden too."""
    session = registry.create(owner_user_id=current_user.id if current_user else None)

    return {
        "session_id": session.session_id,
        "created_at": datetime.fromtimestamp(session.created_at, tz=UTC).isoformat(),
    }


@router.get("/chat/sessions", response_model=SessionListPayload)
def list_persisted_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: AuthenticatedUser | None = Depends(get_current_user),
) -> SessionListPayload:
    # current_user is None whenever the caller sent no/an invalid token AND
    # AUTH_REQUIRED is False (see src.auth.dependencies) — unlike every other
    # session-scoped endpoint below, there is no legitimate "existence check
    # without an identity" use for the aggregate list, so this always returns
    # empty rather than falling back to unscoped behavior. That's the actual
    # fix for the endpoint previously returning every persisted session.
    if not _persistence_enabled or current_user is None:
        return SessionListPayload(sessions=[], page=page, page_size=page_size, has_more=False)
    try:
        persisted = session_store.list_sessions(user_id=current_user.id, page=page, page_size=page_size)
        # One extra batched query for the whole page, not N+1 — see its
        # own doc comment for why "holding"/"paid" can't be baked into the
        # persisted checkpoint summarize() otherwise reads from.
        booking_states = session_store.booking_states_for_sessions(
            [row["session_id"] for row in persisted.rows]
        )
        return SessionListPayload(
            sessions=[
                SessionSummaryPayload.model_validate(
                    session_store.summarize(row, booking_states.get(row["session_id"]))
                )
                for row in persisted.rows
            ],
            page=persisted.page,
            page_size=persisted.page_size,
            has_more=persisted.has_more,
        )
    except Exception:
        logger.exception("Unable to list persisted sessions")
        raise HTTPException(status_code=500, detail="Unable to retrieve session history.")


def _restored_transcript(session_id: str) -> list[dict[str, Any]]:
    """The persisted conversation, or nothing.

    Graph state lives in the checkpointer, the transcript in Supabase — two
    stores, two failure modes. Losing the second must cost the transcript
    alone, not the whole panel: an intake checklist and an itinerary are still
    worth restoring without the chat bubbles.
    """
    if not _persistence_enabled:
        return []
    try:
        row = session_store.load(session_id)
    except Exception:
        logger.exception("Unable to load the transcript for session %s", session_id)
        return []
    return session_store.restored_messages((row or {}).get("messages") or [])


@router.get("/chat/{session_id}/restore", response_model=SessionRestorePayload)
def restore_session(
    session_id: str, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> SessionRestorePayload:
    """Rehydrate a past conversation for the frontend.

    Every field is built by the same helpers `respond` uses for a live turn
    (`agents/graph/response_payload.py`) — a restored conversation and the turn
    that produced it must not be able to disagree.

    `suggestions` is deliberately empty, and is not an oversight: a suggestion
    belongs to one specific turn ("đặt khách sạn này?"), not to durable session
    state. Replaying a stale one next to a conversation the user left days ago
    would be worse than showing none.

    A session that exists but has never run a turn restores as a valid empty
    payload rather than 404. 404 tells the frontend the server lost the
    session, and it responds by silently creating a new one — throwing away the
    id the user is currently sitting on.
    """
    _owned_session_or_404(session_id, current_user)

    app = _get_graph_v2()
    state = app.get_state({"configurable": {"thread_id": session_id}}).values or {}
    travel_state = TravelState.from_dict(state.get("travel_state"))
    hotel_options = durable_hotel_options(state)

    return SessionRestorePayload(
        session_id=session_id,
        messages=_restored_transcript(session_id),
        suggestions=[],
        # `reply=""`: a stored session is not a turn in flight, so there is no
        # reply to judge. A past turn that failed is recorded as such in its own
        # `chat_messages` row, not re-derived for the session as a whole.
        stage=derive_stage(state, hotel_options, reply=""),
        hotel_options=hotel_options,
        hotel_amenities=hotel_amenities_from_hotel_options(hotel_options),
        trip_plan=to_trip_plan_payload(state.get("trip_data")),
        intake=intake_status_from_travel_state(travel_state),
    )


@router.get("/chat/{session_id}/plan")
@router.get("/session/{session_id}/state")
def get_session_plan(
    session_id: str, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> dict:
    """Trả về kế hoạch chuyến đi hiện tại của một phiên, hoặc 404 nếu phiên không
    tồn tại/không thuộc về caller. A session that exists but hasn't run a graph
    turn yet (no checkpointed state) is a legitimate empty-plan session, not a
    404 -- ownership is already the existence check here."""
    _owned_session_or_404(session_id, current_user)

    app = _get_graph_v2()
    snapshot = app.get_state({"configurable": {"thread_id": session_id}})
    state = snapshot.values or {}
    return {"trip_plan": to_trip_plan_payload(state.get("trip_data"))}


@router.delete("/chat/{session_id}", status_code=204)
def delete_session(
    session_id: str, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> None:
    """Xóa một phiên chat. Trả về 204 dù phiên có tồn tại hay không.

    If the session exists but belongs to someone else, this stays a silent
    no-op — still 204, preserving the existing "204 either way" contract —
    but nothing is actually deleted. No new observable status code, so this
    never leaks "this session_id exists, it's just not yours."
    """
    session = registry.get(session_id)
    if session is not None and session.owner_user_id is not None:
        if current_user is None or session.owner_user_id != current_user.id:
            return
    # Must run BEFORE registry.drop() actually deletes the session row --
    # bookings.session_id is ON DELETE SET NULL, so the link this looks up
    # by is gone the instant the row is. Best-effort: a failure here must
    # never block the deletion itself (see cancel_reserved_bookings_for_
    # session's own doc comment for why this can't rely on frontend state).
    try:
        cancel_reserved_bookings_for_session(session_id)
    except Exception:
        logger.exception("Unable to release bookings for deleted session %s", session_id)
    registry.drop(session_id)


# ---------------------------------------------------------------------------
# Main chat endpoint (hardened in Phase 3)
# ---------------------------------------------------------------------------


# `/chat/select_hotel` is an ALIAS of `/hotels/select`, not a second endpoint —
# same handler, same behavior. The frontend calls only the `/hotels/select`
# form; the alias is kept for CLI/test callers written against the older path.
# (`/chat` and `/session/{id}/state` below are aliases in the same way.)
@router.post("/chat/select_hotel", response_model=PlannerChatResponse)
@router.post("/hotels/select", response_model=PlannerChatResponse)
def select_hotel(
    request: SelectHotelRequest, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = _owned_session_or_404(session_id, current_user)

    with session.lock:
        try:
            # The client sends the label the user actually clicked ("Chọn khách
            # sạn Mường Thanh"); the fallback is for older clients that send
            # none. Either way this is transcript text only —
            # `selected_hotel_id` below is the deterministic signal `hotel_node`
            # acts on (review finding F2), so the wording never changes what
            # happens, only what the saved conversation reads like.
            message = request.selection_message or f"Tôi chọn khách sạn ID {request.hotel_id}"
            return _run_turn_via_graph(
                session_id, message, session.language, extra_state={"selected_hotel_id": str(request.hotel_id)}
            )
        except Exception as exc:
            logger.exception("Chat error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/hotels/change", response_model=PlannerChatResponse)
def change_hotel(
    request: ChangeHotelRequest, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = _owned_session_or_404(session_id, current_user)

    with session.lock:
        # The only writer entry point that reaches `hotel_node` without
        # passing through `supervisor` (`Command(goto=...)`, below) — so it
        # is the one place the finalized-trip lock guard in
        # `nodes/supervisor.py` cannot see this request at all. The frontend
        # also hides this control once finalized, but hiding a button is
        # not an access guard, hence the explicit check here too.
        state = _get_graph_v2().get_state({"configurable": {"thread_id": session_id}}).values or {}
        if is_trip_finalized(state.get("trip_data")):
            raise HTTPException(status_code=409, detail="Lịch trình đã hoàn tất và không thể chỉnh sửa.")
        try:
            return _rerun_hotel_search(session_id)
        except Exception as exc:
            logger.exception("Hotel-change error for session %s", session_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc


def _rerun_hotel_search(session_id: str) -> PlannerChatResponse:
    """Re-enter the graph directly at `hotel_node`.

    This endpoint carries no user text — "rebuild the hotel list" is the whole
    request, and `hotel_node` reads every input it needs from the already
    committed `travel_state`. The old implementation ran a full turn on the
    hardcoded Vietnamese string "đổi khách sạn", which meant sending a known
    intent through `extract_patch` — a lossy channel — to get it back, with a
    non-zero chance of the extractor inventing a patch along the way, and no
    regard for `session.language`.

    Still through the graph, not a direct `hotel_node(state)` call: that would
    lose the checkpointer write, `enforce_contract`, `respond`'s payload, and
    `interrupt()` (the node can pause to ask which center a radius search
    should use). `Command(goto=...)` keeps all four while skipping
    `load_context -> scope_guard -> extract_patch -> validate_patch ->
    apply_patch`.

    `update=load_context(...)` is required, not cosmetic: it resets the
    turn-scoped fields, and without it `respond` re-serves the previous turn's
    `task_results` and re-asks its `next_question`. Calling the node function
    keeps one definition of which fields belong to a turn instead of a copied
    list that rots. See `tests/test_hotels_change_entrypoint.py`.
    """
    app = _get_graph_v2()
    config = {"configurable": {"thread_id": session_id}}
    snapshot = app.get_state(config)

    result = app.invoke(
        Command(goto="hotel_node", update=load_context(snapshot.values or {})), config=config
    )

    _persist_turn(session_id, app, config)
    return _response_from_result(session_id, result)


# ---------------------------------------------------------------------------
# Graph dispatch — how every chat endpoint handles a turn, never touching
# TripSession.state. There is no alternative plane and no setting selecting
# one: the legacy process_chat_turn cascade is gone. Compiled once, lazily,
# so the app-lifespan checkpointer (set on `registry` after this module is
# imported) is captured at first use rather than at import time.
# ---------------------------------------------------------------------------

_graph_v2_app = None


def _get_graph_v2():
    global _graph_v2_app
    if _graph_v2_app is None:
        from src.agents.graph.graph import build_graph

        checkpointer = registry.checkpointer
        if checkpointer is None:
            logger.warning(
                "graph_v2 compiling with a process-local MemorySaver: no app-lifespan checkpointer was "
                "set on `registry` yet (checkpointer_backend != 'postgres', or called before lifespan "
                "startup). Graph state will not survive a process restart until this is re-compiled "
                "with a real checkpointer."
            )
        _graph_v2_app = build_graph(checkpointer=checkpointer)
    return _graph_v2_app


def _fresh_turn_input(session_id: str, message: str, language: str, extra_state: dict | None = None) -> dict:
    return {
        "session_id": session_id,
        "language": language,
        # `at` is stamped here, once, because this is the moment the user
        # sent it. The transcript is re-written whole on every persist, so
        # a message that doesn't carry its own timestamp gets "now" on
        # every later turn and the conversation collapses to one instant.
        "messages": [
            HumanMessage(content=message, additional_kwargs={"at": datetime.now(UTC).isoformat()})
        ],
        **(extra_state or {}),
    }


def _task_result_update(chunk: dict) -> Any:
    """The dict a finished node returned, out of a `tasks` frame.

    LangGraph reports it as `result`, which is a sequence of (channel, value)
    writes rather than the dict the node handed back. `phase_facts` reads node
    return values, so the writes are folded back into one.
    """
    result = chunk.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, (list, tuple)):
        merged: dict[str, Any] = {}
        for write in result:
            if isinstance(write, (list, tuple)) and len(write) == 2 and isinstance(write[0], str):
                merged[write[0]] = write[1]
        return merged
    return {}


class _DeclineGate:
    """Holds `intake_qa`'s opening tokens until they cannot be a decline.

    `intake_qa` streams as it writes, but whether the text is an answer at all
    is only settled once it is finished: the node replies with exactly
    `NO_ANSWER` when the message did not actually ask anything, and drops it.
    By then the tokens had already reached the user, so the sentinel appeared on
    screen and the turn then went quiet.

    Nothing is retracted here — an SSE stream has no way to unsay something, and
    the `reset` frame that once existed for exactly this was removed for exactly
    that reason (see `api/streaming.py`). Instead the opening tokens are held
    while they are still a prefix of the sentinel, and released the instant they
    diverge. A real answer is delayed by at most a few characters; a decline is
    never shown at all.

    Scoped to `intake_qa` because it is the only node with a sentinel. `qa_node`
    always answers, so gating it would delay every reply for nothing.
    """

    def __init__(self) -> None:
        self._held = ""
        self._open = False

    def feed(self, text: str) -> str:
        """What may be sent now — everything, once the gate has opened."""
        if self._open:
            return text
        if not text:
            return ""
        self._held += text
        probe = self._held.strip().upper()
        if probe and not INTAKE_QA_NO_ANSWER_SENTINEL.startswith(probe):
            self._open = True
            held, self._held = self._held, ""
            return held
        return ""

    def flush(self) -> str:
        """Whatever is still held when the stream ends.

        A buffer that never diverged is either the sentinel — dropped — or a
        short answer that happens to be a prefix of it, which must still be
        shown rather than swallowed along with the declines.
        """
        held, self._held = self._held, ""
        self._open = True
        if held.strip().upper() == INTAKE_QA_NO_ANSWER_SENTINEL:
            return ""
        return held


def _may_stream(namespace: tuple[str, ...] | None, node_name: str | None) -> bool:
    """Whether a `messages` chunk from this position may reach the user as `delta`.

    Two axes, because one is not enough. A plain node streams under the empty
    namespace and only has to be in `STREAMING_NODES`. A node that is a compiled
    subgraph — `qa_node` — streams under its own namespace, and being inside it
    is NOT sufficient: the agent's tokens are the reply, while the `tools` node
    beside it emits `ToolMessage` content that is real text and must never be
    shown (measured 2026-08-19; it was a tool error string).

    LangGraph namespaces a subgraph as `"<node>:<uuid>"`, so the node name is the
    part before the colon.
    """
    if not namespace:
        return node_name in STREAMING_NODES
    root = str(namespace[0]).split(":", 1)[0]
    return root in STREAMING_NODES and node_name == SUBGRAPH_STREAMING_NODE.get(root)


def _drive_turn(app, config: dict, turn_input, *, stream: bool) -> dict:
    """Run one turn and return its result dict, streaming or not.

    The two modes differ only here, which is the point: everything around this
    — building the input, the resume branch, interrupt handling, persistence,
    response assembly — is shared, so streaming and plain POST cannot answer
    the same message differently.

    `app.stream()` does not hand back a merged state the way `invoke()` does,
    so the final state is read from the checkpointer once the generator is
    drained. An interrupt arrives as an `__interrupt__` key in `updates` and is
    put back onto the result, giving both modes the same shape.

    Frames come from two stream modes at once:
    - `updates` names the node that just finished -> a `phase` frame, for the
      nodes worth reporting (`PHASE_KEY_BY_NODE`).
    - `messages` carries LLM tokens tagged with the node that produced them ->
      a `delta` frame, but only from `STREAMING_NODES`. That filter is the
      whole design: every other producer on this channel is either JSON
      (`extract_patch`, `supervisor`) or the finished reply itself (`respond`,
      which would otherwise be sent twice — once as deltas, once in `final`).
    """
    if not stream:
        return app.invoke(turn_input, config=config)

    interrupts: Any = None
    decline_gate = _DeclineGate()
    # `subgraphs=True` is what makes `qa_node` stream at all: it is a compiled
    # subgraph, and without this its tokens never surface — the drain saw one
    # finished message at the node boundary and the typewriter effect never ran
    # for the product's main answering node. It also changes the yielded shape
    # to (namespace, mode, chunk).
    for namespace, mode, chunk in app.stream(
        turn_input, config=config, stream_mode=["updates", "messages", "tasks"], subgraphs=True
    ):
        # Progress is a top-level concern: a phase key names a graph node, and a
        # subgraph's internal steps are not steps the user tracks.
        if mode in {"updates", "tasks"} and namespace:
            continue

        if mode == "tasks":
            # `updates` only fires once a node has FINISHED, so a UI built on it
            # can say "this step is done" and nothing else — it would spin on a
            # step that already ended while the one actually running stayed
            # unannounced. `tasks` reports both edges of every node.
            node_name = chunk.get("name")
            phase_key = PHASE_KEY_BY_NODE.get(str(node_name))
            if not phase_key:
                continue
            if "result" in chunk or "error" in chunk:
                facts = phase_facts(str(node_name), _task_result_update(chunk))
                emit_phase(phase_key, status="completed", **facts)
                # Only the completed edge is kept: the stored trace is what the
                # turn DID, and a step that opened carries nothing to describe.
                record_step(phase_key, facts)
            else:
                # No facts on the opening edge: the node has not returned yet,
                # and `input` is the state going in, not what this step found.
                emit_phase(phase_key, status="started")
        elif mode == "updates":
            # Kept solely for interrupts. Phase frames come from `tasks` now;
            # emitting here too would double every step.
            for node_name, update in chunk.items():
                if node_name == "__interrupt__":
                    interrupts = update
        elif mode == "messages":
            message_chunk, metadata = chunk
            node = metadata.get("langgraph_node")
            if _may_stream(namespace, node):
                text = response_text(message_chunk)
                if node == "intake_qa":
                    text = decline_gate.feed(text)
                emit_delta(text)
                # The reasoning frame names its own step: it is sent while the
                # node runs, whereas the node's `phase` frame lands only once it
                # finishes, so position in the stream cannot identify it.
                reasoning_key = PHASE_KEY_BY_NODE.get(
                    str(namespace[0]).split(":", 1)[0] if namespace else str(node)
                )
                if reasoning_key:
                    emit_reasoning(reasoning_text(message_chunk), reasoning_key)

    # A held-back opening that turned out to be a real answer still has to be
    # sent; one that was the sentinel is dropped here and never seen.
    emit_delta(decline_gate.flush())

    result = dict(app.get_state(config).values or {})
    if interrupts:
        result["__interrupt__"] = interrupts
    return result


def _persist_turn(
    session_id: str, app, config: dict, thinking_trace: list[dict[str, Any]] | None = None
) -> None:
    """Write the turn's session row and transcript — best effort.

    The reply is already computed by the time this runs, so a database outage
    must cost a log line and nothing else; the same contract
    `supabase_persist_hook` held for the plane this replaces.

    State comes from `app.get_state(...)` rather than the `invoke()` result: a
    turn that stopped at `interrupt()` returns `__interrupt__` instead of the
    merged state, and that turn still needs persisting.

    Re-resolving the session through the registry keeps `_run_turn_via_graph`'s
    signature as it is; it is a dict lookup, since every caller resolved the
    same session moments ago. Runs inside the caller's `session.lock` — two
    concurrent turns on one session would otherwise race to rewrite the same
    transcript.
    """
    if not _persistence_enabled:
        return
    try:
        session = registry.get(session_id)
        if session is None:
            return
        session_store.persist_graph_session(
            session, app.get_state(config).values or {}, thinking_trace
        )
    except Exception:
        logger.exception("Unable to persist graph session %s; continuing in memory", session_id)


def _run_turn_via_graph(
    session_id: str,
    message: str,
    language: str,
    extra_state: dict | None = None,
    *,
    stream: bool = False,
) -> PlannerChatResponse:
    """Phase 7: a thread can be PAUSED at `interrupt()` (an ambiguous date --
    see `nodes/validate_patch.py`) from the previous turn. `get_state(...)
    .interrupts` is non-empty exactly then, and this turn's message must
    resume that paused node via `Command(resume=...)` rather than start a
    fresh turn -- which would re-run the pipeline from `load_context` and
    re-ask every slot already answered. A turn that itself pauses returns
    with `"__interrupt__"` in the result instead of `"response"` (`respond`
    never runs -- the graph stopped at `validate_patch`), so this builds the
    frozen response shape directly from the interrupt's own message.

    A resume reply that does NOT resolve the paused ambiguity (the user
    answered something else entirely, e.g. "thôi đổi điểm đến sang Huế"
    instead of naming a year) comes back with `unresolved_resume_text` set
    (see `nodes/validate_patch.py`) -- that text never reached
    `extract_patch` this turn (resuming re-executes only `validate_patch`,
    not the whole pipeline), so it is re-run here as one ordinary fresh
    turn. This is the fix for "a pending question isn't interruptible by a
    different intent" recreated one level down, inside the interrupt itself.

    `extra_state` (review finding F2) merges extra keys into this turn's
    `invoke()` input -- e.g. `selected_hotel_id` from `POST /hotels/select`,
    read deterministically by `hotel_node` rather than re-parsed out of the
    message text. Only applied on the fresh-turn path: a turn that resumes a
    paused `interrupt()` must resolve that ambiguity first, and threading a
    hotel pick through a resume is an edge case rare enough not to bother.

    `emit_phase("received")` (no-op on the plain POST path -- see
    `emit_phase`'s own no-emitter-bound guard) fires before anything else
    below: no graph_v2 node emits a `phase`/`delta` frame during an
    intake-stage turn (`extract_patch`'s LLM call is the graph's only slow
    step, and it is silent), so the client's `firstFrameTimeoutMs` (5s,
    `stream-client.ts`) previously had nothing to see but the filtered-out
    `: open` comment frame until `final` -- aborting the connection
    ("BodyStreamBuffer was aborted") on any turn whose extraction call ran
    past 5s, e.g. a compound "destination + dates + people + budget" message.
    """
    emit_phase("received")
    app = _get_graph_v2()
    config = {"configurable": {"thread_id": session_id}}

    with collecting_trace() as trace:
        snapshot = app.get_state(config)
        if snapshot.interrupts:
            result = _drive_turn(app, config, Command(resume=message), stream=stream)
            unresolved = result.get("unresolved_resume_text")
            if unresolved and "__interrupt__" not in result:
                result = _drive_turn(
                    app, config, _fresh_turn_input(session_id, unresolved, language, extra_state), stream=stream
                )
        else:
            result = _drive_turn(
                app, config, _fresh_turn_input(session_id, message, language, extra_state), stream=stream
            )

    # Before the interrupt branch below, so a turn that pauses waiting on a
    # clarification is persisted too — that exchange happened and must survive
    # a reload like any other.
    _persist_turn(session_id, app, config, trace)

    return _response_from_result(session_id, result)


def _response_from_result(session_id: str, result: dict) -> PlannerChatResponse:
    """Turn a graph result into the wire response.

    Shared by both graph entry points (`_run_turn_via_graph` and
    `change_hotel`'s `Command(goto=...)`) rather than copied into each: a turn
    that stops at `interrupt()` returns `__interrupt__` in place of
    `response` — `respond` never ran — and two copies of that branch would
    drift the first time either entry point changed.
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value or {}
        return PlannerChatResponse(session_id=session_id, reply=str(payload.get("message", "")), stage="intake")

    return PlannerChatResponse(**result["response"])


# ---------------------------------------------------------------------------
# Suggestion chips (plan 260819-1554-llm-grounded-chat-suggestions)
# ---------------------------------------------------------------------------

#: Only these workers can leave a turn with something worth grounding a chip
#: in (a hotel card, a trip plan, a budget verdict). `qa_node` writes no
#: `task_results` entry at all (see its own docstring), and `scope_guard`
#: writes one this set simply excludes -- both are unreachable here
#: regardless of `_SKIP_STATUSES` below.
_SUGGESTION_WORKERS = frozenset({"hotel_node", "itinerary_node", "budget_check", "booking_node"})

#: Statuses that mean "this worker ran but produced nothing to ground a
#: suggestion in" (validation decision #6: no card, no trip -> a chip would
#: have to invent one) OR "the reply carries state a chip could not actually
#: act on" (`already_paid`: hotel_node's own paid-booking lock, `hotel_node.py`
#: -- any "đổi/lọc khách sạn" chip would just get refused again). Deliberately
#: narrow: a business-outcome status like `over_budget`/`no_results` still has
#: real destination/dates/filters to ground a chip in, and is NOT in this set.
_SKIP_STATUSES = frozenset(
    {
        "no_destination",
        "unknown_destination",
        "error",
        "partial_error",
        "declined",
        "blocked",
        "hotel_selection_failed",
        "already_paid",
    }
)


def _suggestion_context(app, config: dict, response: PlannerChatResponse) -> SuggestionContext | None:
    """Grounding data for this turn's suggestion chips, or `None` when the
    turn doesn't qualify (no gated worker ran, or it ran but hit a status in
    `_SKIP_STATUSES`).

    MUST be called while still holding `session.lock` (see `_run_turn`
    below): `app.get_state(config)` reads the checkpointer's current
    snapshot, and outside the lock a concurrent turn on the same session
    could have already advanced it past the state this `response` was built
    from.
    """
    state = app.get_state(config).values or {}
    last_worker = last_worker_from_task_results(state)
    if last_worker is None:
        return None
    worker, status = last_worker
    if worker not in _SUGGESTION_WORKERS or status in _SKIP_STATUSES:
        return None

    hotel_cards = tuple(
        SuggestionHotelCard(
            name=option.name,
            price=option.average_nightly_price,
            review_score=option.review_score,
        )
        for option in response.hotel_options
    )
    language = str(state.get("language") or "vi")
    amenity_labels = tuple(
        amenity.label_en if language == "en" else amenity.label_vi for amenity in response.hotel_amenities
    )
    active_filter_labels = tuple(preference.label for preference in response.active_preferences)

    return SuggestionContext(
        worker=worker,
        status=status,
        reply=response.reply,
        language=language,
        destination=response.intake.destination if response.intake else None,
        hotel_cards=hotel_cards,
        hotel_amenity_labels=amenity_labels,
        active_filter_labels=active_filter_labels,
        trip_duration_days=response.trip_plan.duration_days if response.trip_plan else None,
    )


@router.post("/planner_chat", response_model=PlannerChatResponse)
@router.post("/chat", response_model=PlannerChatResponse)
def planner_chat(
    request: PlannerChatRequest, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> PlannerChatResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = _owned_session_or_404(session_id, current_user)

    with session.lock:
        try:
            return _run_turn_via_graph(session_id, request.message, request.language)
        except Exception:
            logger.exception("Unexpected error in planner_chat for session %s", session_id)
            raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")


def _run_stream_turn(
    session,
    session_id: str,
    message: str,
    language: str,
    emitter: TurnEmitter,
    *,
    extra_state: dict | None = None,
) -> None:
    """The whole worker-thread body of one `POST /planner_chat/stream` turn.

    A top-level function (not a closure inside the endpoint) so it can be
    driven directly in tests the same way `test_stream_modes.py`'s
    `streaming_turn` fixture drives `_run_turn_via_graph` -- bind a
    `_RecordingEmitter` via `emitting_to`, call this, inspect `emitter.frames`.
    No behavior change from being a closure: still runs inside
    `loop.run_in_executor(None, ...)`, still the sole writer to `emitter`.

    `extra_state` is never set by the real endpoint (`PlannerChatRequest` has
    no such field) -- it exists purely as a test seam, the same shape
    `_run_turn_via_graph` already exposes for `change_hotel`'s entry point.
    """
    try:
        with emitting_to(emitter), session.lock:
            response = _run_turn_via_graph(
                session_id, message, language, extra_state, stream=True
            )
            # Read while still holding the lock (see `_suggestion_context`'s
            # docstring) -- cheap, no LLM call yet. Guarded on its own: a
            # failure here must never block `final` below from going out, the
            # turn's reply is already computed by this point.
            suggestion_context = None
            try:
                config = {"configurable": {"thread_id": session_id}}
                suggestion_context = _suggestion_context(_get_graph_v2(), config, response)
            except Exception:
                logger.exception(
                    "Unexpected error building suggestion context for session %s", session_id
                )

        # `final` goes out before anything below runs: the reply must never
        # wait on the suggestion LLM call (plan
        # 260819-1554-llm-grounded-chat-suggestions, decision #3).
        emitter.emit("final", **response.model_dump(mode="json"))

        if suggestion_context is not None:
            try:
                chips = generate_next_chat_suggestions(suggestion_context)
                # Empty is a valid, designed outcome (LLM failed/timed out/
                # returned nothing) -- no frame at all, not an empty one.
                if chips:
                    emitter.emit(
                        "suggestions",
                        session_id=session_id,
                        suggestions=[{"label": text, "value": text} for text in chips],
                    )
            except Exception:
                # A broken suggestion step must not take the stream down --
                # `final` already went out and `close()` below still runs.
                logger.exception("Unexpected error generating suggestions for session %s", session_id)
    except Exception:
        logger.exception("Unexpected error in planner_chat_stream for session %s", session_id)
        emitter.emit("error", detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")
    finally:
        emitter.close()


@router.post("/planner_chat/stream")
async def planner_chat_stream(
    request: PlannerChatRequest, current_user: AuthenticatedUser | None = Depends(get_current_user)
) -> StreamingResponse:
    session_id = str(request.session_id)
    registry.evict_expired()
    session = _owned_session_or_404(session_id, current_user)

    loop = asyncio.get_running_loop()
    emitter = TurnEmitter(loop)

    loop.run_in_executor(
        None, _run_stream_turn, session, session_id, request.message, request.language, emitter
    )

    return StreamingResponse(
        sse_stream(emitter),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def agent_status():
    """Kiểm tra trạng thái agent."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}


@router.get("/search_attractions")
async def search_attractions(q: str, k: int = 10):
    """Tìm kiếm semantic cho attractions sử dụng Supabase RPC."""
    try:
        from src.services.supabase_search import search_attractions as rpc_search_attractions

        results = rpc_search_attractions(q, match_count=k)

        search_results = []
        for a in results:
            if a.get("id"):
                search_results.append(
                    {
                        "id": str(a["id"]),
                        "score": float(a.get("similarity", 0.0)),
                        "name": a.get("name"),
                        "category": a.get("category"),
                    }
                )

        return {"status": "success", "results": search_results}
    except Exception:
        logger.exception("search_attractions error")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")


@router.get("/search_hotels")
async def search_hotels(q: str, k: int = 5):
    """Tìm kiếm semantic cho hotels và rooms sử dụng Supabase RPC."""
    try:
        from src.services.supabase_search import search_hotels_with_rooms

        results = search_hotels_with_rooms(q, match_count=k)

        search_results = []
        for h in results:
            if h.get("id"):
                matched_rooms_dict = {}
                for idx, r_name in enumerate(h.get("matched_room_names") or []):
                    matched_rooms_dict[f"room_{idx}"] = r_name

                search_results.append(
                    {
                        "id": str(h["id"]),
                        "score": float(h.get("similarity", 0.0)),
                        "name": h.get("name"),
                        "star_rating": h.get("star_rating"),
                        "matched_rooms": matched_rooms_dict,
                        "matched_room_names": h.get("matched_room_names") or [],
                    }
                )

        return {"status": "success", "results": search_results}
    except Exception:
        logger.exception("search_hotels error")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi máy chủ. Vui lòng thử lại.")
