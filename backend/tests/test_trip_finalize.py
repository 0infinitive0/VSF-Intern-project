"""`services/trip_finalize.py` — the user-facing entry point for what used to
be the orphaned `finalize_trip_plan` tool (nothing called it: no graph node,
no HTTP route). No test here touches a real Supabase/embedding call —
`ItineraryStore.from_default()` is monkeypatched to a fake in every case
that could reach it.
"""

from __future__ import annotations

import pytest

import src.services.trip_finalize as trip_finalize_module
from src.services.trip_finalize import FinalizeTripError, finalize_session_trip, is_trip_finalized


def _trip_data(*, status: str = "Draft", **itinerary_overrides) -> dict:
    itinerary = {
        "id": "itin-1",
        "destination_id": "dest-1",
        "hotel_id": "hotel-1",
        "duration_days": 2,
        "number_of_adults": 2,
        "preferences": ["Đà Nẵng", "biển"],
        "status": status,
        **itinerary_overrides,
    }
    return {"hotel": {"id": "hotel-1"}, "itineraries": [itinerary], "itinerary_items": []}


class _FakeItineraryStore:
    """Records calls; `finalize_trip_data` returns a canned result — the
    real one's own embedding-failure behavior is `ItineraryStore`'s
    responsibility (itinerary_store.py), not this module's to re-test."""

    def __init__(self, finalize_result: dict | None = None, *, raise_on_finalize: Exception | None = None):
        self.persisted: list[dict] = []
        self.finalize_calls: list[tuple] = []
        self._finalize_result = finalize_result or {"summary": "2 ngày ở Đà Nẵng", "embedding_saved": True}
        self._raise_on_finalize = raise_on_finalize

    def persist_itinerary_bundle(self, trip_data):
        self.persisted.append(trip_data)
        return trip_data["itineraries"][0]["id"]

    def finalize_trip_data(self, trip_data, reuse_query):
        self.finalize_calls.append((trip_data, reuse_query))
        if self._raise_on_finalize:
            raise self._raise_on_finalize
        return self._finalize_result


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: _FakeItineraryStore) -> None:
    monkeypatch.setattr(trip_finalize_module.ItineraryStore, "from_default", staticmethod(lambda: store))
    monkeypatch.setattr(trip_finalize_module, "_get_destination_id", lambda _name: "dest-1")


# --- is_trip_finalized: the shared predicate ---------------------------------


class TestIsTripFinalized:
    def test_true_for_a_finalized_itinerary(self):
        assert is_trip_finalized(_trip_data(status="Finalized")) is True

    def test_case_insensitive(self):
        assert is_trip_finalized(_trip_data(status="finalized")) is True
        assert is_trip_finalized(_trip_data(status="FINALIZED")) is True

    def test_false_for_a_draft(self):
        assert is_trip_finalized(_trip_data(status="Draft")) is False

    def test_false_for_no_trip_data(self):
        assert is_trip_finalized(None) is False
        assert is_trip_finalized({}) is False

    def test_false_for_malformed_itinerary_shape(self):
        """Never raises on unexpected shapes -- both callers (the graph lock
        guard, the /hotels/change defensive check) run on every turn, so a
        malformed record must fail open (not finalized), not crash the turn."""
        assert is_trip_finalized({"itineraries": ["not-a-dict"]}) is False
        assert is_trip_finalized({"itineraries": []}) is False


# --- finalize_session_trip: the happy path and its failure modes ------------


def test_finalizes_a_draft_and_returns_the_summary(monkeypatch):
    store = _FakeItineraryStore(finalize_result={"summary": "2 ngày ở Đà Nẵng", "embedding_saved": True})
    _patch_store(monkeypatch, store)

    result = finalize_session_trip(_trip_data())

    assert result["status"] == "Finalized"
    assert result["summary"] == "2 ngày ở Đà Nẵng"
    assert result["embedding_saved"] is True
    assert result["trip_data"]["itineraries"][0]["status"] == "Finalized"
    assert store.persisted, "persist_itinerary_bundle must run before finalize_trip_data"


def test_embedding_failure_is_non_fatal(monkeypatch):
    """The whole point of preserving `ItineraryStore.finalize_trip_data`'s
    contract: an embedding-service outage must still lock the trip. Only
    the reuse-template's vector stays missing/retryable."""
    store = _FakeItineraryStore(
        finalize_result={"summary": "2 ngày ở Đà Nẵng", "embedding_saved": False, "embedding_error": "timeout"}
    )
    _patch_store(monkeypatch, store)

    result = finalize_session_trip(_trip_data())

    assert result["status"] == "Finalized"
    assert result["embedding_saved"] is False


def test_double_submit_is_rejected_before_touching_the_store(monkeypatch):
    store = _FakeItineraryStore()
    _patch_store(monkeypatch, store)

    with pytest.raises(FinalizeTripError):
        finalize_session_trip(_trip_data(status="Finalized"))

    assert store.persisted == [], "already-finalized must short-circuit, never re-persist"
    assert store.finalize_calls == []


def test_no_destination_id_is_rejected(monkeypatch):
    store = _FakeItineraryStore()
    monkeypatch.setattr(trip_finalize_module.ItineraryStore, "from_default", staticmethod(lambda: store))
    monkeypatch.setattr(trip_finalize_module, "_get_destination_id", lambda _name: None)

    trip_data = _trip_data(destination_id="")
    trip_data["itineraries"][0]["preferences"] = []  # no destination name either

    with pytest.raises(FinalizeTripError):
        finalize_session_trip(trip_data)

    assert store.persisted == []


def test_store_failure_is_wrapped_as_a_user_facing_error(monkeypatch):
    from src.services.itinerary_store import ItineraryStoreError

    store = _FakeItineraryStore(raise_on_finalize=ItineraryStoreError("RPC unreachable"))
    _patch_store(monkeypatch, store)

    with pytest.raises(FinalizeTripError):
        finalize_session_trip(_trip_data())


def test_child_focused_is_detected_from_people_or_preferences(monkeypatch):
    """Not asserted on the return value (reuse_query is internal) -- asserted
    via the store's spy call, since that is the only observable effect."""
    store = _FakeItineraryStore()
    _patch_store(monkeypatch, store)

    trip_data = _trip_data()
    trip_data["itineraries"][0]["preferences"] = ["Đà Nẵng", "gia đình"]

    finalize_session_trip(trip_data)

    _saved_trip_data, reuse_query = store.finalize_calls[0]
    assert reuse_query.child_focused is True


def test_original_trip_data_mapping_is_not_mutated_in_place(monkeypatch):
    """`trip_data` here is whatever the caller (routes.py) read straight off
    `app.get_state(...).values` -- mutating it in place would corrupt the
    caller's own read before it decides what to write back."""
    store = _FakeItineraryStore()
    _patch_store(monkeypatch, store)

    original = _trip_data()
    original_status = original["itineraries"][0]["status"]

    finalize_session_trip(original)

    assert original["itineraries"][0]["status"] == original_status
