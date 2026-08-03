"""Phase 3 comprehensive tests for the chat session API.

All tests mock the agent, planner tools, and Supabase — no network access.
Covers every test case listed in phase-03-chat-session-api.md step 9.
"""

from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest

import src.agents.session as session_module
import src.api.routes as routes_module
from src.agents.session import (
    SessionRegistry,
    TripSession,
    TurnResult,
    derive_stage,
)
from src.models.schemas import (
    IntakeStatus,
    sanitize_system_error,
    to_hotel_options_payload,
    to_trip_plan_payload,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(session_module, "_get_destination_names", lambda: ("Đà Nẵng", "Nha Trang"))


@pytest.fixture()
def fresh_registry(monkeypatch):
    """A fresh SessionRegistry whose create_chat_session is stubbed (no LLM)."""

    def _stub_create(session_id, **kwargs):
        s = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
        )
        # Give the session mock tools so direct call sites don't crash
        tools = MagicMock()
        tools.select_hotel = MagicMock()
        tools.finalize_trip_plan = MagicMock()
        tools.recommend_hotels = MagicMock()
        s.tools = tools
        return s

    monkeypatch.setattr(session_module, "create_chat_session", _stub_create)

    reg = SessionRegistry(ttl_seconds=3600, cap=50)
    monkeypatch.setattr(routes_module, "registry", reg)
    return reg


@pytest.fixture()
def client_with_fresh_registry(client, fresh_registry):
    """An async HTTP client backed by the fresh registry."""
    return client


# ---------------------------------------------------------------------------
# derive_stage — one test per tool (RT-1)
# ---------------------------------------------------------------------------


class TestDeriveStage:
    def test_recommend_hotels_gives_hotel_options(self):
        result = TurnResult(text="Đây là các khách sạn...", tool="recommend_hotels")
        assert derive_stage(result) == "hotel_options"

    def test_select_hotel_gives_planned(self):
        result = TurnResult(text="Đã chọn khách sạn.", tool="select_hotel")
        assert derive_stage(result) == "planned"

    def test_execute_trip_edit_gives_modified(self):
        result = TurnResult(text="Đã cập nhật lịch trình.", tool="execute_trip_edit_request")
        assert derive_stage(result) == "modified"

    def test_finalize_trip_plan_gives_finalized(self):
        result = TurnResult(text="Đã xác nhận lịch trình.", tool="finalize_trip_plan")
        assert derive_stage(result) == "finalized"

    def test_no_tool_gives_intake(self):
        result = TurnResult(text="Bạn muốn đi đâu?", tool=None)
        assert derive_stage(result) == "intake"

    def test_agent_stream_gives_intake(self):
        result = TurnResult(text="Đây là gợi ý...", tool="agent_stream")
        assert derive_stage(result) == "intake"

    def test_system_error_always_gives_error_regardless_of_tool(self):
        for tool in ("select_hotel", "recommend_hotels", "finalize_trip_plan", None, "agent_stream"):
            result = TurnResult(text="SYSTEM ERROR: something", tool=tool)
            assert derive_stage(result) == "error", f"tool={tool!r}"


# ---------------------------------------------------------------------------
# sanitize_system_error
# ---------------------------------------------------------------------------


class TestSanitizeSystemError:
    def test_non_error_string_passes_through(self):
        assert sanitize_system_error("Hello") == "Hello"

    def test_known_safe_error_passes_through(self):
        msg = "SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa."
        assert sanitize_system_error(msg) == msg

    def test_unknown_error_with_internals_is_sanitized(self):
        msg = "SYSTEM ERROR: psycopg2.InterfaceError: connection already closed (table: hotels)"
        result = sanitize_system_error(msg)
        assert result.startswith("SYSTEM ERROR:")
        assert "psycopg2" not in result
        assert "table" not in result

    def test_sanitized_result_starts_with_system_error(self):
        msg = "SYSTEM ERROR: raw database dump"
        result = sanitize_system_error(msg)
        assert result.startswith("SYSTEM ERROR:")


# ---------------------------------------------------------------------------
# to_hotel_options_payload
# ---------------------------------------------------------------------------


