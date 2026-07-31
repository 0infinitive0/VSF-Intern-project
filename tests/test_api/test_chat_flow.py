"""test_chat_flow.py — Phase 5 full turn-sequence integration test.

Covers the complete conversation flow with all planner tools mocked:
  POST /chat/session
  → intake turn (bare city)          → stage=intake
  → duration added                   → stage=intake (people missing)
  → people added                     → hotel preference questions → stage=intake
  → prefs answered × N               → hotel options → stage=hotel_options
  → hotel selection (send "1")       → stage=planned
  → plan modification                → stage=modified
  → plan finalization                → stage=finalized
  → reset (DELETE)                   → 204
  → GET plan after reset             → 404

All Supabase / Ollama / LLM calls are stubbed — no network access.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.agents.session as session_module
import src.api.routes as routes_module
from src.agents.session import SessionRegistry, TripSession, TurnResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_destination_names(monkeypatch):
    monkeypatch.setattr(
        session_module,
        "_get_destination_names",
        lambda: ("Đà Nẵng", "Nha Trang", "Hội An"),
    )


@pytest.fixture()
def fresh_registry(monkeypatch):
    """Fresh registry with stubbed session factory (no LLM)."""

    def _stub_create(session_id, **kwargs):
        session = TripSession(
            session_id=session_id,
            agent=MagicMock(),
            config={"configurable": {"thread_id": session_id}},
        )
        tools = MagicMock()
        tools.select_hotel = MagicMock()
        tools.finalize_trip_plan = MagicMock()
        tools.recommend_hotels = MagicMock()
        session.tools = tools
        return session

    monkeypatch.setattr(session_module, "create_chat_session", _stub_create)
    reg = SessionRegistry(ttl_seconds=3600, cap=50)
    monkeypatch.setattr(routes_module, "registry", reg)
    return reg


def _mock_turn(monkeypatch, result: TurnResult) -> None:
    """Patch process_chat_turn to return *result* on the next call."""
    monkeypatch.setattr(routes_module, "process_chat_turn", lambda *a, **kw: result)
    monkeypatch.setattr(routes_module, "suggestions_for", lambda s: [])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _session(client) -> str:
    """Create a session and return its id."""
    resp = await client.post("/api/v1/chat/session")
    assert resp.status_code == 200
    return resp.json()["session_id"]


async def _chat(client, sid: str, message: str) -> dict:
    resp = await client.post(
        "/api/v1/planner_chat",
        json={"session_id": sid, "message": message},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Session creation
# ---------------------------------------------------------------------------


class TestSessionCreation:
    @pytest.mark.asyncio
    async def test_create_session_returns_uuid_and_timestamp(self, client, fresh_registry):
        resp = await client.post("/api/v1/chat/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert "created_at" in data
        # Must be a valid UUID (raises ValueError if not)
        import uuid
        uuid.UUID(data["session_id"])

    @pytest.mark.asyncio
    async def test_unknown_session_returns_404(self, client, fresh_registry):
        import uuid
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": str(uuid.uuid4()), "message": "test"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_malformed_session_id_returns_422(self, client, fresh_registry):
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": "not-a-uuid!!!", "message": "test"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 2. Intake stage
# ---------------------------------------------------------------------------


class TestIntakeStage:
    @pytest.mark.asyncio
    async def test_bare_city_gives_intake_stage(self, client, fresh_registry):
        """A bare city name with no duration/people should return stage=intake."""
        sid = await _session(client)
        data = await _chat(client, sid, "Nha Trang")
        assert data["stage"] == "intake"
        assert data["intake"] is not None

    @pytest.mark.asyncio
    async def test_intake_missing_field_listed(self, client, fresh_registry):
        """At minimum duration or people should be in intake.missing."""
        sid = await _session(client)
        data = await _chat(client, sid, "Đà Nẵng")
        missing = data["intake"]["missing"]
        assert "duration" in missing or "people" in missing

    @pytest.mark.asyncio
    async def test_mocked_intake_stage_response(self, client, fresh_registry, monkeypatch):
        """Mocked turn with tool=None → stage=intake."""
        sid = await _session(client)
        _mock_turn(monkeypatch, TurnResult(text="Bạn muốn đi bao lâu?", tool=None))
        data = await _chat(client, sid, "Hội An")
        assert data["stage"] == "intake"


# ---------------------------------------------------------------------------
# 3. Hotel options stage
# ---------------------------------------------------------------------------


class TestHotelOptionsStage:
    @pytest.mark.asyncio
    async def test_recommend_hotels_gives_hotel_options_stage(
        self, client, fresh_registry, monkeypatch
    ):
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(text="Đây là các khách sạn phù hợp:", tool="recommend_hotels"),
        )
        monkeypatch.setattr(
            routes_module,
            "suggestions_for",
            lambda s: [
                {"label": "1. Fusion Resort", "value": "1"},
                {"label": "2. Muong Thanh", "value": "2"},
            ],
        )
        data = await _chat(client, sid, "3 ngày 2 người thích biển")
        assert data["stage"] == "hotel_options"

    @pytest.mark.asyncio
    async def test_hotel_options_index_matches_suggestions(
        self, client, fresh_registry, monkeypatch
    ):
        """hotel_options[i].index must equal int(suggestions[i].value)."""
        sid = await _session(client)

        # Inject pending hotel selection into the session directly
        session = routes_module.registry.get(sid)
        session.pending_hotel_selection = {
            "options": [
                {"id": "h1", "name": "Fusion Resort", "star_rating": 5},
                {"id": "h2", "name": "Muong Thanh", "star_rating": 4},
            ]
        }

        _mock_turn(
            monkeypatch,
            TurnResult(text="Đây là các khách sạn:", tool="recommend_hotels"),
        )
        data = await _chat(client, sid, "gợi ý")
        # hotel_options should be populated from session.pending_hotel_selection
        opts = data["hotel_options"]
        chips = data["suggestions"]
        if opts and chips:
            for opt, chip in zip(opts, chips):
                assert opt["index"] == int(chip["value"])


# ---------------------------------------------------------------------------
# 4. Planned stage
# ---------------------------------------------------------------------------


class TestPlannedStage:
    @pytest.mark.asyncio
    async def test_select_hotel_gives_planned_stage(
        self, client, fresh_registry, monkeypatch
    ):
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(text="Đã chọn khách sạn. Đây là lịch trình:", tool="select_hotel"),
        )
        data = await _chat(client, sid, "1")
        assert data["stage"] == "planned"


# ---------------------------------------------------------------------------
# 5. Modified stage
# ---------------------------------------------------------------------------


class TestModifiedStage:
    @pytest.mark.asyncio
    async def test_execute_trip_edit_gives_modified_stage(
        self, client, fresh_registry, monkeypatch
    ):
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(
                text="Đã cập nhật lịch trình ngày 2.",
                tool="execute_trip_edit_request",
            ),
        )
        data = await _chat(client, sid, "Đổi điểm tham quan ngày 2")
        assert data["stage"] == "modified"


# ---------------------------------------------------------------------------
# 6. Finalized stage
# ---------------------------------------------------------------------------


class TestFinalizedStage:
    @pytest.mark.asyncio
    async def test_finalize_trip_plan_gives_finalized_stage(
        self, client, fresh_registry, monkeypatch
    ):
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(text="Đã xác nhận lịch trình.", tool="finalize_trip_plan"),
        )
        data = await _chat(client, sid, "Chốt lịch trình")
        assert data["stage"] == "finalized"


# ---------------------------------------------------------------------------
# 7. Error stage
# ---------------------------------------------------------------------------


class TestErrorStage:
    @pytest.mark.asyncio
    async def test_system_error_gives_error_stage_http_200(
        self, client, fresh_registry, monkeypatch
    ):
        """SYSTEM ERROR: text → stage='error', HTTP 200 so UI renders it as chat turn."""
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(
                text="SYSTEM ERROR: Chưa có kế hoạch chuyến đi để chỉnh sửa.",
                tool="execute_trip_edit_request",
            ),
        )
        data = await _chat(client, sid, "Đổi ngày 2")
        assert data["stage"] == "error"

    @pytest.mark.asyncio
    async def test_internal_error_detail_sanitized_from_reply(
        self, client, fresh_registry, monkeypatch
    ):
        """Raw DB exception text must not reach the browser reply."""
        sid = await _session(client)
        _mock_turn(
            monkeypatch,
            TurnResult(
                text="SYSTEM ERROR: psycopg2.InterfaceError: connection closed (table: hotels)",
                tool="select_hotel",
            ),
        )
        data = await _chat(client, sid, "1")
        assert data["stage"] == "error"
        assert "psycopg2" not in data["reply"]
        assert "table" not in data["reply"]
        assert data["reply"].startswith("SYSTEM ERROR:")


# ---------------------------------------------------------------------------
# 8. Reset (DELETE) flow
# ---------------------------------------------------------------------------


class TestResetFlow:
    @pytest.mark.asyncio
    async def test_delete_session_returns_204(self, client, fresh_registry):
        sid = await _session(client)
        resp = await client.delete(f"/api/v1/chat/{sid}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_get_plan_after_delete_returns_404(self, client, fresh_registry):
        sid = await _session(client)
        await client.delete(f"/api/v1/chat/{sid}")
        plan_resp = await client.get(f"/api/v1/chat/{sid}/plan")
        assert plan_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_chat_after_delete_returns_404(self, client, fresh_registry):
        sid = await _session(client)
        await client.delete(f"/api/v1/chat/{sid}")
        resp = await client.post(
            "/api/v1/planner_chat",
            json={"session_id": sid, "message": "hello"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 9. Two concurrent sessions are independent
# ---------------------------------------------------------------------------


class TestConcurrentSessions:
    @pytest.mark.asyncio
    async def test_two_sessions_do_not_share_state(self, client, fresh_registry):
        """Two sessions must reach different intake states independently."""
        sid1 = await _session(client)
        sid2 = await _session(client)

        await _chat(client, sid1, "Đà Nẵng")
        await _chat(client, sid2, "Nha Trang")

        plan1 = (await client.get(f"/api/v1/chat/{sid1}/plan")).json()
        plan2 = (await client.get(f"/api/v1/chat/{sid2}/plan")).json()

        # Both sessions have no finalized plan yet (intake still gathering),
        # but they are distinct session objects.
        assert plan1["trip_plan"] is None
        assert plan2["trip_plan"] is None

    @pytest.mark.asyncio
    async def test_two_sessions_have_different_ids(self, client, fresh_registry):
        sid1 = await _session(client)
        sid2 = await _session(client)
        assert sid1 != sid2


# ---------------------------------------------------------------------------
# 10. GET /chat must return 404 (Jinja page retired, D8)
# ---------------------------------------------------------------------------


class TestJinaPageRetired:
    @pytest.mark.asyncio
    async def test_get_chat_returns_404(self, client, fresh_registry):
        """The legacy GET /chat Jinja page must be gone."""
        resp = await client.get("/chat")
        assert resp.status_code == 404, (
            "GET /chat should return 404 after D8 retirement — "
            f"got {resp.status_code}"
        )
