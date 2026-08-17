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