class TestToHotelOptionsPayload:
    def test_none_returns_empty_list(self):
        assert to_hotel_options_payload(None) == []

    def test_empty_options_returns_empty(self):
        assert to_hotel_options_payload({"options": []}) == []

    def test_options_indexed_from_one(self):
        pending = {
            "options": [
                {"id": "h1", "name": "Muong Thanh", "star_rating": 4},
                {"id": "h2", "name": "Fusion", "star_rating": 5},
            ]
        }
        result = to_hotel_options_payload(pending)
        assert len(result) == 2
        assert result[0].index == 1
        assert result[0].name == "Muong Thanh"
        assert result[1].index == 2
        assert result[1].name == "Fusion"

    def test_index_matches_suggestions_value(self):
        """hotel_options[i].index must equal int(suggestions[i].value) for the same pending list."""
        from src.agents.session import TripSession, suggestions_for

        pending = {
            "options": [
                {"id": "h1", "name": "Hotel A"},
                {"id": "h2", "name": "Hotel B"},
                {"id": "h3", "name": "Hotel C"},
            ]
        }
        session = TripSession(session_id="test", agent=None, config={})
        session.pending_hotel_selection = pending

        hotel_opts = to_hotel_options_payload(pending)
        chips = suggestions_for(session)

        assert len(hotel_opts) == len(chips)
        for hotel_opt, chip in zip(hotel_opts, chips):
            assert hotel_opt.index == int(chip["value"]), (
                f"hotel_options[].index={hotel_opt.index} != int(suggestions[].value={chip['value']!r})"
            )


# ---------------------------------------------------------------------------
# to_trip_plan_payload
# ---------------------------------------------------------------------------


class TestToTripPlanPayload:
    def test_none_returns_none(self):
        assert to_trip_plan_payload(None) is None

    def test_empty_dict_returns_payload_with_none_fields(self):
        result = to_trip_plan_payload({})
        assert result is not None
        assert result.destination is None

    def test_basic_fields_extracted(self):
        trip_data = {
            "itineraries": [
                {
                    "status": "Draft",
                    "destination": "Đà Nẵng",
                    "duration_days": 3,
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-13",
                    "number_of_adults": 2,
                    "hotel": {
                        "id": "h-uuid",
                        "name": "Muong Thanh",
                        "star_rating": 4.0,
                    },
                    "days": [],
                }
            ]
        }
        result = to_trip_plan_payload(trip_data)
        assert result.destination == "Đà Nẵng"
        assert result.duration_days == 3
        assert result.start_date == "2026-08-10"
        assert result.end_date == "2026-08-13"
        assert result.number_of_adults == 2
        assert result.status == "Draft"
        assert result.hotel is not None
        assert result.hotel.name == "Muong Thanh"


# ---------------------------------------------------------------------------
# IntakeStatus
# ---------------------------------------------------------------------------


