"""Deterministic, service-role-only booking operations."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.clients.supabase_client import get_supabase_client


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
