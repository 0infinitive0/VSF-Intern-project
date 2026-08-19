"""payment_service.get_payment_for_booking_ids / get_booking_receipt_for_
session — the data source for "reopen a past session's booking" (plan
260818-vnpay-payment-and-email-confirmation's addendum 4)."""
from __future__ import annotations

from uuid import uuid4

from src.services import payment_service


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def overlaps(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return self

    @property
    def data(self):
        return self._rows


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables
        self.table_calls: list[str] = []

    def table(self, name):
        self.table_calls.append(name)
        return _FakeQuery(self._tables.get(name, []))


_ROOM_A = str(uuid4())
_ROOM_B = str(uuid4())
_HOTEL_ID = str(uuid4())
_BOOKING_1 = str(uuid4())
_BOOKING_2 = str(uuid4())
_PAYMENT_ID = str(uuid4())


def test_get_payment_for_booking_ids_short_circuits_on_empty_list(monkeypatch):
    def _unreachable():
        raise AssertionError("get_supabase_client should not be called for an empty list")

    monkeypatch.setattr(payment_service, "get_supabase_client", _unreachable)

    assert payment_service.get_payment_for_booking_ids([]) is None


def test_get_payment_for_booking_ids_returns_the_matching_payment(monkeypatch):
    client = _FakeClient({"payments": [{"id": _PAYMENT_ID, "status": "PAID"}]})
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    result = payment_service.get_payment_for_booking_ids([_BOOKING_1])

    assert result == {"id": _PAYMENT_ID, "status": "PAID"}
    assert client.table_calls == ["payments"]


def test_get_payment_for_booking_ids_returns_none_when_not_found(monkeypatch):
    client = _FakeClient({"payments": []})
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    assert payment_service.get_payment_for_booking_ids([_BOOKING_1]) is None


def test_get_booking_receipt_for_session_returns_none_with_no_confirmed_bookings(monkeypatch):
    client = _FakeClient({"bookings": []})
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    assert payment_service.get_booking_receipt_for_session("session-1") is None


def test_get_booking_receipt_for_session_assembles_hotel_rooms_and_payment(monkeypatch):
    tables = {
        "bookings": [
            {
                "id": _BOOKING_1,
                "room_id": _ROOM_A,
                "check_in_date": "2026-09-01",
                "check_out_date": "2026-09-03",
                "room_count": 2,
                "total_amount": "1000000",
                "currency": "VND",
            },
            {
                "id": _BOOKING_2,
                "room_id": _ROOM_B,
                "check_in_date": "2026-09-01",
                "check_out_date": "2026-09-03",
                "room_count": 1,
                "total_amount": "600000",
                "currency": "VND",
            },
        ],
        "rooms": [
            {"id": _ROOM_A, "name": "Superior", "hotel_id": _HOTEL_ID},
            {"id": _ROOM_B, "name": "Deluxe", "hotel_id": _HOTEL_ID},
        ],
        "hotels": [{"name": "Khách sạn Biển Xanh", "address": "123 Trần Phú"}],
        "payments": [
            {
                "id": _PAYMENT_ID,
                "amount": "1600000",
                "currency": "VND",
                "status": "PAID",
                "paid_at": "2026-09-01T10:00:00+00:00",
            }
        ],
    }
    client = _FakeClient(tables)
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    receipt = payment_service.get_booking_receipt_for_session("session-1")

    assert receipt is not None
    assert receipt["payment_id"] == _PAYMENT_ID
    assert receipt["hotel_name"] == "Khách sạn Biển Xanh"
    assert receipt["hotel_address"] == "123 Trần Phú"
    assert receipt["check_in_date"] == "2026-09-01"
    assert receipt["check_out_date"] == "2026-09-03"
    assert receipt["currency"] == "VND"
    assert receipt["total_amount"] == "1600000"
    assert receipt["paid_at"] == "2026-09-01T10:00:00+00:00"
    assert {(r["name"], r["room_count"]) for r in receipt["rooms"]} == {("Superior", 2), ("Deluxe", 1)}


def test_booking_summary_for_email_short_circuits_on_empty_list(monkeypatch):
    def _unreachable():
        raise AssertionError("get_supabase_client should not be called for an empty list")

    monkeypatch.setattr(payment_service, "get_supabase_client", _unreachable)

    assert payment_service.booking_summary_for_email([]) is None


def test_booking_summary_for_email_returns_none_when_bookings_not_found(monkeypatch):
    client = _FakeClient({"bookings": []})
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    assert payment_service.booking_summary_for_email([_BOOKING_1]) is None


def test_booking_summary_for_email_assembles_hotel_image_and_every_room(monkeypatch):
    tables = {
        "bookings": [
            {
                "id": _BOOKING_1,
                "room_id": _ROOM_A,
                "check_in_date": "2026-09-01",
                "check_out_date": "2026-09-03",
                "room_count": 2,
                "total_amount": "1000000",
            },
            {
                "id": _BOOKING_2,
                "room_id": _ROOM_B,
                "check_in_date": "2026-09-01",
                "check_out_date": "2026-09-03",
                "room_count": 1,
                "total_amount": "600000",
            },
        ],
        "rooms": [
            {"id": _ROOM_A, "name": "Superior", "hotel_id": _HOTEL_ID, "images": ["https://img/superior.jpg"]},
            {"id": _ROOM_B, "name": "Deluxe", "hotel_id": _HOTEL_ID, "images": []},
        ],
        "hotels": [
            {"name": "Khách sạn Biển Xanh", "address": "123 Trần Phú", "image_url": "https://img/hotel.jpg"}
        ],
    }
    client = _FakeClient(tables)
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    summary = payment_service.booking_summary_for_email([_BOOKING_1, _BOOKING_2])

    assert summary is not None
    assert summary["hotel_name"] == "Khách sạn Biển Xanh"
    assert summary["hotel_image_url"] == "https://img/hotel.jpg"
    assert summary["check_in_date"] == "2026-09-01"
    assert summary["check_out_date"] == "2026-09-03"
    rooms_by_name = {r["name"]: r for r in summary["rooms"]}
    assert rooms_by_name["Superior"]["image_url"] == "https://img/superior.jpg"
    assert rooms_by_name["Superior"]["room_count"] == 2
    assert rooms_by_name["Deluxe"]["image_url"] is None
    assert rooms_by_name["Deluxe"]["room_count"] == 1


def test_get_booking_receipt_for_session_falls_back_to_summed_totals_without_a_payment(monkeypatch):
    """Shouldn't normally happen (CONFIRMED only ever follows a PAID
    payment), but must degrade gracefully rather than crash if it does."""
    tables = {
        "bookings": [
            {
                "id": _BOOKING_1,
                "room_id": _ROOM_A,
                "check_in_date": "2026-09-01",
                "check_out_date": "2026-09-03",
                "room_count": 1,
                "total_amount": "500000",
                "currency": "VND",
            },
        ],
        "rooms": [{"id": _ROOM_A, "name": "Superior", "hotel_id": _HOTEL_ID}],
        "hotels": [{"name": "Khách sạn Biển Xanh", "address": None}],
        "payments": [],
    }
    client = _FakeClient(tables)
    monkeypatch.setattr(payment_service, "get_supabase_client", lambda: client)

    receipt = payment_service.get_booking_receipt_for_session("session-1")

    assert receipt is not None
    assert receipt["payment_id"] is None
    assert receipt["paid_at"] is None
    assert receipt["total_amount"] == "500000"
