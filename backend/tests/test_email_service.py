"""email_service.send_booking_confirmation_email / _confirmation_html —
covers the room-list + hotel hero image + logo-centering fix added alongside
the payment-success modal redesign (booking-modal.tsx's 'done' step), and
(from 2026-08-26) sending through Brevo's HTTP API rather than Resend --
see email_service.py's module doc comment for why."""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from src.config import get_settings
from src.services import email_service


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _brevo_response(status_code: int, body: dict | None = None) -> httpx.Response:
    """Mirrors test_airflow_client.py's `_response` helper -- a real
    `httpx.Response` so `.raise_for_status()`/`.json()` behave exactly as
    they would against the genuine API, not a hand-rolled stand-in."""
    request = httpx.Request("POST", email_service._BREVO_SEND_URL)
    if body is None:
        return httpx.Response(status_code, request=request)
    return httpx.Response(status_code, json=body, request=request)


def test_confirmation_html_has_no_flexbox_and_centers_logo_with_line_height():
    html = email_service._confirmation_html(
        guest_name="An",
        hotel_name="Khách sạn Biển Xanh",
        hotel_image_url=None,
        booking_code="ABCD1234",
        check_in_date="2026-09-01",
        check_out_date="2026-09-03",
        rooms=[],
        currency="VND",
        amount_line="1.600.000 VND",
    )

    assert "display:flex" not in html
    assert "line-height:44px" in html
    assert "text-align:center" in html


def test_confirmation_html_includes_hero_image_when_hotel_image_url_given():
    html = email_service._confirmation_html(
        guest_name="An",
        hotel_name="Khách sạn Biển Xanh",
        hotel_image_url="https://img/hotel.jpg",
        booking_code="ABCD1234",
        check_in_date="2026-09-01",
        check_out_date="2026-09-03",
        rooms=[],
        currency="VND",
        amount_line=None,
    )

    assert '<img src="https://img/hotel.jpg"' in html


def test_confirmation_html_omits_hero_image_when_no_hotel_image_url():
    html = email_service._confirmation_html(
        guest_name="An",
        hotel_name="Khách sạn Biển Xanh",
        hotel_image_url=None,
        booking_code="ABCD1234",
        check_in_date="2026-09-01",
        check_out_date="2026-09-03",
        rooms=[],
        currency="VND",
        amount_line=None,
    )

    assert "<img" not in html


def test_confirmation_html_lists_every_room_with_name_qty_price_and_thumbnail():
    html = email_service._confirmation_html(
        guest_name="An",
        hotel_name="Khách sạn Biển Xanh",
        hotel_image_url=None,
        booking_code="ABCD1234",
        check_in_date="2026-09-01",
        check_out_date="2026-09-03",
        rooms=[
            {"name": "Superior", "image_url": "https://img/superior.jpg", "room_count": 2, "total_amount": Decimal("1000000")},
            {"name": "Deluxe", "image_url": None, "room_count": 1, "total_amount": Decimal("600000")},
        ],
        currency="VND",
        amount_line="1.600.000 VND",
    )

    assert "Superior" in html
    assert "x2" in html
    assert '<img src="https://img/superior.jpg"' in html
    assert "1.000.000 VND" in html
    assert "Deluxe" in html
    assert "x1" in html
    assert "600.000 VND" in html


def test_send_booking_confirmation_email_raises_when_not_configured(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "")
    monkeypatch.setenv("BREVO_FROM_EMAIL", "")
    get_settings.cache_clear()

    with pytest.raises(email_service.EmailError):
        email_service.send_booking_confirmation_email(
            to_email="guest@example.com",
            guest_name="An",
            hotel_name="Khách sạn Biển Xanh",
            booking_code="ABCD1234",
            check_in_date="2026-09-01",
            check_out_date="2026-09-03",
            total_amount=None,
            currency=None,
        )


def test_send_booking_confirmation_email_sends_html_with_rooms_and_hero(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    monkeypatch.setenv("BREVO_FROM_EMAIL", "sender@example.com")
    get_settings.cache_clear()

    sent = {}

    def _fake_post(url, *, headers=None, json=None, timeout=None):
        sent["url"] = url
        sent["headers"] = headers
        sent["json"] = json
        return _brevo_response(201, {"messageId": "msg_123"})

    monkeypatch.setattr(email_service.httpx, "post", _fake_post)

    message_id = email_service.send_booking_confirmation_email(
        to_email="guest@example.com",
        guest_name="An",
        hotel_name="Khách sạn Biển Xanh",
        hotel_image_url="https://img/hotel.jpg",
        booking_code="ABCD1234",
        check_in_date="2026-09-01",
        check_out_date="2026-09-03",
        rooms=[{"name": "Superior", "image_url": "https://img/superior.jpg", "room_count": 2, "total_amount": Decimal("1000000")}],
        total_amount=Decimal("1000000"),
        currency="VND",
    )

    assert message_id == "msg_123"
    assert sent["url"] == email_service._BREVO_SEND_URL
    assert sent["headers"]["api-key"] == "test-key"
    assert sent["json"]["sender"] == {"email": "sender@example.com", "name": "VP-OTA"}
    assert sent["json"]["to"] == [{"email": "guest@example.com"}]
    assert '<img src="https://img/hotel.jpg"' in sent["json"]["htmlContent"]
    assert "Superior" in sent["json"]["htmlContent"]


def test_send_booking_confirmation_email_raises_on_a_rejected_request(monkeypatch):
    """A real Brevo error response (e.g. the sender address isn't verified
    yet) must surface as EmailError, not an unhandled httpx exception."""
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    monkeypatch.setenv("BREVO_FROM_EMAIL", "sender@example.com")
    get_settings.cache_clear()

    monkeypatch.setattr(
        email_service.httpx,
        "post",
        lambda *_a, **_k: _brevo_response(401, {"code": "unauthorized", "message": "Key not found"}),
    )

    with pytest.raises(email_service.EmailError):
        email_service.send_booking_confirmation_email(
            to_email="guest@example.com",
            guest_name="An",
            hotel_name="Khách sạn Biển Xanh",
            booking_code="ABCD1234",
            check_in_date="2026-09-01",
            check_out_date="2026-09-03",
            total_amount=None,
            currency=None,
        )