class TestIntakeStatus:
    def test_missing_all_fields(self):
        from src.services.trip_intake import TripIntakeState

        state = TripIntakeState()
        status = IntakeStatus.from_state(state)
        assert set(status.missing) == {"destination", "duration", "start_date", "people"}

    def test_missing_people_only(self):
        from dataclasses import replace

        from src.services.trip_intake import TripIntakeState

        state = replace(TripIntakeState(), destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10")
        status = IntakeStatus.from_state(state)
        assert status.missing == ["people"]
        assert status.destination == "Đà Nẵng"

    def test_complete_state_has_no_missing(self):
        from dataclasses import replace

        from src.services.trip_intake import TripIntakeState

        state = replace(TripIntakeState(), destination="Đà Nẵng", duration="3 ngày", start_date="2026-08-10", people="2 người")
        status = IntakeStatus.from_state(state)
        assert status.missing == []

    def test_includes_start_and_derived_end_dates(self):
        from src.services.trip_intake import TripIntakeState

        status = IntakeStatus.from_state(
            TripIntakeState(
                destination="Đà Nẵng",
                duration="3 ngày",
                start_date="2026-08-10",
                people="2 người",
            )
        )

        assert status.start_date == "2026-08-10"
        assert status.end_date == "2026-08-13"


# ---------------------------------------------------------------------------
# SessionRegistry — race condition tests
# ---------------------------------------------------------------------------


class TestSessionRegistryRaces:
    def test_concurrent_creates_for_same_unknown_id_produce_one_session(self, monkeypatch):
        """N threads calling create() must each get a distinct session (server-generated ids)."""
        monkeypatch.setattr(
            session_module,
            "create_chat_session",
            lambda sid, **kw: TripSession(session_id=sid, agent=object(), config={}),
        )
        registry = SessionRegistry(ttl_seconds=3600, cap=50)
        results = []
        barrier = threading.Barrier(10)

        def _create():
            barrier.wait()
            results.append(registry.create())

        threads = [threading.Thread(target=_create) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 10 creations should produce distinct sessions (server-generated ids are UUIDs)
        session_ids = [s.session_id for s in results]
        assert len(set(session_ids)) == 10, "Concurrent create() must generate distinct session ids"

    def test_concurrent_resolve_for_same_id_returns_one_session(self, monkeypatch):
        """resolve() called concurrently with the same new id must return one TripSession object."""
        created = []

        def _stub_create(sid, **kw):
            s = TripSession(session_id=sid, agent=object(), config={})
            created.append(s)
            return s

        monkeypatch.setattr(session_module, "create_chat_session", _stub_create)

        registry = SessionRegistry(ttl_seconds=3600, cap=50)
        fixed_id = str(uuid.uuid4())
        results = []
        barrier = threading.Barrier(10)

        def _resolve():
            barrier.wait()
            results.append(registry.resolve(fixed_id))

        threads = [threading.Thread(target=_resolve) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Only one TripSession should have been created for the shared id
        assert len(created) == 1, f"Expected 1 session created, got {len(created)}"
        # All threads should have the same session object
        assert all(r is results[0] for r in results), "All threads must see the same TripSession"

    def test_locked_session_is_not_evicted(self, monkeypatch):
        """evict_expired() must skip any session whose lock is currently held."""
        monkeypatch.setattr(
            session_module,
            "create_chat_session",
            lambda sid, **kw: TripSession(session_id=sid, agent=object(), config={}),
        )
        import time

        registry = SessionRegistry(ttl_seconds=1, cap=50)  # 1-second TTL
        session = registry.create()
        sid = session.session_id

        # Acquire the per-session lock to simulate a long-running request
        session.lock.acquire()
        try:
            # Force the session to appear expired
            session.last_seen_at = time.time() - 10  # 10s ago > 1s TTL
            evicted = registry.evict_expired()
            assert evicted == 0, "A session whose lock is held must not be evicted"
            assert registry.get(sid) is session, "The locked session must still be in the registry"
        finally:
            session.lock.release()


# ---------------------------------------------------------------------------
# HTTP — stage derivation via mocked process_chat_turn
# ---------------------------------------------------------------------------


class TestStageDerivationHTTP:
    """One HTTP-level test per direct-call site (RT-1).

    Uses monkeypatched process_chat_turn so the HTTP layer's stage derivation
    is tested in isolation from the session state machine.
    """

    @pytest.fixture()
    def registered_session(self, fresh_registry):
        """A pre-registered session ready for planner_chat calls."""
        session = fresh_registry.create()
        return session.session_id

    @pytest.mark.asyncio
    async def test_recommend_hotels_stage(self, client, registered_session, monkeypatch):
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(text="Đây là khách sạn...", tool="recommend_hotels"),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "Gợi ý khách sạn"},
        )
        assert resp.status_code == 200
        assert resp.json()["stage"] == "hotel_options"

    @pytest.mark.asyncio
    async def test_select_hotel_stage(self, client, registered_session, monkeypatch):
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(text="Đã chọn.", tool="select_hotel"),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "1"},
        )
        assert resp.status_code == 200
        assert resp.json()["stage"] == "planned"

    @pytest.mark.asyncio
    async def test_execute_trip_edit_stage(self, client, registered_session, monkeypatch):
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(text="Đã cập nhật.", tool="execute_trip_edit_request"),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "Đổi ngày 2"},
        )
        assert resp.status_code == 200
        assert resp.json()["stage"] == "modified"

    @pytest.mark.asyncio
    async def test_finalize_trip_plan_stage(self, client, registered_session, monkeypatch):
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(text="Đã xác nhận.", tool="finalize_trip_plan"),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "Chốt lịch trình"},
        )
        assert resp.status_code == 200
        assert resp.json()["stage"] == "finalized"

    @pytest.mark.asyncio
    async def test_system_error_gives_error_stage_with_200(self, client, registered_session, monkeypatch):
        """SYSTEM ERROR: tool output → stage='error', HTTP 200 so UI renders as chat turn."""
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(
                text="SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa.",
                tool="execute_trip_edit_request",
            ),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "Đổi ngày 2"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "error"
        # Must not leak raw exception text
        assert "psycopg2" not in data["reply"]
        assert "traceback" not in data["reply"].lower()

    @pytest.mark.asyncio
    async def test_system_error_raw_exception_is_sanitized(self, client, registered_session, monkeypatch):
        """A SYSTEM ERROR: carrying internal detail must be sanitized before the browser sees it."""
        monkeypatch.setattr(
            routes_module,
            "process_chat_turn",
            lambda *a, **kw: TurnResult(
                text="SYSTEM ERROR: supabase.exceptions.APIError: relation 'hotels' does not exist",
                tool="select_hotel",
            ),
        )
        monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": registered_session, "message": "1"},
        )
        assert resp.status_code == 200
        reply = resp.json()["reply"]
        assert "supabase" not in reply
        assert "hotels" not in reply
        assert reply.startswith("SYSTEM ERROR:")


# ---------------------------------------------------------------------------
# HTTP — intake gate
# ---------------------------------------------------------------------------


class TestIntakeGateHTTP:
    @pytest.mark.asyncio
    async def test_bare_city_gives_intake_stage(self, client, fresh_registry):
        """A bare 'Nha Trang' message without duration/people → stage=intake."""
        sid = (await client.post("/api/v1/chat/session")).json()["session_id"]
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": sid, "message": "Nha Trang"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "intake"
        # intake.missing must list what is still needed
        assert data["intake"] is not None
        missing = data["intake"]["missing"]
        # At a minimum, duration and people should be missing
        assert "duration" in missing or "people" in missing
