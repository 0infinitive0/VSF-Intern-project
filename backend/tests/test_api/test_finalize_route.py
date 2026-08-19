"""`POST /chat/{session_id}/finalize` — the user-facing entry point for the
previously-orphaned `finalize_trip_plan` tool (see
`services/trip_finalize.py`'s module docstring). Mirrors
`test_get_booking_receipt_*`'s setup: ownership is the SESSION's
(`_owned_session_or_404`), payment-gating reuses
`payment_service.get_booking_receipt_for_session` returning non-None as
"this session is paid" -- the same signal `GET .../booking-receipt` itself
depends on, so no second query is introduced.

No test here reaches a real Supabase/embedding call --
`services.trip_finalize.finalize_session_trip` is monkeypatched directly;
its own contract (embedding failure is non-fatal, double-submit rejected)
is tested at the unit level in test_trip_finalize.py.
"""

from __future__ import annotations

import pytest

_FAKE_RECEIPT = {
    "payment_id": "9b1e2c1a-0000-4000-8000-000000000001",
    "hotel_name": "Khách sạn Biển Xanh",
    "check_in_date": "2026-09-01",
    "check_out_date": "2026-09-03",
    "currency": "VND",
    "total_amount": "1600000",
    "rooms": [],
}


async def _create_session_with_trip_data(client, trip_data: dict) -> str:
    import src.api.routes as _routes

    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]
    app = _routes._get_graph_v2()
    config = {"configurable": {"thread_id": session_id}}
    app.update_state(config, {"trip_data": trip_data})
    return session_id


def _draft_trip_data() -> dict:
    return {"hotel": {"id": "h1"}, "itineraries": [{"id": "itin-1", "status": "Draft"}], "itinerary_items": []}


def _finalized_trip_data() -> dict:
    return {"hotel": {"id": "h1"}, "itineraries": [{"id": "itin-1", "status": "Finalized"}], "itinerary_items": []}


@pytest.mark.asyncio
async def test_returns_404_for_a_different_owner(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_returns_409_when_the_session_has_no_confirmed_booking(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service

    auth_override("user-a")
    session_id = await _create_session_with_trip_data(client, _draft_trip_data())
    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: None)

    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_returns_409_when_there_is_no_trip_plan_yet(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]  # no trip_data seeded
    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: dict(_FAKE_RECEIPT))

    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_returns_409_for_an_already_finalized_trip(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service

    auth_override("user-a")
    session_id = await _create_session_with_trip_data(client, _finalized_trip_data())
    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: dict(_FAKE_RECEIPT))

    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_finalizes_a_paid_draft_and_persists_the_status_back(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = await _create_session_with_trip_data(client, _draft_trip_data())
    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: dict(_FAKE_RECEIPT))

    def _fake_finalize(trip_data):
        updated = dict(trip_data)
        itinerary = dict(updated["itineraries"][0])
        itinerary["status"] = "Finalized"
        updated["itineraries"] = [itinerary]
        return {"trip_data": updated, "status": "Finalized", "summary": "2 ngày ở Đà Nẵng", "embedding_saved": True}

    monkeypatch.setattr(_routes, "finalize_session_trip", _fake_finalize)

    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Finalized"
    assert body["summary"] == "2 ngày ở Đà Nẵng"
    assert body["embedding_saved"] is True

    # The write-back actually landed in checkpointed graph state -- not just
    # in the HTTP response -- so the NEXT read (GET .../plan, another turn)
    # sees the lock too.
    app = _routes._get_graph_v2()
    state = app.get_state({"configurable": {"thread_id": session_id}}).values
    assert state["trip_data"]["itineraries"][0]["status"] == "Finalized"


@pytest.mark.asyncio
async def test_a_finalize_error_from_the_service_surfaces_as_409_not_500(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service
    from src.services.trip_finalize import FinalizeTripError
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = await _create_session_with_trip_data(client, _draft_trip_data())
    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: dict(_FAKE_RECEIPT))

    def _raise(_trip_data):
        raise FinalizeTripError("Không xác định được điểm đến của kế hoạch hiện tại.")

    monkeypatch.setattr(_routes, "finalize_session_trip", _raise)

    response = await client.post(f"/api/v1/chat/{session_id}/finalize")

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /hotels/change on a finalized trip -- the one writer entry point that
# reaches `hotel_node` via `Command(goto=...)` without passing through
# `nodes/supervisor.py`'s lock guard at all (routes.py::_rerun_hotel_search).
# Checked directly in the route, not just relying on the frontend hiding the
# control.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hotels_change_returns_409_for_a_finalized_trip(client, auth_override):
    auth_override("user-a")
    session_id = await _create_session_with_trip_data(client, _finalized_trip_data())

    response = await client.post("/api/v1/hotels/change", json={"session_id": session_id})

    assert response.status_code == 409
