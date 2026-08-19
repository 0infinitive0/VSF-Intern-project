"""`session_store.summarize`'s booking_state override, and
`booking_states_for_sessions`' batched lookup + paid-beats-holding
precedence — sidebar "Đang giữ phòng"/"Đã thanh toán" badge (plan
260818-vnpay-payment-and-email-confirmation's addendum 2)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.services import session_store
from src.services.session_store import (
    _CONTEXT_SCHEMA_VERSION,
    _CONTEXT_SCHEMA_VERSION_V3,
    booking_states_for_sessions,
    summarize,
)


def _v3_row(status: str = "draft") -> dict:
    return {
        "session_id": "s1",
        "context_data": {
            "schema_version": _CONTEXT_SCHEMA_VERSION_V3,
            "ui_summary": {"status": status, "destination": "Đà Nẵng", "duration_days": 3},
        },
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }


def _legacy_row(trip_data: dict | None = None) -> dict:
    return {
        "session_id": "s1",
        "context_data": {"intake": {}, "trip_data": trip_data or {}},
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# summarize() — booking_state override, both branches
# ---------------------------------------------------------------------------


def test_v3_branch_summarize_with_no_booking_state_behaves_as_before():
    assert summarize(_v3_row("draft"))["status"] == "draft"
    assert summarize(_v3_row("finalized"))["status"] == "completed"


def test_v3_branch_booking_state_holding_overrides_a_draft_itinerary():
    assert summarize(_v3_row("draft"), "holding")["status"] == "holding"


def test_v3_branch_a_finalized_itinerary_outranks_paid():
    """"completed" already exclusively means "the itinerary is Finalized"
    (`_ui_summary`'s own definition) -- the finalize feature requires
    payment FIRST, so a finalized session is now always also paid. Before
    this precedence flip, "paid" permanently masked "completed" and the
    badge could never show the later, more advanced state (plan
    260819-finalize-itinerary's addendum 12)."""
    assert summarize(_v3_row("finalized"), "paid")["status"] == "completed"


def test_v3_branch_a_finalized_itinerary_outranks_holding_too():
    assert summarize(_v3_row("finalized"), "holding")["status"] == "completed"


def test_v2_branch_also_respects_booking_state_override():
    row = _v3_row("draft")
    row["context_data"]["schema_version"] = _CONTEXT_SCHEMA_VERSION
    assert summarize(row, "holding")["status"] == "holding"


def test_legacy_branch_summarize_with_no_booking_state_behaves_as_before():
    assert summarize(_legacy_row())["status"] == "draft"
    assert summarize(_legacy_row({"destination": "Hội An"}))["status"] == "completed"


def test_legacy_branch_booking_state_holding_overrides_no_trip_data():
    assert summarize(_legacy_row(), "holding")["status"] == "holding"


def test_legacy_branch_booking_state_paid_overrides_completed():
    assert summarize(_legacy_row({"destination": "Hội An"}), "paid")["status"] == "paid"


def test_booking_state_none_string_is_ignored_not_treated_as_a_value():
    # Guards against a future caller accidentally passing the string "None"
    # or an unrecognized status and silently corrupting the badge.
    assert summarize(_v3_row("draft"), "something_else")["status"] == "draft"


# ---------------------------------------------------------------------------
# booking_states_for_sessions() — batched lookup + precedence
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def execute(self):
        return self

    @property
    def data(self):
        return self._rows


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls = 0

    def table(self, _name):
        self.calls += 1
        return _FakeQuery(self._rows)


def test_empty_session_ids_short_circuits_without_a_query(monkeypatch):
    client = _FakeClient([])
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: client)

    assert booking_states_for_sessions([]) == {}
    assert client.calls == 0


def test_confirmed_beats_reserved_for_the_same_session(monkeypatch):
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    rows = [
        {"session_id": "s1", "status": "RESERVED", "expires_at": future},
        {"session_id": "s1", "status": "CONFIRMED", "expires_at": None},
    ]
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: _FakeClient(rows))

    assert booking_states_for_sessions(["s1"]) == {"s1": "paid"}


def test_reserved_and_unexpired_maps_to_holding(monkeypatch):
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    rows = [{"session_id": "s2", "status": "RESERVED", "expires_at": future}]
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: _FakeClient(rows))

    assert booking_states_for_sessions(["s2"]) == {"s2": "holding"}


def test_expired_reserved_row_is_ignored(monkeypatch):
    past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    rows = [{"session_id": "s3", "status": "RESERVED", "expires_at": past}]
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: _FakeClient(rows))

    assert booking_states_for_sessions(["s3"]) == {}


def test_different_sessions_get_independent_states(monkeypatch):
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    rows = [
        {"session_id": "s1", "status": "CONFIRMED", "expires_at": None},
        {"session_id": "s2", "status": "RESERVED", "expires_at": future},
    ]
    monkeypatch.setattr(session_store, "_get_supabase_client", lambda: _FakeClient(rows))

    assert booking_states_for_sessions(["s1", "s2"]) == {"s1": "paid", "s2": "holding"}
