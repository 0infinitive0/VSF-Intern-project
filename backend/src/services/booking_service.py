"""Deterministic, service-role-only booking operations."""

from __future__ import annotations

import logging
from datetime import date, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.clients.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class BookingError(RuntimeError):
    """A safe domain error suitable for conversion to an HTTP 409/404."""


def _one_row(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        return dict(data[0])
    if isinstance(data, dict):
        return dict(data)
    raise BookingError("booking_operation_failed")


def _call(rpc_name: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return _one_row(get_supabase_client().rpc(rpc_name, params).execute())
    except BookingError:
        raise
    except Exception as exc:
        message = str(exc)
        if "insufficient_room_availability" in message:
            raise BookingError("insufficient_room_availability") from exc
        if "booking_reservation_expired" in message:
            raise BookingError("booking_reservation_expired") from exc
        if "booking_not_found" in message:
            raise BookingError("booking_not_found") from exc
        if "booking_not_confirmable" in message:
            raise BookingError("booking_not_confirmable") from exc
        # create_booking_reservation's own validation (bad date range,
        # room_count <= 0, hold_minutes out of [1, 60]) — the caller's
        # fault, not a server error. Was previously indistinguishable from
        # booking_operation_failed and surfaced as a bare 500.
        if "invalid_booking_request" in message:
            raise BookingError("invalid_booking_request") from exc
        # A different browser tab (same guest ref, shared via localStorage —
        # see frontend/src/lib/guest-ref.ts) already holds a live RESERVED
        # booking at a DIFFERENT hotel — create_booking_reservation's
        # cross-hotel guard (migration 20260819_add_guest_single_hotel_hold_
        # guard.sql). Rejected, not auto-resolved: the other tab's hold is
        # left untouched.
        if "guest_already_holding_elsewhere" in message:
            raise BookingError("guest_already_holding_elsewhere") from exc
        raise BookingError("booking_operation_failed") from exc


def reserve_booking(
    *, room_id: UUID, temporary_user_ref: str, check_in_date: date,
    check_in_time: time, check_out_date: date, check_out_time: time,
    room_count: int, total_amount: Decimal | None, currency: str | None,
    session_id: str | None = None,
) -> dict[str, Any]:
    return _call("create_booking_reservation", {
        "p_room_id": str(room_id),
        "p_temporary_user_ref": temporary_user_ref,
        "p_check_in_date": check_in_date.isoformat(),
        "p_check_in_time": check_in_time.isoformat(),
        "p_check_out_date": check_out_date.isoformat(),
        "p_check_out_time": check_out_time.isoformat(),
        "p_room_count": room_count,
        "p_total_amount": str(total_amount) if total_amount is not None else None,
        "p_currency": currency,
        "p_session_id": session_id,
    })


def confirm_booking(*, booking_id: UUID, temporary_user_ref: str) -> dict[str, Any]:
    return _call("confirm_booking_reservation", {
        "p_booking_id": str(booking_id), "p_temporary_user_ref": temporary_user_ref,
    })


def cancel_booking(*, booking_id: UUID, temporary_user_ref: str) -> dict[str, Any]:
    return _call("cancel_booking", {
        "p_booking_id": str(booking_id), "p_temporary_user_ref": temporary_user_ref,
    })


def cancel_reserved_bookings_for_session(session_id: str) -> int:
    """Cancels every still-RESERVED booking tied to `session_id` — called
    when a chat session is deleted (routes.py's delete_session), BEFORE the
    session row itself is deleted (bookings.session_id is ON DELETE SET
    NULL, not CASCADE — deleting the session first would null the FK out
    from under this lookup, losing the link to whatever it was still
    holding). Deliberately only ever touches RESERVED rows: a CONFIRMED
    booking is a real, paid transaction that must survive its chat session
    being deleted (the same reason the column isn't CASCADE).

    Doesn't rely on any frontend state to know which hold belongs to which
    session — the frontend's roomHold hook only ever tracks ONE hold, for
    whichever browser tab happens to be open at the time (see use-room-
    hold.ts's module doc comment); a hold started in a tab that's since
    been closed, or in a different tab entirely, is invisible to whichever
    tab the guest is deleting the session from. This is the deterministic,
    server-side source of truth instead, so deleting a session always
    actually frees the room(s) it held, independent of any tab.

    Best-effort per row: one failed cancel is logged and skipped rather
    than aborting the rest or blocking the session deletion that triggered
    this (cancel_booking is also idempotent, so a partially-cancelled batch
    from a retried delete is harmless).

    Returns the number of bookings cancelled (0 is the common case)."""
    response = (
        get_supabase_client()
        .table("bookings")
        .select("id,temporary_user_ref")
        .eq("session_id", session_id)
        .eq("status", "RESERVED")
        .execute()
    )
    rows = response.data or []
    cancelled = 0
    for row in rows:
        try:
            cancel_booking(booking_id=UUID(str(row["id"])), temporary_user_ref=row["temporary_user_ref"])
            cancelled += 1
        except Exception:
            logger.exception(
                "Unable to cancel booking %s while deleting session %s", row.get("id"), session_id
            )
    return cancelled


def get_booking(booking_id: UUID) -> dict[str, Any] | None:
    """Plain read, no RPC needed — a SELECT has no race to guard against.
    Used by the VNPay payment-creation route (plan
    260818-vnpay-payment-and-email-confirmation) to verify each booking in a
    checkout attempt is still RESERVED and unexpired, and to total their
    `total_amount` before charging."""
    response = (
        get_supabase_client().table("bookings").select("*").eq("id", str(booking_id)).limit(1).execute()
    )
    return dict(response.data[0]) if response.data else None
