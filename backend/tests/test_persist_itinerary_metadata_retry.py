"""`trip_planner._persist_itinerary_metadata` — the durable write meant to
survive past the LangGraph checkpoint's 2h idle TTL (`itineraries` has no
TTL of its own). A 2026-08-25 incident found it failing completely
silently: a fully-built itinerary was shown to the guest as done, its
durable write failed with no exception reaching anyone, and once the
checkpoint expired there was nothing left to recover (see
`session_store.recover_trip_data`'s doc comment for the full story — that
fix gives `trip_data` a second, independent durable copy; these tests cover
the complementary hardening of the original write path itself: retry
transient failures, and make an unrecoverable one loud instead of a
truncated `logger.warning`).
"""

from __future__ import annotations

from typing import Any

import pytest

import src.services.trip_planner as trip_planner
from src.services.itinerary_store import ItineraryStoreError


def _trip_data(itinerary_id: str = "it-1", session_id: str = "sess-1") -> dict[str, Any]:
    return {
        "itineraries": [
            {
                "id": itinerary_id,
                "session_id": session_id,
                "hotel_id": "hotel-1",
                "status": "Draft",
                "duration_days": 2,
            }
        ],
    }


class _FlakyItineraryStore:
    """Fails `persist_itinerary_bundle` the first `fail_times` calls, then
    succeeds. `calls` records every attempt for the test to count."""

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self.calls = 0

    def persist_itinerary_bundle(self, _trip_data: dict[str, Any]) -> str:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ItineraryStoreError("transient supabase blip")
        return "ok"


class _AlwaysFailingItineraryStore:
    def __init__(self) -> None:
        self.calls = 0

    def persist_itinerary_bundle(self, _trip_data: dict[str, Any]) -> str:
        self.calls += 1
        raise ItineraryStoreError("permanently unreachable")


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries are for real transient failures, not for this test suite's
    own runtime — the backoff itself isn't what's under test."""
    monkeypatch.setattr(trip_planner.time, "sleep", lambda _seconds: None)


class TestRetriesTransientFailures:
    def test_succeeds_after_two_failed_attempts_without_falling_back(self, monkeypatch: pytest.MonkeyPatch):
        _no_sleep(monkeypatch)
        fake_store = _FlakyItineraryStore(fail_times=2)
        monkeypatch.setattr(trip_planner.ItineraryStore, "from_default", classmethod(lambda cls: fake_store))

        itineraries_table_touched = False

        class _RecordingTable:
            def __init__(self, name: str) -> None:
                self._name = name

            def upsert(self, *_args, **_kwargs):
                nonlocal itineraries_table_touched
                if self._name == "itineraries":
                    itineraries_table_touched = True
                return self

            def execute(self):
                return None

        class _RecordingClient:
            def table(self, name: str):
                return _RecordingTable(name)

        # The raw-upsert fallback only touches `itineraries` once the RPC
        # path is exhausted -- asserting it stays untouched proves the
        # retry itself is what recovered, not the fallback.
        monkeypatch.setattr(trip_planner, "get_supabase_client", lambda: _RecordingClient())

        trip_planner._persist_itinerary_metadata(_trip_data())

        assert fake_store.calls == 3
        assert itineraries_table_touched is False

    def test_falls_back_to_the_raw_upsert_after_exhausting_retries(self, monkeypatch: pytest.MonkeyPatch, caplog):
        import logging

        _no_sleep(monkeypatch)
        upserted_tables: list[str] = []

        class _RecordingTable:
            def __init__(self, name: str) -> None:
                self._name = name

            def upsert(self, _payload, **_kwargs):
                upserted_tables.append(self._name)
                return self

            def execute(self):
                return None

        class _RecordingClient:
            def table(self, name: str):
                return _RecordingTable(name)

        monkeypatch.setattr(trip_planner, "get_supabase_client", lambda: _RecordingClient())
        fake_store = _AlwaysFailingItineraryStore()
        monkeypatch.setattr(trip_planner.ItineraryStore, "from_default", classmethod(lambda cls: fake_store))

        with caplog.at_level(logging.ERROR, logger="src.services.trip_planner"):
            trip_planner._persist_itinerary_metadata(_trip_data())

        # 1 initial attempt + 2 retries (_PERSIST_RETRY_DELAYS_SECONDS has 2
        # entries) before giving up on the RPC path.
        assert fake_store.calls == 3
        assert "itineraries" in upserted_tables
        # The failure must be loud (full traceback), not the old truncated
        # `logger.warning` that let the 2026-08-25 incident go unnoticed.
        assert any(record.levelno >= logging.ERROR for record in caplog.records)
