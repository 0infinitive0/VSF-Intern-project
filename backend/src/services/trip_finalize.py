"""`finalize_session_trip` — locks a session's trip plan and saves it as a
reusable, embedded template.

Extracted from the orphaned `agents/tools/finalize_itinerary.py` tool
(dead code: nothing imported it — no graph node, no HTTP route, and
`finalize` was already one of `extract_patch`'s six intent labels with no
consumer). The logic itself was already correct; this module is that same
logic with the `ToolRuntime`/`Command` wrapper removed so `routes.py` can
call it directly, and `ItineraryStore.finalize_trip_data` (the actual
persist + embed) is left untouched — `create_golden_trip_3d` also depends
on it (impact analysis: LOW, 2 direct callers, both preserved).

Two properties of `ItineraryStore.finalize_trip_data` this module leans on
rather than re-implements:
- Embedding failure is non-fatal. It returns `embedding_saved: False` +
  `embedding_error` instead of raising, so a transient embedding-service
  outage never blocks the lock itself — only the reuse-template's vector
  stays retryable via `ItineraryStore.refresh_embedding`.
- The `finalize_itinerary` RPC returns `already_finalized`, so calling this
  twice for the same itinerary is safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.services.itinerary_reuse import ItineraryReuseQuery
from src.services.itinerary_store import ItineraryStore, ItineraryStoreError
from src.services.trip_formatter import parse_duration_to_days
from src.services.trip_planner import _current_trip_parameters, _get_destination_id

__all__ = ["FinalizeTripError", "finalize_session_trip", "is_trip_finalized"]


class FinalizeTripError(ValueError):
    """A session's trip could not be finalized — message is user-facing."""


def is_trip_finalized(trip_data: Mapping[str, Any] | None) -> bool:
    """True once `finalize_session_trip` has already locked this trip.

    Single source of truth for the "Finalized" check, shared by the graph
    lock guard (`nodes/supervisor.py`) and the one route that reaches a
    writer worker without going through the supervisor at all —
    `POST /hotels/change`'s `Command(goto="hotel_node", ...)` direct entry
    (`routes.py::_rerun_hotel_search`). The frontend also hides that
    control once finalized, but hiding a button is not an access guard."""
    itineraries = (trip_data or {}).get("itineraries") or []
    itinerary = itineraries[0] if isinstance(itineraries, list) and itineraries else itineraries
    if not isinstance(itinerary, dict):
        return False
    return str(itinerary.get("status") or "").casefold() == "finalized"


def finalize_session_trip(trip_data: Mapping[str, Any]) -> Mapping[str, Any]:
    """Persist, lock, and embed the itinerary in `trip_data`.

    Mutates and returns a copy of `trip_data` with `itineraries[0]["status"]`
    set to `"Finalized"` and `["summary"]` set to the generated summary — the
    caller (routes.py) writes this back into graph state and re-persists the
    session checkpoint. Raises `FinalizeTripError` for anything the caller
    should turn into an HTTP 4xx; any other exception is a real failure the
    caller should let become a 500.
    """
    if is_trip_finalized(trip_data):
        raise FinalizeTripError("Lịch trình này đã được xác nhận rồi.")

    itineraries = trip_data.get("itineraries") or [{}]
    itinerary = dict(itineraries[0] if isinstance(itineraries, list) else itineraries)

    destination, duration, people, preferences = _current_trip_parameters(trip_data)
    destination_id = str(itinerary.get("destination_id") or _get_destination_id(destination) or "")
    if not destination_id:
        raise FinalizeTripError("Không xác định được điểm đến của kế hoạch hiện tại.")

    number_of_people = int("".join(filter(str.isdigit, people)) or 1)
    child_context = f"{people} {preferences}".casefold()
    child_focused = any(
        keyword in child_context
        for keyword in ("trẻ em", "tre em", "children", "child", "kids", "gia đình", "gia dinh")
    )
    reuse_query = ItineraryReuseQuery(
        destination_id=destination_id,
        destination_name=destination,
        duration_days=parse_duration_to_days(duration),
        number_of_adults=number_of_people,
        preferences=tuple(part.strip() for part in preferences.split(",") if part.strip()),
        child_focused=child_focused,
        hotel_id=str(itinerary.get("hotel_id") or (trip_data.get("hotel") or {}).get("id") or ""),
        planning_constraints=dict(itinerary.get("planning_constraints") or {}),
    )

    updated_trip_data = dict(trip_data)
    updated_trip_data["itineraries"] = [itinerary, *itineraries[1:]] if isinstance(itineraries, list) else [itinerary]

    try:
        store = ItineraryStore.from_default()
        store.persist_itinerary_bundle(updated_trip_data)
        result = store.finalize_trip_data(updated_trip_data, reuse_query)
    except ItineraryStoreError as exc:
        raise FinalizeTripError(f"Xác nhận lịch trình thất bại: {exc}") from exc

    itinerary["status"] = "Finalized"
    itinerary["summary"] = result.get("summary")
    return {
        "trip_data": updated_trip_data,
        "status": "Finalized",
        "summary": result.get("summary"),
        "embedding_saved": bool(result.get("embedding_saved", result.get("has_embedding", False))),
    }
