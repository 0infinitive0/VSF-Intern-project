"""Booking confirmation email (plan 260818-vnpay-payment-and-email-confirmation).

Sent once from routes.py's VNPay IPN handler, right after a payment's
bookings are confirmed — never before, since a bounced/failed email must
never be mistaken for a bounced payment. Callers should catch EmailError and
log-and-continue rather than let an email-provider outage fail the
confirmation itself: by the time this runs, the booking is already CONFIRMED
and the guest has already paid — losing the email is a real but much
smaller problem than losing/duplicating the payment confirmation would be.

Sends through Brevo's transactional email API (single-sender verification --
switched 2026-08-26 from Resend, whose free sandbox sender
(onboarding@resend.dev) can only deliver to the Resend account owner's own
verified email; sending to any real guest silently failed. Brevo's
equivalent free tier only requires verifying ONE sender address (a
confirmation-link click in the Brevo dashboard, config.brevo_from_email),
not a whole domain with DNS records, and then delivers to any recipient).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

_BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class EmailError(RuntimeError):
    """Brevo rejected the request, or isn't configured at all."""


def _money(amount: Decimal | None, currency: str | None) -> str | None:
    if amount is None or not currency:
        return None
    return f"{amount:,.0f} {currency}".replace(",", ".")


def _room_rows_html(rooms: list[dict[str, Any]], currency: str | None) -> str:
    """Table-based (not flex/grid — see module note below) list of the rooms
    in this booking, one row per room type: thumbnail, name + qty, price."""
    cells = []
    for room in rooms:
        image_url = room.get("image_url")
        price = _money(room.get("total_amount"), currency)
        thumb = (
            f'<img src="{image_url}" width="56" height="56" alt="" '
            f'style="width:56px;height:56px;border-radius:10px;object-fit:cover;background:#f3f5fa;display:block" />'
            if image_url
            else '<div style="width:56px;height:56px;border-radius:10px;background:#f3f5fa"></div>'
        )
        cells.append(
            "<tr>"
            f'<td style="padding:8px 0;width:56px">{thumb}</td>'
            '<td style="padding:8px 0 8px 12px;color:#15181c;font-size:13px;font-weight:600">'
            f'{room.get("name", "")}<div style="color:#8a8f99;font-weight:400;font-size:12px;margin-top:2px">'
            f'x{room.get("room_count", 1)}</div></td>'
            f'<td style="padding:8px 0;text-align:right;color:#15181c;font-size:13px;font-weight:600;vertical-align:top">{price or ""}</td>'
            "</tr>"
        )
    return "".join(cells)


