"""Booking confirmation email (plan 260818-vnpay-payment-and-email-confirmation).

Sent once from routes.py's VNPay IPN handler, right after a payment's
bookings are confirmed — never before, since a bounced/failed email must
never be mistaken for a bounced payment. Callers should catch EmailError and
log-and-continue rather than let a Resend outage fail the confirmation
itself: by the time this runs, the booking is already CONFIRMED and the
guest has already paid — losing the email is a real but much smaller
problem than losing/duplicating the payment confirmation would be.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import resend

from src.config import get_settings

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """Resend rejected the request, or isn't configured at all."""


def _confirmation_html(
    *,
    guest_name: str,
    hotel_name: str,
    booking_code: str,
    check_in_date: str,
    check_out_date: str,
    amount_line: str | None,
) -> str:
    rows = [
        ("Khách sạn", hotel_name),
        ("Nhận phòng", check_in_date),
        ("Trả phòng", check_out_date),
    ]
    if amount_line:
        rows.append(("Tổng cộng", amount_line))
    rows_html = "".join(
        f'<tr><td style="padding:8px 0;color:#60646c;font-size:13px">{label}</td>'
        f'<td style="padding:8px 0;text-align:right;font-weight:600;color:#15181c;font-size:13px">{value}</td></tr>'
        for label, value in rows
    )
    greeting = f"Chào {guest_name}," if guest_name else "Xin chào,"
    return f"""
<div style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
  <div style="width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#5C93EE,#2C5FC9);
              color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:18px">V</div>
  <h1 style="font-size:20px;margin:20px 0 4px;color:#15181c">Đặt phòng đã được xác nhận</h1>
  <p style="color:#60646c;font-size:14px;line-height:1.5">{greeting} thanh toán của bạn đã thành công và đặt phòng đã được xác nhận.</p>
  <div style="margin:20px 0;padding:14px 16px;border-radius:14px;background:#f3f5fa">
    <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8a8f99">Mã đặt phòng</div>
    <div style="font-size:18px;font-weight:600;letter-spacing:.03em;color:#15181c;margin-top:2px">{booking_code}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;border-top:1px solid #e6eaf5">{rows_html}</table>
  <p style="color:#8a8f99;font-size:12px;margin-top:28px">V‑OTA · Email này được gửi tự động, vui lòng không trả lời trực tiếp.</p>
</div>
""".strip()


def send_booking_confirmation_email(
    *,
    to_email: str,
    guest_name: str,
    hotel_name: str,
    booking_code: str,
    check_in_date: str,
    check_out_date: str,
    total_amount: Decimal | None,
    currency: str | None,
) -> str:
    """Sends the confirmation email; returns Resend's message id.

    Raises EmailError on any failure (not configured, Resend API error) —
    the caller decides whether to swallow it (see the module doc comment)."""
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailError("resend_not_configured")

    resend.api_key = settings.resend_api_key
    amount_line = (
        f"{total_amount:,.0f} {currency}".replace(",", ".")
        if total_amount is not None and currency
        else None
    )
    html = _confirmation_html(
        guest_name=guest_name,
        hotel_name=hotel_name,
        booking_code=booking_code,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        amount_line=amount_line,
    )

    try:
        response = resend.Emails.send({
            "from": settings.resend_from_email,
            "to": [to_email],
            "subject": f"Xác nhận đặt phòng {booking_code} — V-OTA",
            "html": html,
        })
    except Exception as exc:
        raise EmailError(str(exc)) from exc

    message_id = response.get("id") if isinstance(response, dict) else None
    if not message_id:
        raise EmailError("resend_no_message_id")
    return message_id
