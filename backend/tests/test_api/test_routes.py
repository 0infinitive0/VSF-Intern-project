"""Tests for API routes — Phase 3 hardening.

The existing session-state tests are adapted to Phase 3: a session must be
created via POST /api/v1/chat/session before planner_chat is called.
The 422 and status/health tests are unchanged (D10 backward-compat).
"""

import uuid

import pytest

import src.agents.session as session_module
from src.agents.session import TripSession
from src.config import get_settings


@pytest.fixture(autouse=True)
def _auth_not_required_by_default(monkeypatch):
    """Pin AUTH_REQUIRED=false for this module's baseline, explicitly rather
    than relying on config.py's default: Settings reads backend/.env
    directly (env_file=".env"), so on a dev machine that has since flipped
    AUTH_REQUIRED=true there for real, an un-pinned test would silently
    inherit that and 401 on every request below that sends no token —
    same class of bug already documented in test_jwt_verifier.py's
    test_no_supabase_url_configured_raises. Most tests here exercise
    business logic (session lifecycle, hotel flows, planner turns) that is
    orthogonal to the auth rollout flag; the handful that specifically test
    ownership/AUTH_REQUIRED behavior use the auth_override fixture below or
    set the env var themselves.
    """
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fake_planner_agent(monkeypatch):
    """Stub build_trip_agent so tests don't need a live LLM.

    The state-machine logic under test (intake -> hotel prefs) never touches
    session.agent, so an object() stub suffices.
    """

    def _fake_create_chat_session(thread_id, **kwargs):
        return TripSession(
            session_id=thread_id,
            config={"configurable": {"thread_id": thread_id}},
            owner_user_id=kwargs.get("owner_user_id"),
        )

    monkeypatch.setattr(session_module, "create_chat_session", _fake_create_chat_session)

    # Refresh the registry so it picks up the monkeypatched create_chat_session.
    import src.api.routes as _routes
    from src.agents.session import SessionRegistry

    _routes.registry = SessionRegistry(ttl_seconds=3600, cap=100)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_returns_uuid(client):
    response = await client.post("/api/v1/chat/session")
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    # Must be a valid UUID
    uuid.UUID(data["session_id"])
    assert "created_at" in data


@pytest.mark.asyncio
async def test_unknown_session_id_returns_404(client):
    """An unknown but well-formed UUID must return 404, not create a session."""
    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": str(uuid.uuid4()), "message": "Tôi muốn đi Đà Nẵng"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_malformed_session_id_returns_422(client):
    """A non-UUID session_id must be rejected at the pydantic boundary."""
    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": "not-a-uuid!!", "message": "Tôi muốn đi Đà Nẵng"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_then_get_plan_returns_404(client):
    create_resp = await client.post("/api/v1/chat/session")
    sid = create_resp.json()["session_id"]

    del_resp = await client.delete(f"/api/v1/chat/{sid}")
    assert del_resp.status_code == 204

    plan_resp = await client.get(f"/api/v1/chat/{sid}/plan")
    assert plan_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_plan_for_unknown_session_returns_404(client):
    response = await client.get(f"/api/v1/chat/{uuid.uuid4()}/plan")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Planner chat — state preservation (adapted from original test_routes.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_chat_empty_message_rejected(client):
    """min_length=1 on message must still produce 422 (D10 backward-compat)."""
    create_resp = await client.post("/api/v1/chat/session")
    session_id = create_resp.json()["session_id"]

    response = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": session_id, "message": ""},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Two sessions must not share state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Utility endpoints (unchanged from original)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_search_hotels_defaults_to_five_candidates(client, monkeypatch):
    import src.services.supabase_search as supabase_search_module

    captured: dict[str, int] = {}

    def fake_search_hotels_with_rooms(_query, *, match_count):
        captured["match_count"] = match_count
        return [
            {"id": str(index), "similarity": 0.9, "name": f"Hotel {index}"}
            for index in range(match_count)
        ]

    monkeypatch.setattr(
        supabase_search_module,
        "search_hotels_with_rooms",
        fake_search_hotels_with_rooms,
    )

    response = await client.get("/api/v1/search_hotels", params={"q": "hotel"})

    assert response.status_code == 200
    assert captured["match_count"] == 5
    assert len(response.json()["results"]) == 5


# ---------------------------------------------------------------------------
# Ownership / cross-user isolation (plan 260814-supabase-auth-and-per-user-history)
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_override():
    """Overrides the get_current_user dependency for the app under test.

    Call with a user id to simulate an authenticated caller, or with None to
    simulate no/an invalid token (AUTH_REQUIRED defaults to False, so that is
    "anonymous", not "rejected" — see src/auth/dependencies.py). Always
    cleared after the test, pass or fail.
    """
    from src.auth import AuthenticatedUser, get_current_user
    from src.main import app

    def _set(user_id: str | None):
        if user_id is None:
            app.dependency_overrides.pop(get_current_user, None)
            return
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
            id=user_id, email=f"{user_id}@example.com", is_anonymous=False
        )

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_create_session_stamps_the_caller_as_owner(client, auth_override):
    import src.api.routes as _routes

    auth_override("user-a")
    response = await client.post("/api/v1/chat/session")
    session_id = response.json()["session_id"]

    session = _routes.registry.get(session_id)
    assert session.owner_user_id == "user-a"


