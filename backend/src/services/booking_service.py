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
        raise BookingError("booking_operation_failed") from exc


def reserve_booking(
    *, room_id: UUID, temporary_user_ref: str, check_in_date: date,
    check_in_time: time, check_out_date: date, check_out_time: time,
    room_count: int, total_amount: Decimal | None, currency: str | None,
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
    })


def confirm_booking(*, booking_id: UUID, temporary_user_ref: str) -> dict[str, Any]:
    return _call("confirm_booking_reservation", {
        "p_booking_id": str(booking_id), "p_temporary_user_ref": temporary_user_ref,
    })


def cancel_booking(*, booking_id: UUID, temporary_user_ref: str) -> dict[str, Any]:
    return _call("cancel_booking", {
        "p_booking_id": str(booking_id), "p_temporary_user_ref": temporary_user_ref,
    })
