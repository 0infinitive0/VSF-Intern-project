"""`budget_check` — deterministic trip-total budget validation (Phase 14).

Reads `budget.trip_total` from `TravelState`, calls `_calculate_trip_budget`
on the current `trip_data` to get the known cost, and decides whether the
plan satisfies, is unknown-coverage, or exceeds the stated total.

When the known cost exceeds the total the node derives a per-night hotel
ceiling from the remaining allowance after subtracting known non-hotel
activity costs, runs one bounded re-plan pass (hotel search + unlocked-day
rebuild), then recomputes the budget.  If still over, it names the dominant
cost component and reports the shortfall — never silently returns an
over-budget plan.

**Bounded iteration.** Exactly one re-plan pass, then report.  No unbounded
optimisation loop (doc §38).

**Coverage honesty.** When `_calculate_trip_budget` returns `None` (no known
prices at all), or when known costs cover only a fraction of the plan, the
node reports coverage rather than claiming compliance — preserving the
existing "never invent missing prices" contract.

**Coexistence.**  `budget.trip_total` and `budget.max`/`budget.min` are
independent slots that do not overwrite each other.  The node reads both but
only acts on `trip_total`.

**locked_days.**  The re-plan pass honours `planning_constraints.locked_days`
exactly as `itinerary_node` does — only unlocked days are rebuilt.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState
from src.i18n import t
from src.services.hotel_selection import rank_hotel_candidates, select_hotel_candidates
from src.services.trip_formatter import format_budget_status
from src.services.trip_planner import (
    _calculate_trip_budget,
    _get_destination_id,
    _get_locked_days,
    _itinerary_record,
    rebuild_day_data,
)

logger = logging.getLogger(__name__)

_WORKER_NAME = "budget_check"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _known_hotel_total(hotel: dict[str, Any]) -> float | None:
    """Return the total hotel cost for the stay, or None if not known."""
    total = hotel.get("total_stay_price")
    if total is not None:
        try:
            return max(0.0, float(total))
        except (TypeError, ValueError):
            pass
    nightly = hotel.get("average_nightly_price") or hotel.get("lowest_price")
    nights = hotel.get("stay_night_count")
    if nightly is not None and nights is not None:
        try:
            return max(0.0, float(nightly) * max(0, int(nights)))
        except (TypeError, ValueError):
            pass
    return None


def _known_activity_total(items: list[dict[str, Any]]) -> float:
    """Sum of all known activity costs (excluding hotel)."""
    total = 0.0
    for item in items:
        cost = item.get("estimated_cost")
        if cost is not None:
            try:
                total += max(0.0, float(cost))
            except (TypeError, ValueError):
                pass
    return total


def _item_count_with_known_cost(items: list[dict[str, Any]]) -> int:
    return sum(1 for item in items if item.get("estimated_cost") is not None)


def _dominant_cost_name(
    hotel_total: float | None, activity_total: float, language: str
) -> str:
    if hotel_total is None or hotel_total < activity_total:
        return t("chi phí hoạt động", language)
    return t("chi phí khách sạn", language)


def _stay_nights(trip_data: dict[str, Any]) -> int | None:
    """Return number of nights from the itinerary record, or None."""
    try:
        itinerary = _itinerary_record(trip_data)
        duration = itinerary.get("duration_days")
        if duration:
            return max(1, int(duration))
    except (ValueError, TypeError):
        pass
    hotel = trip_data.get("hotel") or {}
    nights = hotel.get("stay_night_count")
    if nights is not None:
        try:
            return max(1, int(nights))
        except (TypeError, ValueError):
            pass
    return None


def _derive_per_night_ceiling(
    trip_total: float,
    activity_total: float,
    nights: int,
) -> float:
    """Derive a per-night hotel price ceiling.

    Subtracts the known activity total from the trip total to get the
    remaining hotel budget, then divides by nights.  Clamps to 0 if the
    activity costs alone already exceed the total (caller handles that case
    separately as over-budget).
    """
    hotel_allowance = max(0.0, trip_total - activity_total)
    return hotel_allowance / nights if nights > 0 else 0.0


# ---------------------------------------------------------------------------
# Trip-total constraint evaluation
# ---------------------------------------------------------------------------


def _check_trip_total(
    trip_data: dict[str, Any],
    trip_total: float,
    language: str,
) -> dict[str, Any]:
    """Evaluate the trip-total constraint against the current trip_data.

    Returns a dict with:
      status: "ok" | "over_budget" | "unknown_coverage"
      known_total: float | None
      coverage_fraction: float | None  (0-1, fraction of items with known cost)
      reply: str
      hotel_total: float | None
      activity_total: float
    """
    hotel = trip_data.get("hotel") or {}
    items = trip_data.get("itinerary_items") or []

    hotel_total = _known_hotel_total(hotel)
    activity_total = _known_activity_total(items)
    known_total = _calculate_trip_budget(hotel, items)

    total_items = len(items)
    items_with_cost = _item_count_with_known_cost(items)
    coverage_fraction: float | None = (
        items_with_cost / total_items if total_items > 0 else None
    )

    base_reply = format_budget_status(known_total, trip_total, items_with_cost, total_items, language)

    if known_total is None:
        return {
            "status": "unknown_coverage",
            "known_total": None,
            "coverage_fraction": coverage_fraction,
            "reply": base_reply,
            "hotel_total": hotel_total,
            "activity_total": activity_total,
        }

    if known_total <= trip_total:
        return {
            "status": "ok",
            "known_total": known_total,
            "coverage_fraction": coverage_fraction,
            "reply": base_reply,
            "hotel_total": hotel_total,
            "activity_total": activity_total,
        }

    # Over budget — name the dominant cost component
    dominant = _dominant_cost_name(hotel_total, activity_total, language)
    reply = base_reply + " " + t("Phần chiếm nhiều nhất là {dominant}.", language, dominant=dominant)
    return {
        "status": "over_budget",
        "known_total": known_total,
        "coverage_fraction": coverage_fraction,
        "reply": reply,
        "hotel_total": hotel_total,
        "activity_total": activity_total,
    }


# ---------------------------------------------------------------------------
# Re-plan pass (bounded: exactly one attempt)
# ---------------------------------------------------------------------------


def _replan_hotel_for_budget(
    trip_data: dict[str, Any],
    trip_total: float,
    activity_total: float,
    language: str,
) -> tuple[dict[str, Any], str | None]:
    """Derive a per-night ceiling and attempt one hotel search under it.

    Returns (updated_trip_data, error_message).
    error_message is None on success, non-None when no hotel was found.
    Does NOT mutate the incoming trip_data dict; returns a deep copy.
    """
    nights = _stay_nights(trip_data)
    if not nights:
        return trip_data, t(
            "Không thể tính ngân sách mỗi đêm vì chưa có thông tin số đêm lưu trú.",
            language,
        )

    per_night_ceiling = _derive_per_night_ceiling(trip_total, activity_total, nights)
    if per_night_ceiling <= 0:
        return trip_data, t(
            "Chi phí hoạt động đã vượt tổng ngân sách {total:,.0f} VND "
            "— không còn ngân sách cho khách sạn.",
            language,
            total=trip_total,
        )

    # select_hotel_candidates and rank_hotel_candidates are module-level imports
    # (see top of file) to allow test patching via the module's own namespace.

    itinerary: dict[str, Any] = {}
    try:
        itinerary = _itinerary_record(trip_data)
    except ValueError:
        pass

    preferences = list(itinerary.get("preferences") or [])
    destination = str(preferences[0]) if preferences else ""
    if not destination:
        return trip_data, t("Không thể xác định điểm đến để tìm lại khách sạn.", language)

    destination_id = _get_destination_id(destination)
    if not destination_id:
        return trip_data, t(
            "Không tìm thấy dữ liệu điểm đến cho {destination}.", language, destination=destination
        )

    people_count = int(itinerary.get("number_of_adults") or 1)
    people = str(people_count)
    start_date = itinerary.get("start_date")
    end_date = itinerary.get("end_date")

    current_hotel_id = (trip_data.get("hotel") or {}).get("id")
    exclude_ids = {current_hotel_id} if current_hotel_id else set()

    try:
        options = select_hotel_candidates(
            destination,
            destination_id,
            people,
            max_price=per_night_ceiling,
            start_date=start_date,
            end_date=end_date,
            exclude_hotel_ids=exclude_ids,
            min_guests=people_count,
        )
    except Exception as exc:
        logger.warning("budget_check replan: hotel search failed: %s", exc)
        return trip_data, t(
            "Tìm khách sạn trong ngân sách {ceiling:,.0f} VND/đêm thất bại: {exc}",
            language,
            ceiling=per_night_ceiling,
            exc=exc,
        )

    if not options:
        return trip_data, t(
            "Không tìm thấy khách sạn nào trong mức {ceiling:,.0f} VND/đêm tại {destination}.",
            language,
            ceiling=per_night_ceiling,
            destination=destination,
        )

    ranked = rank_hotel_candidates(options)
    new_hotel_data, _ = ranked[0]

    new_trip_data = copy.deepcopy(trip_data)
    new_trip_data["hotel"] = new_hotel_data
    return new_trip_data, None


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


def budget_check(state: TravelGraphState) -> dict[str, Any]:
    """Deterministic trip-total budget validation (Phase 14).

    Reads `budget.trip_total` from `TravelState`.  When it is not SET,
    this node is a pass-through (returns empty dict — no state mutation).

    When the total IS set:
    1. Computes the known trip total from `trip_data`.
    2. If within budget, reports compliance (with coverage caveat if needed).
    3. If over budget, attempts exactly one re-plan pass:
       a. Derives a per-night hotel ceiling from the remaining allowance
          after subtracting known activity costs.
       b. Re-searches hotels under that ceiling (excluding the current one).
       c. Rebuilds unlocked itinerary days with the new hotel.
       d. Recomputes the trip total.
    4. If still over budget after the re-plan pass, reports the dominant cost
       component and the shortfall — never silently returns an over-budget plan.
    """
    language = state.get("language") or "vi"
    travel_state = TravelState.from_dict(state.get("travel_state"))
    trip_total_slot = travel_state.get("budget.trip_total")

    # No trip_total set — pass through (compatible with the old stub body)
    if trip_total_slot.presence is not Presence.SET or trip_total_slot.value is None:
        return {}

    try:
        trip_total = float(trip_total_slot.value)
    except (TypeError, ValueError):
        return {}

    trip_data: dict[str, Any] = dict(state.get("trip_data") or {})
    if not trip_data:
        # No plan yet — nothing to check; don't block early question turns
        return {}

    # --- First evaluation ----------------------------------------------------
    evaluation = _check_trip_total(trip_data, trip_total, language)
    status = evaluation["status"]

    if status in ("ok", "unknown_coverage"):
        task_results = list(state.get("task_results") or [])
        task_results.append(
            {"worker": _WORKER_NAME, "status": status, "reply": evaluation["reply"]}
        )
        return {"task_results": task_results}

    # --- Over budget: attempt one re-plan pass --------------------------------
    activity_total: float = evaluation.get("activity_total") or 0.0
    logger.info(
        "budget_check: over budget total=%.0f limit=%.0f; attempting re-plan",
        evaluation.get("known_total") or 0,
        trip_total,
    )

    new_trip_data, replan_error = _replan_hotel_for_budget(
        trip_data, trip_total, activity_total, language
    )

    if replan_error:
        # Could not find a cheaper hotel — report the binding constraint
        reply = evaluation["reply"] + " " + t(
            "Không tìm được khách sạn rẻ hơn: {error}", language, error=replan_error
        )
        task_results = list(state.get("task_results") or [])
        task_results.append(
            {"worker": _WORKER_NAME, "status": "binding_constraint", "reply": reply}
        )
        return {"task_results": task_results}

    # --- Rebuild unlocked itinerary days with the new hotel ------------------
    locked: frozenset[int] = _get_locked_days(new_trip_data)
    itinerary: dict[str, Any] = {}
    try:
        itinerary = _itinerary_record(new_trip_data)
    except ValueError:
        pass
    duration = int(itinerary.get("duration_days") or 0)
    days_to_rebuild = [d for d in range(1, duration + 1) if d not in locked]

    if days_to_rebuild:
        try:

            day_themes = itinerary.get("day_themes") or []
            theme_by_day = {
                int(th.get("day_number") or 0): th
                for th in day_themes
                if th.get("day_number")
            }
            for day_number in days_to_rebuild:
                theme = theme_by_day.get(
                    day_number,
                    {"day_number": day_number, "title": t("Ngày {day}", language, day=day_number), "query": ""},
                )
                rebuild_day_data(new_trip_data, day_number, theme, locked_days=locked)
        except Exception as exc:
            logger.warning("budget_check: itinerary rebuild failed: %s", exc)
            # Continue — we still have the new hotel; partial rebuild is
            # better than the original over-budget plan

    # --- Recompute trip total with the new hotel + items --------------------
    re_evaluation = _check_trip_total(new_trip_data, trip_total, language)
    re_status = re_evaluation["status"]

    task_results = list(state.get("task_results") or [])

    if re_status in ("ok", "unknown_coverage"):
        # Re-plan succeeded
        new_hotel_name = (new_trip_data.get("hotel") or {}).get("name", "")
        prefix = (
            t("Đã điều chỉnh sang khách sạn {hotel} để phù hợp ngân sách. ", language, hotel=new_hotel_name)
            if new_hotel_name
            else t("Đã điều chỉnh khách sạn để phù hợp ngân sách. ", language)
        )
        task_results.append(
            {
                "worker": _WORKER_NAME,
                "status": re_status,
                "reply": prefix + re_evaluation["reply"],
            }
        )
        return {"task_results": task_results, "trip_data": new_trip_data}

    # Still over budget after re-plan — report with dominant cost named
    dominant = _dominant_cost_name(
        re_evaluation.get("hotel_total"),
        re_evaluation.get("activity_total") or 0.0,
        language,
    )
    known_total = re_evaluation.get("known_total") or 0.0
    shortfall = known_total - trip_total
    reply = t(
        "Sau khi tìm khách sạn rẻ hơn, tổng chi phí vẫn là {known:,.0f} VND "
        "(ngân sách {total:,.0f} VND, vượt {shortfall:,.0f} VND). "
        "Phần chiếm nhiều nhất là {dominant}.",
        language,
        known=known_total,
        total=trip_total,
        shortfall=shortfall,
        dominant=dominant,
    )
    task_results.append(
        {
            "worker": _WORKER_NAME,
            "status": "still_over_budget",
            "reply": reply,
        }
    )
    # Return the re-planned trip_data even if still over budget —
    # it is the closest available plan; the reply tells the user the truth.
    return {"task_results": task_results, "trip_data": new_trip_data}