@pytest.mark.asyncio
async def test_a_session_created_with_no_caller_identity_has_no_owner(client, auth_override):
    """AUTH_REQUIRED=False (the default) must not regress today's behavior:
    a caller sending no token still gets a working, unowned session."""
    import src.api.routes as _routes

    auth_override(None)
    response = await client.post("/api/v1/chat/session")
    session_id = response.json()["session_id"]

    session = _routes.registry.get(session_id)
    assert session.owner_user_id is None


@pytest.mark.asyncio
async def test_the_owning_user_can_reach_their_own_session(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_different_authenticated_user_gets_404_not_someone_elses_session(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_an_unauthenticated_caller_cannot_reach_someone_elses_session_either(client, auth_override):
    """The security fix does not depend on AUTH_REQUIRED being on: a caller
    with no identity at all must be just as unable to reach an owned session
    as a caller authenticated as someone else."""
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override(None)
    response = await client.get(f"/api/v1/chat/{session_id}/plan")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_planner_chat_also_enforces_ownership(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.post(
        "/api/v1/planner_chat", json={"session_id": session_id, "message": "hello"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_session_is_a_silent_noop_for_a_different_owner(client, auth_override):
    """Preserves the existing '204 either way' contract (never leaks
    existence via status code) while still not actually deleting a session
    that belongs to someone else."""
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.delete(f"/api/v1/chat/{session_id}")
    assert response.status_code == 204
    assert _routes.registry.get(session_id) is not None

    auth_override("user-a")
    response = await client.delete(f"/api/v1/chat/{session_id}")
    assert response.status_code == 204
    assert _routes.registry.get(session_id) is None


@pytest.mark.asyncio
async def test_delete_session_cancels_reserved_bookings_for_that_session(client, auth_override, monkeypatch):
    """Deleting a session must release whatever room it was still holding —
    server-side and deterministic, independent of any particular browser
    tab's frontend state (see booking_service.cancel_reserved_bookings_
    for_session's own doc comment for why relying on the frontend alone
    isn't enough)."""
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    calls: list[str] = []
    monkeypatch.setattr(
        _routes, "cancel_reserved_bookings_for_session", lambda sid: calls.append(sid) or 1
    )

    response = await client.delete(f"/api/v1/chat/{session_id}")

    assert response.status_code == 204
    assert calls == [session_id]


@pytest.mark.asyncio
async def test_delete_session_still_succeeds_if_booking_cleanup_fails(client, auth_override, monkeypatch):
    """A failure releasing bookings must never block the session deletion
    itself — best-effort side effect, per the route's own comment."""
    import src.api.routes as _routes

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    def _raise(_sid):
        raise RuntimeError("boom")

    monkeypatch.setattr(_routes, "cancel_reserved_bookings_for_session", _raise)

    response = await client.delete(f"/api/v1/chat/{session_id}")

    assert response.status_code == 204
    assert _routes.registry.get(session_id) is None


# ---------------------------------------------------------------------------
# Bookings — HTTP status mapping (plan 260818-booking-backend-robustness)
#
# booking_service.reserve_booking/confirm_booking/cancel_booking are imported
# by NAME at the top of routes.py (`from src.services.booking_service import
# ...`), unlike search_hotels_with_rooms's lazy in-function import above — so
# they must be monkeypatched on src.api.routes itself, not on the
# booking_service module, or the patch never takes effect.
# ---------------------------------------------------------------------------

_BOOKING_ROOM_ID = "11111111-1111-1111-1111-111111111111"
_BOOKING_ID = "22222222-2222-2222-2222-222222222222"


def _fake_booking(**overrides):
    booking = {
        "id": _BOOKING_ID,
        "room_id": _BOOKING_ROOM_ID,
        "check_in_date": "2026-09-01",
        "check_in_time": "14:00:00",
        "check_out_date": "2026-09-03",
        "check_out_time": "12:00:00",
        "room_count": 1,
        "status": "RESERVED",
        "expires_at": "2026-09-01T00:15:00+00:00",
        "total_amount": "1500000.00",
        "currency": "VND",
    }
    booking.update(overrides)
    return booking


@pytest.mark.asyncio
async def test_create_booking_returns_201_on_success(client, monkeypatch):
    import src.api.routes as _routes

    monkeypatch.setattr(_routes, "reserve_booking", lambda **_kwargs: _fake_booking())

    response = await client.post(
        "/api/v1/bookings",
        json={
            "room_id": _BOOKING_ROOM_ID,
            "temporary_user_ref": "guest-1",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-03",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "RESERVED"


@pytest.mark.asyncio
async def test_create_booking_sold_out_returns_409(client, monkeypatch):
    """The room a second, losing racer just missed — see
    create_booking_reservation's pg_advisory_xact_lock in the migration:
    this is the clean, expected outcome of a real concurrent hold, not a
    server error."""
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(**_kwargs):
        raise BookingError("insufficient_room_availability")

    monkeypatch.setattr(_routes, "reserve_booking", _raise)

    response = await client.post(
        "/api/v1/bookings",
        json={
            "room_id": _BOOKING_ROOM_ID,
            "temporary_user_ref": "guest-2",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-03",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "insufficient_room_availability"


@pytest.mark.asyncio
async def test_create_booking_guest_already_holding_elsewhere_returns_409(client, monkeypatch):
    """The same guest ref (shared cross-tab via localStorage — see
    frontend/src/lib/guest-ref.ts) already holds a live RESERVED booking at
    a different hotel — create_booking_reservation's cross-hotel guard
    (migration 20260819_add_guest_single_hotel_hold_guard.sql). Rejected
    with a clear domain code, not a bare 500."""
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(**_kwargs):
        raise BookingError("guest_already_holding_elsewhere")

    monkeypatch.setattr(_routes, "reserve_booking", _raise)

    response = await client.post(
        "/api/v1/bookings",
        json={
            "room_id": _BOOKING_ROOM_ID,
            "temporary_user_ref": "guest-2",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-03",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "guest_already_holding_elsewhere"


@pytest.mark.asyncio
async def test_create_booking_invalid_request_returns_422(client, monkeypatch):
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(**_kwargs):
        raise BookingError("invalid_booking_request")

    monkeypatch.setattr(_routes, "reserve_booking", _raise)

    response = await client.post(
        "/api/v1/bookings",
        json={
            "room_id": _BOOKING_ROOM_ID,
            "temporary_user_ref": "guest-3",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-03",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_booking_request"


@pytest.mark.asyncio
async def test_create_booking_unexpected_failure_returns_500_without_leaking_internals(client, monkeypatch):
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(**_kwargs):
        raise BookingError("booking_operation_failed")

    monkeypatch.setattr(_routes, "reserve_booking", _raise)

    response = await client.post(
        "/api/v1/bookings",
        json={
            "room_id": _BOOKING_ROOM_ID,
            "temporary_user_ref": "guest-4",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-03",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Unable to process booking."


@pytest.mark.asyncio
async def test_confirm_booking_not_found_returns_404(client, monkeypatch):
    """Covers both a genuinely missing booking id AND a temporary_user_ref
    that doesn't match — confirm_booking_reservation raises the identical
    error for both, so neither case leaks which one it was."""
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(*, booking_id, temporary_user_ref):
        raise BookingError("booking_not_found")

    monkeypatch.setattr(_routes, "confirm_booking", _raise)

    response = await client.post(
        f"/api/v1/bookings/{_BOOKING_ID}/confirm",
        json={"temporary_user_ref": "wrong-guest"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_confirm_booking_after_hold_expired_returns_409(client, monkeypatch):
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(*, booking_id, temporary_user_ref):
        raise BookingError("booking_reservation_expired")

    monkeypatch.setattr(_routes, "confirm_booking", _raise)

    response = await client.post(
        f"/api/v1/bookings/{_BOOKING_ID}/confirm",
        json={"temporary_user_ref": "guest-1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "booking_reservation_expired"


@pytest.mark.asyncio
async def test_confirm_already_confirmed_booking_returns_409(client, monkeypatch):
    """A double-submit (two tabs, retried request) on the same booking must
    not silently succeed twice or 500 — confirm_booking_reservation's row
    lock means only the first ever sees status='RESERVED'."""
    import src.api.routes as _routes
    from src.services.booking_service import BookingError

    def _raise(*, booking_id, temporary_user_ref):
        raise BookingError("booking_not_confirmable")

    monkeypatch.setattr(_routes, "confirm_booking", _raise)

    response = await client.post(
        f"/api/v1/bookings/{_BOOKING_ID}/confirm",
        json={"temporary_user_ref": "guest-1"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "booking_not_confirmable"


@pytest.mark.asyncio
async def test_cancel_booking_returns_200_on_success(client, monkeypatch):
    import src.api.routes as _routes

    monkeypatch.setattr(
        _routes, "cancel_booking", lambda *, booking_id, temporary_user_ref: _fake_booking(status="CANCELLED")
    )

    response = await client.post(
        f"/api/v1/bookings/{_BOOKING_ID}/cancel",
        json={"temporary_user_ref": "guest-1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# VNPay payment (plan 260818-vnpay-payment-and-email-confirmation)
#
# create_vnpay_payment/vnpay_ipn/get_payment_endpoint reach payment_service
# and vnpay_service via a MODULE reference (`from src.services import
# payment_service` / `vnpay_service` in routes.py, not `from ... import
# create_payment`), so those are monkeypatched on the source module itself —
# same reasoning as search_hotels_with_rooms's lazy import elsewhere in this
# file, opposite of the booking_service functions above (which ARE
# monkeypatched on _routes, being direct-name imports there).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _vnpay_configured(monkeypatch):
    """Pins real-looking (but fake) VNPay credentials so create_vnpay_payment
    doesn't 503 by default; individual tests override/clear as needed."""
    monkeypatch.setenv("VNPAY_TMN_CODE", "TESTCODE")
    monkeypatch.setenv("VNPAY_HASH_SECRET", "test-secret")
    monkeypatch.setenv("VNPAY_RETURN_URL", "https://example.com/")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fake_reserved_booking(**overrides):
    booking = {
        "id": _BOOKING_ID,
        "room_id": _BOOKING_ROOM_ID,
        "status": "RESERVED",
        "temporary_user_ref": "guest-1",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "total_amount": "1500000.00",
        "currency": "VND",
    }
    booking.update(overrides)
    return booking


_PAYMENT_ID = "33333333-3333-3333-3333-333333333333"


def _fake_payment(**overrides):
    payment = {
        "id": _PAYMENT_ID,
        "booking_ids": [_BOOKING_ID],
        "temporary_user_ref": "guest-1",
        "amount": "1500000.00",
        "currency": "VND",
        "status": "PENDING",
        "guest_name": "Nguyen Van A",
        "guest_email": "guest@example.com",
        "guest_phone": None,
        "vnp_transaction_no": None,
        "paid_at": None,
        "created_at": "2026-08-18T00:00:00+00:00",
    }
    payment.update(overrides)
    return payment


@pytest.mark.asyncio
async def test_create_vnpay_payment_returns_pay_url_on_success(client, monkeypatch):
    import src.api.routes as _routes
    from src.services import payment_service as _payment_service

    monkeypatch.setattr(_routes, "get_booking", lambda _id: _fake_reserved_booking())
    monkeypatch.setattr(_payment_service, "create_payment", lambda **_kwargs: _fake_payment())

    response = await client.post(
        "/api/v1/payments/vnpay",
        json={
            "booking_ids": [_BOOKING_ROOM_ID],
            "temporary_user_ref": "guest-1",
            "guest_name": "Nguyen Van A",
            "guest_email": "guest@example.com",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["payment_id"] == _PAYMENT_ID
    assert data["pay_url"].startswith("https://sandbox.vnpayment.vn/paymentv2/vpcpay.html?")
    assert "vnp_SecureHash=" in data["pay_url"]


@pytest.mark.asyncio
async def test_create_vnpay_payment_returns_503_when_not_configured(client, monkeypatch):
    # setenv("", "") rather than delenv: pydantic-settings' source priority is
    # env vars > .env file, so an explicit empty env var reliably blocks the
    # dotenv fallback. delenv would instead let a real VNPAY_TMN_CODE/
    # VNPAY_HASH_SECRET in the developer's own backend/.env (e.g. for manual
    # sandbox testing) leak through and silently "configure" this test.
    monkeypatch.setenv("VNPAY_TMN_CODE", "")
    monkeypatch.setenv("VNPAY_HASH_SECRET", "")
    get_settings.cache_clear()

    response = await client.post(
        "/api/v1/payments/vnpay",
        json={
            "booking_ids": [_BOOKING_ROOM_ID],
            "temporary_user_ref": "guest-1",
            "guest_name": "Nguyen Van A",
            "guest_email": "guest@example.com",
        },
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_create_vnpay_payment_rejects_a_booking_owned_by_someone_else(client, monkeypatch):
    import src.api.routes as _routes

    monkeypatch.setattr(
        _routes, "get_booking", lambda _id: _fake_reserved_booking(temporary_user_ref="someone-else")
    )

    response = await client.post(
        "/api/v1/payments/vnpay",
        json={
            "booking_ids": [_BOOKING_ROOM_ID],
            "temporary_user_ref": "guest-1",
            "guest_name": "Nguyen Van A",
            "guest_email": "guest@example.com",
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_vnpay_payment_rejects_a_non_reserved_booking(client, monkeypatch):
    import src.api.routes as _routes

    monkeypatch.setattr(_routes, "get_booking", lambda _id: _fake_reserved_booking(status="CONFIRMED"))

    response = await client.post(
        "/api/v1/payments/vnpay",
        json={
            "booking_ids": [_BOOKING_ROOM_ID],
            "temporary_user_ref": "guest-1",
            "guest_name": "Nguyen Van A",
            "guest_email": "guest@example.com",
        },
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_vnpay_payment_rejects_an_expired_hold(client, monkeypatch):
    import src.api.routes as _routes

    monkeypatch.setattr(
        _routes, "get_booking", lambda _id: _fake_reserved_booking(expires_at="2000-01-01T00:00:00+00:00")
    )

    response = await client.post(
        "/api/v1/payments/vnpay",
        json={
            "booking_ids": [_BOOKING_ROOM_ID],
            "temporary_user_ref": "guest-1",
            "guest_name": "Nguyen Van A",
            "guest_email": "guest@example.com",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "booking_reservation_expired"


@pytest.mark.asyncio
async def test_vnpay_ipn_rejects_an_invalid_signature(client, monkeypatch):
    from src.services import vnpay_service as _vnpay_service

    monkeypatch.setattr(_vnpay_service, "verify_signature", lambda *_a, **_k: False)

    response = await client.get("/api/v1/payments/vnpay/ipn", params={"vnp_TxnRef": _PAYMENT_ID})

    assert response.status_code == 200
    assert response.json()["RspCode"] == "97"


@pytest.mark.asyncio
async def test_vnpay_ipn_returns_order_not_found_for_unknown_txn_ref(client, monkeypatch):
    from src.services import payment_service as _payment_service
    from src.services import vnpay_service as _vnpay_service

    monkeypatch.setattr(_vnpay_service, "verify_signature", lambda *_a, **_k: True)
    monkeypatch.setattr(_payment_service, "get_payment", lambda _id: None)

    response = await client.get("/api/v1/payments/vnpay/ipn", params={"vnp_TxnRef": _PAYMENT_ID})

    assert response.json()["RspCode"] == "01"


@pytest.mark.asyncio
async def test_vnpay_ipn_rejects_a_mismatched_amount(client, monkeypatch):
    from src.services import payment_service as _payment_service
    from src.services import vnpay_service as _vnpay_service

    monkeypatch.setattr(_vnpay_service, "verify_signature", lambda *_a, **_k: True)
    monkeypatch.setattr(_payment_service, "get_payment", lambda _id: _fake_payment(amount="1500000.00"))

    response = await client.get(
        "/api/v1/payments/vnpay/ipn",
        params={"vnp_TxnRef": _PAYMENT_ID, "vnp_Amount": "100"},  # far too low
    )

    assert response.json()["RspCode"] == "04"


@pytest.mark.asyncio
async def test_vnpay_ipn_is_idempotent_on_a_retried_notification(client, monkeypatch):
    from src.services import payment_service as _payment_service
    from src.services import vnpay_service as _vnpay_service

    monkeypatch.setattr(_vnpay_service, "verify_signature", lambda *_a, **_k: True)
    monkeypatch.setattr(_payment_service, "get_payment", lambda _id: _fake_payment(status="PAID"))

    response = await client.get(
        "/api/v1/payments/vnpay/ipn",
        params={"vnp_TxnRef": _PAYMENT_ID, "vnp_Amount": "150000000"},
    )

    assert response.json()["RspCode"] == "02"


@pytest.mark.asyncio
async def test_vnpay_ipn_confirms_bookings_on_a_successful_payment(client, monkeypatch):
    """The end-to-end happy path this whole feature exists for: a genuine,
    signature-verified "00" IPN must flip the payment to PAID AND confirm
    every booking in its group — not just record the payment."""
    import src.api.routes as _routes
    from src.services import payment_service as _payment_service
    from src.services import vnpay_service as _vnpay_service

    monkeypatch.setattr(_vnpay_service, "verify_signature", lambda *_a, **_k: True)
    monkeypatch.setattr(_payment_service, "get_payment", lambda _id: _fake_payment())
    monkeypatch.setattr(
        _payment_service, "mark_payment_paid", lambda **_kwargs: _fake_payment(status="PAID")
    )
    monkeypatch.setattr(_payment_service, "booking_summary_for_email", lambda _id: None)
    confirmed_booking_ids: list[str] = []
    monkeypatch.setattr(
        _routes,
        "confirm_booking",
        lambda *, booking_id, temporary_user_ref: confirmed_booking_ids.append(str(booking_id)),
    )

    response = await client.get(
        "/api/v1/payments/vnpay/ipn",
        params={
            "vnp_TxnRef": _PAYMENT_ID,
            "vnp_Amount": "150000000",
            "vnp_ResponseCode": "00",
            "vnp_TransactionStatus": "00",
            "vnp_TransactionNo": "VNP123",
        },
    )

    assert response.json()["RspCode"] == "00"
    assert confirmed_booking_ids == [_BOOKING_ID]


@pytest.mark.asyncio
async def test_get_payment_endpoint_returns_404_for_wrong_owner(client, monkeypatch):
    from src.services import payment_service as _payment_service

    monkeypatch.setattr(_payment_service, "get_payment_for_owner", lambda _id, _ref: None)

    response = await client.get(
        f"/api/v1/payments/{_PAYMENT_ID}", params={"temporary_user_ref": "someone-else"}
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_payment_endpoint_returns_payment_for_the_owner(client, monkeypatch):
    from src.services import payment_service as _payment_service

    monkeypatch.setattr(_payment_service, "get_payment_for_owner", lambda _id, _ref: _fake_payment())

    response = await client.get(
        f"/api/v1/payments/{_PAYMENT_ID}", params={"temporary_user_ref": "guest-1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PENDING"


# ---------------------------------------------------------------------------
# GET /chat/{session_id}/booking-receipt (plan
# 260818-vnpay-payment-and-email-confirmation's addendum 4) — "reopen a
# past session's booking". Ownership is the SESSION's (_owned_session_or_404,
# same as every other /chat/{session_id}/... route), not a payment/
# temporary_user_ref check, so these mirror test_delete_session_is_a_
# silent_noop_for_a_different_owner's setup rather than the payment-owner
# tests just above.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_booking_receipt_returns_404_for_a_different_owner(client, auth_override):
    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    auth_override("user-b")
    response = await client.get(f"/api/v1/chat/{session_id}/booking-receipt")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_booking_receipt_returns_404_when_no_confirmed_booking(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    monkeypatch.setattr(_payment_service, "get_booking_receipt_for_session", lambda _sid: None)

    response = await client.get(f"/api/v1/chat/{session_id}/booking-receipt")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_booking_receipt_returns_the_receipt_for_the_owner(client, auth_override, monkeypatch):
    from src.services import payment_service as _payment_service

    auth_override("user-a")
    session_id = (await client.post("/api/v1/chat/session")).json()["session_id"]

    fake_receipt = {
        "payment_id": _PAYMENT_ID,
        "hotel_name": "Khách sạn Biển Xanh",
        "hotel_address": "123 Trần Phú",
        "check_in_date": "2026-09-01",
        "check_out_date": "2026-09-03",
        "currency": "VND",
        "total_amount": "1600000",
        "paid_at": "2026-09-01T10:00:00+00:00",
        "rooms": [
            {"room_id": _BOOKING_ROOM_ID, "name": "Superior", "room_count": 2, "total_amount": "1000000"},
        ],
    }
    monkeypatch.setattr(
        _payment_service,
        "get_booking_receipt_for_session",
        lambda sid: fake_receipt if sid == session_id else None,
    )

    response = await client.get(f"/api/v1/chat/{session_id}/booking-receipt")

    assert response.status_code == 200
    data = response.json()
    assert data["hotel_name"] == "Khách sạn Biển Xanh"
    assert data["total_amount"] == "1600000"
    assert len(data["rooms"]) == 1
    assert data["rooms"][0]["name"] == "Superior"
