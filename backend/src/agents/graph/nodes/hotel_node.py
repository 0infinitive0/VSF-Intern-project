"""`hotel_node` — hard filters, radius, center (Phase 8,
phase-08-hotel-flow.md).

Runs after `apply_patch`, so `state["travel_state"]` already holds this
turn's committed facts. Reads `hotel_preferences.*` (amenities, radius_km,
center, min_star_rating, min_review_score) and calls
`select_hotel_candidates` with them as HARD, app-level filters — never the
soft ranking bonus `rank_hotel_candidates` still applies for anything not
requested as a hard filter.

Center resolution (`services/search_center.py`) can call `interrupt()`
exactly once per invocation, when a radius search's center is neither a
named, geocodable landmark nor (not yet reachable — see that module's
docstring) an already-selected hotel. This makes `hotel_node` the SECOND
node in this plane allowed to call `interrupt()` (`validate_patch` was
previously the only one — see `test_graph_v2_skeleton.py`). It does not
share validate_patch's zero-I/O purity bar: LangGraph re-runs a node from
its start on every resume, so the standing requirement is that everything
before the `interrupt()` call stays PURE-OR-IDEMPOTENT, not literally I/O-
free. `_resolve_center`'s only I/O before a possible `interrupt()` is a
read-only `attractions` lookup (`find_attraction_by_name`), safe to repeat
verbatim on replay.

A resume reply that still doesn't resolve the center (e.g. it answers a
completely different intent, "đổi ngân sách xuống 2 triệu") is handled the
same way `validate_patch` handles an unresolved date reply: this node sets
`unresolved_resume_text` and returns without running the search.
`_run_turn_via_graph` (api/routes.py) already re-runs that text as an
ordinary fresh turn — generic to any node, not `validate_patch`-specific —
so the discarded response here is never shown to the user.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from langgraph.types import interrupt

from src.agents.graph.state import TravelGraphState
from src.domain.travel_state import Presence, TravelState, apply_patch
from src.i18n import t
from src.services.amenity_catalog import resolve_hotel_amenity_ids
from src.services.hotel_selection import (
    NoHotelsMatchAmenities,
    NoHotelsMatchRating,
    fetch_hotel_by_id,
    rank_hotel_candidates,
    select_hotel_candidates,
)
from src.services.search_center import CenterResolution, extract_named_place, resolve_center
from src.services.trip_planner import _get_destination_id, build_selected_hotel_trip
from src.services.trip_scheduler import parse_coordinates

logger = logging.getLogger(__name__)

_WORKER_NAME = "hotel_node"
_HOTEL_OPTION_LIMIT = 10
_HOTEL_DISPLAY_LIMIT = 5


def _last_human_message(state: TravelGraphState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) == "human":
            return str(getattr(message, "content", "") or "")
    return ""


def _center_ask_payload(radius_km: float, language: str) -> dict[str, Any]:
    message = t(
        "Bạn muốn tìm khách sạn trong bán kính {radius}km tính từ đâu? Cho mình biết một địa điểm/địa danh cụ thể nhé.",
        language,
        radius=radius_km,
    )
    return {"kind": "hotel_radius_center", "radius_km": radius_km, "message": message}


def _resolve_center(
    *, destination_id: str, radius_km: float, center_slot_value: str | None, language: str, last_message: str
) -> tuple[tuple[float, float] | None, str | None]:
    """Returns `(coordinates, unresolved_resume_text)`. Exactly one of the
    two is non-None on return, except both are None when nothing about
    this turn asked for a center at all (never actually returned — callers
    only invoke this when `radius_km` is set)."""
    if center_slot_value:
        coordinates = parse_coordinates(center_slot_value)
        if coordinates is not None:
            return coordinates, None

    named_place = extract_named_place(last_message)
    resolution = resolve_center(
        destination_id=destination_id, named_place=named_place, selected_hotel_coordinates=None
    )
    if resolution.resolved:
        return (resolution.latitude, resolution.longitude), None  # type: ignore[return-value]

    resume_text = str(interrupt(_center_ask_payload(radius_km, language)) or "")
    retry_place = extract_named_place(resume_text) or (resume_text.strip() or None)
    retry_resolution: CenterResolution = (
        resolve_center(destination_id=destination_id, named_place=retry_place, selected_hotel_coordinates=None)
        if retry_place
        else CenterResolution(latitude=None, longitude=None, source="unresolved")
    )
    if retry_resolution.resolved:
        return (retry_resolution.latitude, retry_resolution.longitude), None  # type: ignore[return-value]

    return None, resume_text


def _amenity_labels(tags: list[str]) -> str:
    return ", ".join(tags)


def _binding_constraint_reply(exc: NoHotelsMatchAmenities, language: str) -> str:
    if not exc.tag_drop_counts:
        return t("Không có khách sạn nào đáp ứng đủ các tiện ích bạn yêu cầu.", language)
    best_tag, best_count = max(exc.tag_drop_counts.items(), key=lambda item: item[1])
    tags_text = _amenity_labels(list(exc.tag_drop_counts.keys()))
    if best_count <= 0:
        return t(
            "Không có khách sạn nào có đủ các tiện ích: {tags} — kể cả khi bỏ bớt từng tiện ích một.",
            language,
            tags=tags_text,
        )
    return t(
        "Không có khách sạn nào vừa có đủ các tiện ích: {tags}. Nếu bỏ '{tag}' thì có {count} khách sạn phù hợp.",
        language,
        tags=tags_text,
        tag=best_tag,
        count=best_count,
    )


def _rating_reply(exc: NoHotelsMatchRating, language: str) -> str:
    parts = []
    if exc.min_star_rating is not None:
        parts.append(t("từ {n} sao trở lên", language, n=exc.min_star_rating))
    if exc.min_review_score is not None:
        parts.append(t("điểm đánh giá từ {n}/10 trở lên", language, n=exc.min_review_score))
    return t("Không có khách sạn nào đạt {criteria}.", language, criteria=" và ".join(parts))


def _handle_hotel_selection(
    *,
    hotel_id: str,
    destination: str,
    destination_id: str,
    people: str,
    start_date: str | None,
    end_date: str | None,
    current_trip_data: dict[str, Any],
    session_id: str,
    language: str,
) -> tuple[dict[str, Any] | None, str]:
    """Fetch the picked hotel and build/replace `trip_data` from it (review
    finding F2). Returns `(None, error_reply)` on any failure -- never
    raises, mirroring every other error path in this node."""
    resolved = fetch_hotel_by_id(hotel_id, destination_id)
    if resolved is None:
        return None, t("Không tìm thấy khách sạn với id đã cho tại điểm đến này.", language)
    hotel_data, _candidate = resolved

    if not start_date or not end_date:
        return None, t("Mình cần biết ngày đi và ngày về trước khi chọn khách sạn.", language)
    duration_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days
    if duration_days <= 0:
        return None, t("Khoảng ngày lưu trú không hợp lệ.", language)

    has_existing_trip = bool(current_trip_data)
    selection_pending = {
        "mode": "change_hotel" if has_existing_trip else "new_trip",
        "destination": destination,
        "duration": str(duration_days),
        "people": people,
        "preferences_text": "",
        "start_date": start_date,
        "end_date": end_date,
        "planning_constraints": {},
    }
    try:
        generated = build_selected_hotel_trip(
            selection_pending,
            hotel_data,
            current_trip_data=current_trip_data if has_existing_trip else None,
            session_id=session_id,
            language=language,
        )
    except Exception as exc:
        logger.exception("hotel_node: hotel selection failed")
        return None, t("Chọn khách sạn thất bại: {error}", language, error=str(exc))

    return generated.trip_data, generated.reply


def hotel_node(state: TravelGraphState) -> dict[str, Any]:
    pending = [worker for worker in (state.get("pending_tasks") or []) if worker != _WORKER_NAME]
    language = state.get("language") or "vi"
    travel_state = TravelState.from_dict(state.get("travel_state"))
    selected_hotel_id = state.get("selected_hotel_id")

    destination_slot = travel_state.get("destination")
    if destination_slot.presence is not Presence.SET:
        # ask_slot gates destination before the supervisor ever delegates
        # here — this is a defensive fallback, not an expected path.
        reply = t("Mình cần biết bạn muốn đi đâu trước khi tìm khách sạn.", language)
        task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": "no_destination", "reply": reply}]
        return {"pending_tasks": pending, "task_results": task_results, "selected_hotel_id": None}

    destination = str(destination_slot.value)
    destination_id = _get_destination_id(destination)
    if not destination_id:
        reply = t("Không tìm thấy dữ liệu điểm đến cho {dest}.", language, dest=destination)
        task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": "unknown_destination", "reply": reply}]
        return {"pending_tasks": pending, "task_results": task_results, "selected_hotel_id": None}

    people_slot = travel_state.get("people")
    people = str(int(people_slot.value)) if people_slot.presence is Presence.SET else ""
    start_slot = travel_state.get("dates.start")
    end_slot = travel_state.get("dates.end")
    start_date = str(start_slot.value) if start_slot.presence is Presence.SET else None
    end_date = str(end_slot.value) if end_slot.presence is Presence.SET else None

    if selected_hotel_id:
        trip_data, reply = _handle_hotel_selection(
            hotel_id=selected_hotel_id,
            destination=destination,
            destination_id=destination_id,
            people=people,
            start_date=start_date,
            end_date=end_date,
            current_trip_data=state.get("trip_data") or {},
            session_id=state.get("session_id") or "",
            language=language,
        )
        status = "hotel_selected" if trip_data is not None else "hotel_selection_failed"
        task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": status, "reply": reply}]
        update: dict[str, Any] = {"pending_tasks": pending, "task_results": task_results, "selected_hotel_id": None}
        if trip_data is not None:
            update["trip_data"] = trip_data
        return update

    min_price_slot = travel_state.get("budget.min")
    max_price_slot = travel_state.get("budget.max")
    min_price = float(min_price_slot.value) if min_price_slot.presence is Presence.SET else None
    max_price = float(max_price_slot.value) if max_price_slot.presence is Presence.SET else None
    target_price_slot = travel_state.get("budget.target")
    target_price = float(target_price_slot.value) if target_price_slot.presence is Presence.SET else None

    amenities_slot = travel_state.get("hotel_preferences.amenities")
    requested_amenities = (
        [str(tag) for tag in amenities_slot.value] if amenities_slot.presence is Presence.SET else []
    )
    required_amenities = list(resolve_hotel_amenity_ids(requested_amenities).ids)
    star_slot = travel_state.get("hotel_preferences.min_star_rating")
    min_star_rating = float(star_slot.value) if star_slot.presence is Presence.SET else None
    review_slot = travel_state.get("hotel_preferences.min_review_score")
    min_review_score = float(review_slot.value) if review_slot.presence is Presence.SET else None

    radius_slot = travel_state.get("hotel_preferences.radius_km")
    center_slot = travel_state.get("hotel_preferences.center")
    root_latitude: float | None = None
    root_longitude: float | None = None
    max_radius_km: float | None = None
    updated_travel_state_dict: dict[str, Any] | None = None

    if radius_slot.presence is Presence.SET:
        radius_km = float(radius_slot.value)
        coordinates, unresolved_resume_text = _resolve_center(
            destination_id=destination_id,
            radius_km=radius_km,
            center_slot_value=str(center_slot.value) if center_slot.presence is Presence.SET else None,
            language=language,
            last_message=_last_human_message(state),
        )
        if unresolved_resume_text is not None:
            task_results = [
                *(state.get("task_results") or []),
                {"worker": _WORKER_NAME, "status": "center_unresolved", "reply": ""},
            ]
            return {
                "pending_tasks": pending,
                "task_results": task_results,
                "unresolved_resume_text": unresolved_resume_text,
            }
        root_latitude, root_longitude = coordinates  # type: ignore[misc]
        max_radius_km = radius_km
        if center_slot.presence is not Presence.SET:
            patch_result = apply_patch(
                travel_state,
                [{"path": "hotel_preferences.center", "operation": "set", "value": f"{root_latitude},{root_longitude}"}],
            )
            travel_state = patch_result.state
            updated_travel_state_dict = travel_state.to_dict()

    def _result(status: str, reply: str, hotel_search_result: dict[str, Any] | None = None) -> dict[str, Any]:
        entry: dict[str, Any] = {"worker": _WORKER_NAME, "status": status, "reply": reply}
        if hotel_search_result is not None:
            entry["hotel_search_result"] = hotel_search_result
        task_results = [*(state.get("task_results") or []), entry]
        update: dict[str, Any] = {"pending_tasks": pending, "task_results": task_results}
        if updated_travel_state_dict is not None:
            update["travel_state"] = updated_travel_state_dict
        return update

    current_search_context = {
        "destination_id": destination_id,
        "start_date": start_date,
        "end_date": end_date,
        "people": people,
    }
    previous_context = state.get("previous_hotel_search_context") or {}
    previous_options = state.get("previous_hotel_options") or []
    if previous_context != current_search_context:
        previous_options = []
    previous_options = [
        option for option in previous_options if isinstance(option, dict) and option.get("id")
    ]
    previous_ids = [str(option["id"]) for option in previous_options]

    try:
        selection_kwargs: dict[str, Any] = {
            "match_count": _HOTEL_OPTION_LIMIT,
            "min_price": min_price,
            "max_price": max_price,
            "start_date": start_date,
            "end_date": end_date,
            "root_latitude": root_latitude,
            "root_longitude": root_longitude,
            "max_radius_km": max_radius_km,
            "required_amenities": required_amenities,
            "min_star_rating": min_star_rating,
            "min_review_score": min_review_score,
        }
        if previous_ids:
            selection_kwargs["exclude_hotel_ids"] = previous_ids
        options = select_hotel_candidates(
            destination,
            destination_id,
            people,
            **selection_kwargs,
        )
    except NoHotelsMatchAmenities as exc:
        return _result("no_results_amenities", _binding_constraint_reply(exc, language))
    except NoHotelsMatchRating as exc:
        return _result("no_results_rating", _rating_reply(exc, language))
    except Exception as exc:
        logger.exception("hotel_node: hotel search failed")
        return _result("error", t("Tìm khách sạn thất bại: {error}", language, error=str(exc)))

    if not options and not previous_options:
        return _result("no_results", t("Không tìm thấy khách sạn phù hợp tại {dest}.", language, dest=destination))

    ranked = rank_hotel_candidates(options, target_price=target_price)
    active_preferences = [{"id": tag, "label": tag} for tag in required_amenities]
    hotel_options = [*previous_options]
    known_ids = set(previous_ids)
    for data, _candidate in ranked[:_HOTEL_DISPLAY_LIMIT]:
        hotel_id = str(data.get("id") or "")
        if hotel_id and hotel_id not in known_ids:
            known_ids.add(hotel_id)
            hotel_options.append(data)
    reply = t("Mình tìm được {count} khách sạn phù hợp.", language, count=len(hotel_options))
    result = _result(
        "ok", reply, {"options": hotel_options, "active_preferences": active_preferences}
    )
    result["previous_hotel_options"] = hotel_options
    result["previous_hotel_search_context"] = current_search_context
    return result
