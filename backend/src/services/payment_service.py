"""Payment-record CRUD (plan 260818-vnpay-payment-and-email-confirmation).

Deterministic, service-role-only — same posture as booking_service.py.
Unlike bookings' create_booking_reservation (which needs an advisory lock
because two DIFFERENT guests can race for the same room), a payment row
only ever has one writer racing itself: VNPay's own IPN retries for the
SAME payment_id. A plain conditional UPDATE ("... WHERE status = 'PENDING'")
is enough — Postgres's row-level UPDATE is atomic, and a retry that
affects 0 rows (status already flipped by the first successful call) IS
the idempotency guard, surfaced here as mark_payment_paid/mark_payment_failed
returning None.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from src.clients.supabase_client import get_supabase_client


class PaymentError(RuntimeError):
    """A safe domain error suitable for conversion to an HTTP 404/409."""


def create_payment(
    *,
    booking_ids: list[UUID],
    temporary_user_ref: str,
    amount: Decimal,
    currency: str,
    guest_name: str,
    guest_email: str,
    guest_phone: str | None,
) -> dict[str, Any]:
    response = (
        get_supabase_client()
        .table("payments")
        .insert({
            "booking_ids": [str(b) for b in booking_ids],
            "temporary_user_ref": temporary_user_ref,
            "amount": str(amount),
            "currency": currency,
            "guest_name": guest_name,
            "guest_email": guest_email,
            "guest_phone": guest_phone,
            "status": "PENDING",
        })
        .execute()
    )
    if not response.data:
        raise PaymentError("payment_create_failed")
    return dict(response.data[0])


def get_payment(payment_id: UUID) -> dict[str, Any] | None:
    response = (
        get_supabase_client().table("payments").select("*").eq("id", str(payment_id)).limit(1).execute()
    )
    return dict(response.data[0]) if response.data else None


def get_payment_for_owner(payment_id: UUID, temporary_user_ref: str) -> dict[str, Any] | None:
    """Same "don't leak which one it was" posture as booking_service's
    ownership check — a wrong ref and a missing payment look identical to
    the caller."""
    payment = get_payment(payment_id)
    if payment is None or payment.get("temporary_user_ref") != temporary_user_ref:
        return None
    return payment


def mark_payment_paid(
    *, payment_id: UUID, vnp_transaction_no: str, vnp_response_code: str
) -> dict[str, Any] | None:
    """Conditional UPDATE — returns None if the row wasn't PENDING (already
    PAID/FAILED), which is exactly the idempotency guard an IPN retry needs.
    Callers must treat None as "already processed", not as an error."""
    response = (
        get_supabase_client()
        .table("payments")
        .update({
            "status": "PAID",
            "vnp_transaction_no": vnp_transaction_no,
            "vnp_response_code": vnp_response_code,
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", str(payment_id))
        .eq("status", "PENDING")
        .execute()
    )
    return dict(response.data[0]) if response.data else None


def booking_summary_for_email(booking_id: UUID) -> dict[str, Any] | None:
    """hotel name + stay dates for ONE booking in a payment's group, for the
    confirmation email (email_service.py) — `payments` doesn't store the
    hotel name itself, and `bookings` only has `room_id`, so this joins
    bookings -> rooms -> hotels the same way place_details.py's other
    hotel/room lookups already do. Only the first booking in a payment
    group's needed (they all share one hotel, since a hold is always for a
    single hotel — see use-room-hold.ts)."""
    client = get_supabase_client()
    booking_rows = (
        client.table("bookings")
        .select("room_id, check_in_date, check_out_date")
        .eq("id", str(booking_id))
        .limit(1)
        .execute()
        .data
    )
    if not booking_rows:
        return None
    room_id = booking_rows[0]["room_id"]

    room_rows = client.table("rooms").select("hotel_id").eq("id", room_id).limit(1).execute().data
    if not room_rows:
        return None
    hotel_id = room_rows[0]["hotel_id"]

    hotel_rows = client.table("hotels").select("name").eq("id", hotel_id).limit(1).execute().data
    hotel_name = hotel_rows[0]["name"] if hotel_rows else None

    return {
        "hotel_name": hotel_name,
        "check_in_date": booking_rows[0]["check_in_date"],
        "check_out_date": booking_rows[0]["check_out_date"],
    }


def get_payment_for_booking_ids(booking_ids: list[UUID]) -> dict[str, Any] | None:
    """The PAID payment covering any of these booking ids — used to recover
    a session's payment code/paid_at once the frontend's roomHold (its only
    other source for paymentId) has moved on to a different session's hold
    (see get_booking_receipt_for_session below). "PAID" only: a booking is
    CONFIRMED exclusively via the VNPay IPN handler after its payment
    succeeded (routes.py's vnpay_ipn), so a CONFIRMED booking always has
    exactly one PAID payment covering it — this never needs to disambiguate
    between several."""
    if not booking_ids:
        return None
    response = (
        get_supabase_client()
        .table("payments")
        .select("*")
        .overlaps("booking_ids", [str(b) for b in booking_ids])
        .eq("status", "PAID")
        .limit(1)
        .execute()
    )
    return dict(response.data[0]) if response.data else None


def get_booking_receipt_for_session(session_id: str) -> dict[str, Any] | None:
    """Full, read-only receipt (hotel, stay dates, room list, total, payment
    code) for a session's CONFIRMED booking(s) — the data source for
    "reopen a past session's booking" (frontend's booking-receipt-modal.tsx,
    routes.py's GET /chat/{session_id}/booking-receipt). Deliberately
    independent of the frontend's roomHold/hotelDetail: those only ever
    reflect whichever session most recently held/paid (use-room-hold.ts's
    module doc comment), so a guest revisiting an OLDER paid session needs
    this real backend lookup instead of trusting local state. None when the
    session has no CONFIRMED booking (never held anything, hold expired
    unpaid, or payment failed) — the route maps that to 404.

    A session's hold is always for a single hotel (use-room-hold.ts), so
    every CONFIRMED booking for one session_id shares one hotel and one
    stay (check-in/out dates) even when there's more than one room type —
    the first row's dates are used for the receipt as a whole."""
    client = get_supabase_client()
    booking_rows = (
        client.table("bookings")
        .select("id, room_id, check_in_date, check_out_date, room_count, total_amount, currency")
        .eq("session_id", session_id)
        .eq("status", "CONFIRMED")
        .execute()
        .data
        or []
    )
    if not booking_rows:
        return None

    room_ids = list({row["room_id"] for row in booking_rows})
    room_rows = (
        client.table("rooms").select("id, name, hotel_id").in_("id", room_ids).execute().data or []
    )
    room_by_id = {row["id"]: row for row in room_rows}

    hotel_id = next((row["hotel_id"] for row in room_rows if row.get("hotel_id")), None)
    hotel_name = None
    hotel_address = None
    if hotel_id:
        hotel_rows = client.table("hotels").select("name, address").eq("id", hotel_id).limit(1).execute().data
        if hotel_rows:
            hotel_name = hotel_rows[0].get("name")
            hotel_address = hotel_rows[0].get("address")

    booking_ids = [UUID(str(row["id"])) for row in booking_rows]
    payment = get_payment_for_booking_ids(booking_ids)

    currency = (
        next((row["currency"] for row in booking_rows if row.get("currency")), None)
        or (payment.get("currency") if payment else None)
        or "VND"
    )
    total_amount = (
        Decimal(str(payment["amount"]))
        if payment
        else sum(
            (Decimal(str(row["total_amount"])) for row in booking_rows if row.get("total_amount") is not None),
            Decimal("0"),
        )
    )

    rooms = [
        {
            "room_id": row["room_id"],
            "name": room_by_id.get(row["room_id"], {}).get("name") or row["room_id"],
            "room_count": row["room_count"],
            "total_amount": row.get("total_amount"),
        }
        for row in booking_rows
    ]

    return {
        "payment_id": payment["id"] if payment else None,
        "hotel_name": hotel_name,
        "hotel_address": hotel_address,
        "check_in_date": booking_rows[0]["check_in_date"],
        "check_out_date": booking_rows[0]["check_out_date"],
        "currency": currency,
        "total_amount": str(total_amount),
        "paid_at": payment.get("paid_at") if payment else None,
        "rooms": rooms,
    }


def mark_payment_failed(*, payment_id: UUID, vnp_response_code: str) -> dict[str, Any] | None:
    response = (
        get_supabase_client()
        .table("payments")
        .update({
            "status": "FAILED",
            "vnp_response_code": vnp_response_code,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", str(payment_id))
        .eq("status", "PENDING")
        .execute()
    )
    return dict(response.data[0]) if response.data else None
