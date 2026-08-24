"""`run_turn` (turn_runner.py) — continuing to chat on a session whose
LangGraph checkpoint was evicted by `SessionRegistry.evict_expired()`
(session.py, default 2h idle).

Companion to `test_restore_endpoint.py`'s `TestCheckpointEvictedFallback`:
that one covers the read-only `GET /chat/{id}/restore` view, this one
covers actually sending another message on such a session. Before this fix,
`app.get_state(config).values` came back empty and the turn ran as if the
guest had never built a trip at all -- every tool reading `trip_data` from
state (`modify_trip_plan` included) would report "Chưa có kế hoạch chuyến
đi" for a trip that, from the guest's own chat transcript, plainly still
exists.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import src.agents.graph.turn_runner as turn_runner


class _FakeApp:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get_state(self, _config):
        return SimpleNamespace(values=self._values, interrupts=())


class _FakeItineraryStore:
    def __init__(self, trip_data: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._trip_data = trip_data
        self._error = error
        self.calls: list[str] = []

    def load_session_trip_data_by_session(self, session_id: str) -> dict[str, Any] | None:
        self.calls.append(session_id)
        if self._error is not None:
            raise self._error
        return self._trip_data


_RECOVERED_TRIP_DATA = {
    "hotel": {"id": "hotel-1", "name": "Vinpearl Resort", "coordinates": "16.05,108.20"},
    "itineraries": [{"id": "it-1", "destination_id": "d-1", "duration_days": 3, "status": "Draft"}],
    "itinerary_items": [],
}


def _fake_drive_turn(captured: dict[str, Any]):
    def _run(app, config, turn_input, *, stream: bool) -> dict:
        captured["turn_input"] = turn_input
        return {"response": {"session_id": "s1", "reply": "ok", "stage": "planned"}}

    return _run


class TestRecoversTripDataForAFreshTurn:
    def test_injects_recovered_trip_data_into_the_turn_input(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict[str, Any] = {}
        monkeypatch.setattr(turn_runner, "_drive_turn", _fake_drive_turn(captured))
        fake_store = _FakeItineraryStore(trip_data=_RECOVERED_TRIP_DATA)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        turn_runner.run_turn(_FakeApp({}), "s1", "đổi khách sạn", "vi")

        assert fake_store.calls == ["s1"]
        assert captured["turn_input"]["trip_data"] == _RECOVERED_TRIP_DATA

    def test_preserves_other_extra_state_keys_already_being_merged(self, monkeypatch: pytest.MonkeyPatch):
        """`extra_state` is the same channel `selected_hotel_id` (POST
        /hotels/select) already uses -- recovering trip_data must not clobber
        a caller-supplied key already headed into this turn's input."""
        captured: dict[str, Any] = {}
        monkeypatch.setattr(turn_runner, "_drive_turn", _fake_drive_turn(captured))
        fake_store = _FakeItineraryStore(trip_data=_RECOVERED_TRIP_DATA)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        turn_runner.run_turn(_FakeApp({}), "s1", "chọn khách sạn 1", "vi", extra_state={"selected_hotel_id": "h-1"})

        assert captured["turn_input"]["selected_hotel_id"] == "h-1"
        assert captured["turn_input"]["trip_data"] == _RECOVERED_TRIP_DATA

    def test_a_session_with_no_durable_itinerary_runs_the_turn_unchanged(self, monkeypatch: pytest.MonkeyPatch):
        """No itinerary row for this session (it genuinely never built a
        trip) -- the turn must still run, just without a recovered trip_data
        key, same as before this fix existed."""
        captured: dict[str, Any] = {}
        monkeypatch.setattr(turn_runner, "_drive_turn", _fake_drive_turn(captured))
        fake_store = _FakeItineraryStore(trip_data=None)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        turn_runner.run_turn(_FakeApp({}), "s1", "xin chào", "vi")

        assert fake_store.calls == ["s1"]
        assert "trip_data" not in captured["turn_input"]

    def test_a_durable_lookup_failure_does_not_fail_the_turn(self, monkeypatch: pytest.MonkeyPatch):
        from src.services.itinerary_store import ItineraryStoreError

        captured: dict[str, Any] = {}
        monkeypatch.setattr(turn_runner, "_drive_turn", _fake_drive_turn(captured))
        fake_store = _FakeItineraryStore(error=ItineraryStoreError("supabase unreachable"))
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        result = turn_runner.run_turn(_FakeApp({}), "s1", "xin chào", "vi")

        assert result.session_id == "s1"
        assert "trip_data" not in captured["turn_input"]

    def test_an_intact_checkpoint_never_triggers_the_durable_lookup(self, monkeypatch: pytest.MonkeyPatch):
        """The common case (checkpoint still alive) must not pay for an
        extra Supabase round trip on every single turn."""
        captured: dict[str, Any] = {}
        monkeypatch.setattr(turn_runner, "_drive_turn", _fake_drive_turn(captured))
        fake_store = _FakeItineraryStore(trip_data=_RECOVERED_TRIP_DATA)
        monkeypatch.setattr(
            "src.services.itinerary_store.ItineraryStore.from_default",
            classmethod(lambda cls: fake_store),
        )

        turn_runner.run_turn(
            _FakeApp({"trip_data": {"destination": "Đà Nẵng"}}), "s1", "thêm 1 hoạt động ngày 1", "vi"
        )

        assert fake_store.calls == []
        assert "trip_data" not in captured["turn_input"]
