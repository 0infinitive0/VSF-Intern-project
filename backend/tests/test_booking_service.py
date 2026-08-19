from datetime import date, time
from decimal import Decimal
from uuid import uuid4

import pytest

from src.services import booking_service


class _Response:
    def __init__(self, data):
        self.data = data


class _RPC:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return _Response(self._data)


class _Client:
    def __init__(self, data):
        self.data = data
        self.call = None

    def rpc(self, name, params):
        self.call = (name, params)
        return _RPC(self.data)


def test_reserve_booking_calls_atomic_reservation_rpc(monkeypatch):
    client = _Client([{"id": "booking-1", "status": "RESERVED"}])
    monkeypatch.setattr(booking_service, "get_supabase_client", lambda: client)

    result = booking_service.reserve_booking(
        room_id=uuid4(), temporary_user_ref="guest-1",
        check_in_date=date(2026, 8, 1), check_in_time=time(14),
        check_out_date=date(2026, 8, 3), check_out_time=time(12),
        room_count=2, total_amount=Decimal("2500000"), currency="VND",
    )

    assert result["status"] == "RESERVED"
    assert client.call[0] == "create_booking_reservation"
    assert client.call[1]["p_room_count"] == 2


def test_booking_service_translates_availability_conflict(monkeypatch):
    class _FailingRPC:
        def execute(self):
            raise RuntimeError("insufficient_room_availability")

    class _FailingClient:
        def rpc(self, *_args):
            return _FailingRPC()

    monkeypatch.setattr(booking_service, "get_supabase_client", _FailingClient)

    with pytest.raises(booking_service.BookingError, match="insufficient_room_availability"):
        booking_service.confirm_booking(booking_id=uuid4(), temporary_user_ref="guest-1")


def test_reserve_booking_passes_session_id_through(monkeypatch):
    client = _Client([{"id": "booking-1", "status": "RESERVED"}])
    monkeypatch.setattr(booking_service, "get_supabase_client", lambda: client)

    booking_service.reserve_booking(
        room_id=uuid4(), temporary_user_ref="guest-1",
        check_in_date=date(2026, 8, 1), check_in_time=time(14),
        check_out_date=date(2026, 8, 3), check_out_time=time(12),
        room_count=2, total_amount=Decimal("2500000"), currency="VND",
        session_id="session-abc",
    )

    assert client.call[1]["p_session_id"] == "session-abc"


def test_reserve_booking_defaults_session_id_to_none(monkeypatch):
    client = _Client([{"id": "booking-1", "status": "RESERVED"}])
    monkeypatch.setattr(booking_service, "get_supabase_client", lambda: client)

    booking_service.reserve_booking(
        room_id=uuid4(), temporary_user_ref="guest-1",
        check_in_date=date(2026, 8, 1), check_in_time=time(14),
        check_out_date=date(2026, 8, 3), check_out_time=time(12),
        room_count=2, total_amount=Decimal("2500000"), currency="VND",
    )

    assert client.call[1]["p_session_id"] is None


def test_booking_service_translates_guest_already_holding_elsewhere(monkeypatch):
    """create_booking_reservation's cross-hotel hold guard (migration
    20260819_add_guest_single_hotel_hold_guard.sql) must map to its own
    code, not fall through to booking_operation_failed's generic 500 (see
    routes.py's _booking_http_error, which maps this to 409)."""

    class _FailingRPC:
        def execute(self):
            raise RuntimeError("guest_already_holding_elsewhere")

    class _FailingClient:
        def rpc(self, *_args):
            return _FailingRPC()

    monkeypatch.setattr(booking_service, "get_supabase_client", _FailingClient)

    with pytest.raises(booking_service.BookingError, match="guest_already_holding_elsewhere"):
        booking_service.reserve_booking(
            room_id=uuid4(), temporary_user_ref="guest-1",
            check_in_date=date(2026, 8, 1), check_in_time=time(14),
            check_out_date=date(2026, 8, 3), check_out_time=time(12),
            room_count=2, total_amount=Decimal("2500000"), currency="VND",
        )


def test_booking_service_translates_invalid_request(monkeypatch):
    """create_booking_reservation's own validation (bad date range,
    room_count <= 0, hold_minutes out of range) must map to its own code —
    previously fell through to the generic booking_operation_failed and
    surfaced as a bare 500 (see routes.py's _booking_http_error)."""

    class _FailingRPC:
        def execute(self):
            raise RuntimeError("invalid_booking_request")

    class _FailingClient:
        def rpc(self, *_args):
            return _FailingRPC()

    monkeypatch.setattr(booking_service, "get_supabase_client", _FailingClient)

    with pytest.raises(booking_service.BookingError, match="invalid_booking_request"):
        booking_service.reserve_booking(
            room_id=uuid4(), temporary_user_ref="guest-1",
            check_in_date=date(2026, 8, 1), check_in_time=time(14),
            check_out_date=date(2026, 8, 3), check_out_time=time(12),
            room_count=2, total_amount=Decimal("2500000"), currency="VND",
        )
