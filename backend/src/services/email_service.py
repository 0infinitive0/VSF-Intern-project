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
from typing import Any

import resend

from src.config import get_settings

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """Resend rejected the request, or isn't configured at all."""


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
        f'<tr><td style="padding:8px 0;color:#60646c;font-size:13px">{label}</td>'
        f'<td style="padding:8px 0;text-align:right;font-weight:600;color:#15181c;font-size:13px">{value}</td></tr>'
        for label, value in rows
    )
    greeting = f"Chào {guest_name}," if guest_name else "Xin chào,"
    # Email-client HTML note: flexbox (display:flex) isn't reliably supported
    # across email clients (esp. Outlook desktop, which renders with Word's
    # engine) — the "V" logo badge below is centered with line-height +
    # text-align instead, and the room list is a <table>, not flex/grid.
    hero_html = (
        f'<img src="{hotel_image_url}" width="432" alt="" '
        'style="width:100%;max-width:432px;height:160px;object-fit:cover;border-radius:16px;display:block;margin-bottom:20px" />'
        if hotel_image_url
        else ""
    )
    room_rows_html = _room_rows_html(rooms, currency)
    rooms_section_html = (
        f"""
  <div style="margin-top:20px">
    <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8a8f99;margin-bottom:4px">Phòng đã đặt</div>
    <table style="width:100%;border-collapse:collapse;border-top:1px solid #e6eaf5">{room_rows_html}</table>
  </div>"""
        if room_rows_html
        else ""
    )
    total_html = (
        f"""
  <div style="margin-top:16px;padding-top:12px;border-top:1px solid #e6eaf5;display:table;width:100%">
    <span style="color:#60646c;font-size:13px">Tổng cộng</span>
    <span style="float:right;font-weight:600;color:#15181c;font-size:15px">{amount_line}</span>
  </div>"""
        if amount_line
        else ""
    )
    return f"""
<div style="font-family:-apple-system,'Segoe UI',sans-serif;max-width:480px;margin:0 auto;padding:32px 24px">
  {hero_html}
  <div style="width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#5C93EE,#2C5FC9);
              color:#fff;line-height:44px;text-align:center;font-weight:600;font-size:18px">V</div>
  <h1 style="font-size:20px;margin:20px 0 4px;color:#15181c">Đặt phòng đã được xác nhận</h1>
  <p style="color:#60646c;font-size:14px;line-height:1.5">{greeting} thanh toán của bạn đã thành công và đặt phòng đã được xác nhận.</p>
  <div style="margin:20px 0;padding:14px 16px;border-radius:14px;background:#f3f5fa">
    <div style="font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#8a8f99">Mã đặt phòng</div>
    <div style="font-size:18px;font-weight:600;letter-spacing:.03em;color:#15181c;margin-top:2px">{booking_code}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;border-top:1px solid #e6eaf5">{rows_html}</table>{rooms_section_html}{total_html}
  <p style="color:#8a8f99;font-size:12px;margin-top:28px">V‑OTA · Email này được gửi tự động, vui lòng không trả lời trực tiếp.</p>
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
    """Sends the confirmation email; returns Resend's message id.

    Raises EmailError on any failure (not configured, Resend API error) —
    the caller decides whether to swallow it (see the module doc comment)."""
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailError("resend_not_configured")

    resend.api_key = settings.resend_api_key
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
