"""Response-payload derivation shared by the `respond` node and the restore
endpoint.

These functions used to live inside `nodes/respond.py` as private helpers,
which left `GET /chat/{id}/restore` with two bad options: import
underscore-prefixed names out of a graph node (an API-layer module reaching
into the execution plane, and past a name that says "not public"), or write a
second serialization. It wrote the second one — and it was wrong in every
field, silently, because nothing compares the two.

So they live here instead, and both callers import them:

                        ┌─ nodes/respond.py   (a live turn)
    response_payload.py ┤
                        └─ api/routes.py      (restoring a past one)

The dependency direction is one-way: this module imports `models.schemas`,
never the reverse (`tests/test_domain_layer_purity.py` guards the analogous
rule one layer down).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState
from src.models.schemas import IntakeStatus, to_hotel_options_payload
from src.services.hotel_selection import budget_option_labels
from src.services.trip_planner import _get_destination_names


def _slot_value(travel_state: TravelState, path: str) -> Any:
    slot = travel_state.get(path)
    return slot.value if slot.presence is Presence.SET else None


def format_duration(start_date: str | None, end_date: str | None) -> str | None:
    """Nights between the two dates, in the legacy plane's "N ngày" shape
    (`trip_intake.py`'s `_duration_from_stay_dates`) — `travel_state` only
    stores `dates.start`/`dates.end`, no standalone duration slot."""
    if not start_date or not end_date:
        return None
    try:
        nights = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
    except (TypeError, ValueError):
        return None
    return f"{nights} ngày" if nights > 0 else None


def budget_from_travel_state(travel_state: TravelState) -> tuple[float | None, float | None, bool]:
    """(min_price, max_price, skipped) from the budget.* slots.

    Presence-aware, not `_slot_value`: an explicit "no preference" answer
    (e.g. "bao nhieu cung duoc") sets budget.target to Presence.NOT_APPLICABLE
    (travel_state.py's tri-state model) -- `_slot_value` collapses that to the
    same None a never-asked slot returns, which would make a real skip
    indistinguishable from "not answered yet" and leave the frontend's intake
    widget re-asking forever (intake-budget-slider.tsx). min_price/max_price
    only surface the explicit budget.min/budget.max range the widget's
    dual-thumb slider actually produces; a bare budget.target value or
    budget.trip_total (a different unit -- whole trip, not per night) is
    intentionally left out of this shape.
    """
    target_slot = travel_state.get("budget.target")
    skipped = target_slot.presence is Presence.NOT_APPLICABLE
    min_slot = travel_state.get("budget.min")
    max_slot = travel_state.get("budget.max")
    min_price = min_slot.value if min_slot.presence is Presence.SET else None
    max_price = max_slot.value if max_slot.presence is Presence.SET else None
    return min_price, max_price, skipped


def hotel_options_from_task_results(state: TravelGraphState) -> list[dict[str, Any]]:
    """The hotels the last worker turn produced.

    They arrive nested in `task_results[-1]["hotel_search_result"]`;
    `TravelGraphState` has no top-level `hotel_options` key, which is exactly
    what the old restore handler read (and always got `[]` from).
    """
    task_results = state.get("task_results") or []
    if not task_results:
        return []
    hotel_search_result = task_results[-1].get("hotel_search_result")
    if not isinstance(hotel_search_result, dict):
        return []
    return [option.model_dump() for option in to_hotel_options_payload(hotel_search_result)]


#: The prefix `sanitize_system_error` (models/schemas.py) puts on every
#: user-facing failure. Not a loose convention: that function is the single
#: choke point every backend error passes through, and the prefix set it
#: preserves is itself under test (`_SAFE_ERROR_PREFIXES`, 16 entries, two
#: languages).
_SYSTEM_ERROR_PREFIX = "SYSTEM ERROR:"


def derive_stage(state: TravelGraphState, hotel_options: list[dict[str, Any]], reply: str) -> str:
    """The turn's stage.

    A failed turn outranks everything: a turn that broke is not a `planned`
    turn that happens to have gone wrong, and the frontend keys its error
    styling off this value alone (`use-chat-session.ts`'s
    `data.stage === 'error'`), never off the reply text.

    Reading the failure out of `reply` is a text check, which this codebase
    otherwise avoids — accepted here for two reasons, both narrow. It is the
    behavior the legacy plane already had (`session.py::derive_stage`'s own
    `result.text.startswith("SYSTEM ERROR:")`), so this restores a contract
    rather than inventing one; and there is exactly one place to look,
    because `sanitize_system_error` is the only way a user-facing error is
    produced. Replace it with an explicit `state["turn_failed"]` the day a
    node needs to report a failure without going through that function —
    that is the signal this check has outlived its justification.

    After the error branch: `missing_slots` is checked first because it is
    the only signal that intake is genuinely incomplete — `ask_slot` is its
    sole writer and `load_context` deliberately does not reset it.
    `trip_data` outranks `hotel_options` next, per the legacy precedence: a
    complete plan outranks a pending hotel pick. `hotel_options` is passed in
    already computed so the two response fields can never disagree.
    """
    if reply.startswith(_SYSTEM_ERROR_PREFIX):
        return "error"
    if state.get("missing_slots"):
        return "intake"
    if state.get("trip_data"):
        return "planned"
    if hotel_options:
        return "hotel_options"
    return "intake"


def intake_status_from_travel_state(travel_state: TravelState) -> IntakeStatus:
    destination = _slot_value(travel_state, "destination")
    people_count = _slot_value(travel_state, "people")
    people = f"{int(people_count)} người" if people_count is not None else None
    start_date = _slot_value(travel_state, "dates.start")
    end_date = _slot_value(travel_state, "dates.end")
    duration = format_duration(start_date, end_date)
    min_price, max_price, budget_skipped = budget_from_travel_state(travel_state)

    # Same four gated keys the legacy plane's IntakeStatus.from_state used —
    # intake-checklist-rows.ts's MISSING_KEYS reads exactly these names.
    missing = [
        name
        for name, value in (
            ("destination", destination),
            ("people", people),
            ("start_date", start_date),
            ("duration", duration),
        )
        if value is None
    ]

    return IntakeStatus(
        destination=destination,
        duration=duration,
        start_date=start_date,
        end_date=end_date,
        people=people,
        preferences=list(_slot_value(travel_state, "preferences.themes") or []),
        companions=_slot_value(travel_state, "preferences.companions"),
        pace=_slot_value(travel_state, "preferences.pace"),
        day_rhythm=list(_slot_value(travel_state, "preferences.day_rhythm") or []),
        notes=_slot_value(travel_state, "preferences.notes") or "",
        available_destinations=[option.name for option in _get_destination_names() if option.name],
        budget_options=list(budget_option_labels()),
        min_price=min_price,
        max_price=max_price,
        budget_skipped=budget_skipped,
        missing=missing,
    )