def _confirmation_html(
    *,
    guest_name: str,
    hotel_name: str,
    hotel_image_url: str | None,
    booking_code: str,
    check_in_date: str,
    check_out_date: str,
    rooms: list[dict[str, Any]],
    currency: str | None,
    amount_line: str | None,
) -> str:
    rows = [
        ("Khách sạn", hotel_name),
        ("Nhận phòng", check_in_date),
        ("Trả phòng", check_out_date),
    ]
    rows_html = "".join(
        f'<tr><td style="padding:10px 0;color:#60646c;font-size:13px;border-bottom:1px solid #f1f4f9">{label}</td>'
        f'<td style="padding:10px 0;text-align:right;font-weight:600;color:#15181c;font-size:13px;border-bottom:1px solid #f1f4f9">{value}</td></tr>'
        for label, value in rows
    )
    greeting = f"Chào {guest_name}," if guest_name else "Xin chào,"
    hero_html = (
        f'<img src="{hotel_image_url}" width="496" alt="" '
        'style="width:100%;max-width:496px;height:200px;object-fit:cover;border-radius:18px;display:block;margin-bottom:24px" />'
        if hotel_image_url
        else ""
    )
    room_rows_html = _room_rows_html(rooms, currency)
    rooms_section_html = (
        f"""
  <div style="margin-top:22px">
    <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8a8f99;font-weight:600;margin-bottom:6px">Phòng đã đặt</div>
    <table style="width:100%;border-collapse:collapse;border-top:1px solid #e6eaf5">{room_rows_html}</table>
  </div>"""
        if room_rows_html
        else ""
    )

    amount_display = amount_line or "—"

    return f"""
<div style="background-color:#f4f6fa;padding:32px 12px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:22px;border:1px solid #e2e8f0;padding:28px 24px;box-shadow:0 8px 30px rgba(0,0,0,0.04)">
    {hero_html}
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px">
      <tr>
        <td style="vertical-align:middle">
          <div style="width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#5C93EE,#2C5FC9);
                      color:#fff;line-height:44px;text-align:center;font-weight:700;font-size:18px">V</div>
        </td>
        <td style="text-align:right;vertical-align:middle">
          <span style="display:inline-block;padding:6px 14px;border-radius:99px;background:#e8f7f5;color:#1f6f67;font-size:12px;font-weight:600">
            ✓ Đã xác nhận
          </span>
        </td>
      </tr>
    </table>
    <h1 style="font-size:22px;font-weight:700;margin:0 0 6px;color:#15181c;letter-spacing:-0.3px">Đặt phòng đã được xác nhận</h1>
    <p style="color:#60646c;font-size:14px;line-height:1.5;margin:0 0 20px">{greeting} thanh toán của bạn đã thành công và đặt phòng đã được xác nhận với khách sạn.</p>
    
    <table style="width:100%;border-collapse:collapse;margin:20px 0;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
      <tr>
        <td style="padding:14px 16px;width:50%;text-align:center;border-right:1px solid #e2e8f0;vertical-align:middle">
          <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#737885;font-weight:600">Mã đặt phòng</div>
          <div style="font-size:18px;font-weight:700;letter-spacing:.03em;color:#15181c;margin-top:3px">{booking_code}</div>
        </td>
        <td style="padding:14px 16px;width:50%;text-align:center;vertical-align:middle">
          <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#737885;font-weight:600">Tổng cộng</div>
          <div style="font-size:18px;font-weight:700;color:#2C5FC9;margin-top:3px">{amount_display}</div>
        </td>
      </tr>
    </table>

    <table style="width:100%;border-collapse:collapse;border-top:1px solid #e6eaf5;margin-top:8px">{rows_html}</table>{rooms_section_html}

    <p style="color:#8a8f99;font-size:12px;margin-top:28px;text-align:center;line-height:1.5">V‑OTA Travel · Email này được gửi tự động, vui lòng không trả lời trực tiếp.</p>
  </div>
</div>
""".strip()


def send_booking_confirmation_email(
    *,
    to_email: str,
    guest_name: str,
    hotel_name: str,
    hotel_image_url: str | None = None,
    booking_code: str,
    check_in_date: str,
    check_out_date: str,
    rooms: list[dict[str, Any]] | None = None,
    total_amount: Decimal | None,
    currency: str | None,
) -> str:
    """Sends the confirmation email; returns Brevo's message id.

    Raises EmailError on any failure (not configured, Brevo API error) —
    the caller decides whether to swallow it (see the module doc comment)."""
    settings = get_settings()
    if not settings.brevo_api_key or not settings.brevo_from_email:
        raise EmailError("brevo_not_configured")

    amount_line = _money(total_amount, currency)
    html = _confirmation_html(
        guest_name=guest_name,
        hotel_name=hotel_name,
        hotel_image_url=hotel_image_url,
        booking_code=booking_code,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        rooms=rooms or [],
        currency=currency,
        amount_line=amount_line,
    )

    try:
        response = httpx.post(
            _BREVO_SEND_URL,
            headers={
                "api-key": settings.brevo_api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
            json={
                "sender": {"email": settings.brevo_from_email, "name": "VP-OTA"},
                "to": [{"email": to_email}],
                "subject": f"Xác nhận đặt phòng {booking_code} — VP-OTA",
                "htmlContent": html,
            },
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmailError(str(exc)) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise EmailError("brevo_invalid_response") from exc
    message_id = data.get("messageId") if isinstance(data, dict) else None
    if not message_id:
        raise EmailError("brevo_no_message_id")
    return message_id
