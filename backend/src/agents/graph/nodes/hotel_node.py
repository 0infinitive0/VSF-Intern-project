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
from src.api.streaming import emit_phase
from src.domain.travel_state import Presence, TravelState, apply_patch
from src.i18n import t
from src.services import session_store
from src.services.amenity_catalog import all_approved_amenities, resolve_hotel_amenity_ids
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


def _amenity_catalog_labels() -> dict[str, str]:
    return {entry.id: entry.label for entry in all_approved_amenities()}


def _amenity_label(tag: str, catalog: dict[str, str]) -> str:
    return catalog.get(tag, tag)


def _amenity_labels(tags: list[str], catalog: dict[str, str]) -> str:
    return ", ".join(_amenity_label(tag, catalog) for tag in tags)


def _binding_constraint_reply(exc: NoHotelsMatchAmenities, language: str) -> str:
    if not exc.tag_drop_counts:
        return t("Không có khách sạn nào đáp ứng đủ các tiện ích bạn yêu cầu.", language)
    catalog = _amenity_catalog_labels()
    best_tag, best_count = max(exc.tag_drop_counts.items(), key=lambda item: item[1])
    tags_text = _amenity_labels(list(exc.tag_drop_counts.keys()), catalog)
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
        tag=_amenity_label(best_tag, catalog),
        count=best_count,
    )


def _rating_reply(exc: NoHotelsMatchRating, language: str) -> str:
    parts = []
    if exc.min_star_rating is not None:
        parts.append(t("từ {n} sao trở lên", language, n=exc.min_star_rating))
    if exc.min_review_score is not None:
        parts.append(t("điểm đánh giá từ {n}/10 trở lên", language, n=exc.min_review_score))
    return t("Không có khách sạn nào đạt {criteria}.", language, criteria=" và ".join(parts))


def _capacity_reply(min_guests: int, language: str) -> str:
    return t(
        "Không có khách sạn nào (kể cả ghép nhiều phòng) đủ chỗ cho {n} người.",
        language,
        n=min_guests,
    )


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

    # Absolute lock, checked before anything else in this node (including
    # `destination_slot` below): once this session's booking is CONFIRMED
    # (paid), searching or re-selecting a hotel here must never touch
    # `trip_data` again — that would rebuild the itinerary around a
    # different hotel and destroy the one the guest already paid for. This
    # is the single point every path that can reach hotel_node funnels
    # through — POST /hotels/select (selected_hotel_id set), POST
    # /hotels/change (Command(goto="hotel_node", ...), bypassing the whole
    # intake pipeline), and organic chat text ("tôi muốn đổi khách sạn",
    # routed here by the supervisor's LLM classification) — so guarding
    # only the REST routes would miss the third one entirely.
    session_id = state.get("session_id") or ""
    if session_id and session_store.session_has_paid_booking(session_id):
        reply = t(
            "Đoạn chat này đã thanh toán xong nên mình không thể đổi hoặc tìm khách sạn khác nữa — "
            "việc đó sẽ làm mất lịch trình đã đặt. Nếu muốn lên kế hoạch cho chuyến đi khác, "
            "bạn hãy mở một đoạn chat mới nhé.",
            language,
        )
        task_results = [*(state.get("task_results") or []), {"worker": _WORKER_NAME, "status": "already_paid", "reply": reply}]
        return {"pending_tasks": pending, "task_results": task_results, "selected_hotel_id": None}

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
    people_count = int(people_slot.value) if people_slot.presence is Presence.SET else None
    people = str(people_count) if people_count is not None else ""
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
    amenity_binding = resolve_hotel_amenity_ids(requested_amenities)
    required_amenities = list(amenity_binding.ids)
    # Surfaced rather than silently dropped (review finding): a term that
    # didn't resolve to a known amenity is a request the search never even
    # tried to honor -- the user deserves to know, not just get an
    # unexplained partial (or empty) result. `.unresolved` already carries
    # exactly the user's own words, never an internal ID.
    unresolved_amenities = list(amenity_binding.unresolved)
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
        if unresolved_amenities:
            reply = reply + " " + t(
                "Mình chưa hỗ trợ lọc theo: {items}.",
                language,
                items=", ".join(unresolved_amenities),
            )
        entry: dict[str, Any] = {"worker": _WORKER_NAME, "status": status, "reply": reply}
        if hotel_search_result is not None:
            entry["hotel_search_result"] = hotel_search_result
        # The one place every exit path passes through, which is why the phase
        # frame is emitted here rather than at each `return`.
        #
        # `hotel_node` is deliberately absent from `PHASE_KEY_BY_NODE` so this is
        # the only `hotel_search` frame for the turn. That module explains the
        # rule: the frontend keys progress rows by `${key}-${at}`, so a node
        # mapped there AND emitting from inside shows the user the same step
        # twice. `itinerary_node` is absent for exactly this reason.
        #
        # `found` (candidates before the display trim) is not reachable from
        # here, so it is not reported rather than being recomputed for a
        # progress line. `destination` and the amenities are the user's own
        # inputs; no internal id is published.
        # `outcome`, not `status`: a phase frame's `status` names the step's edge
        # (started / completed) for every key, and this one describes what the
        # search found. Two meanings on one field name would collide.
        facts: dict[str, Any] = {"outcome": status}
        if destination:
            facts["destination"] = destination
        if max_radius_km is not None:
            facts["radius_km"] = max_radius_km
        if required_amenities:
            facts["amenities"] = list(required_amenities)
        if hotel_search_result is not None:
            options_shown = hotel_search_result.get("options")
            if isinstance(options_shown, list):
                facts["kept"] = len(options_shown)
        emit_phase("hotel_search", **facts)

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
            "min_guests": people_count,
        }
        if previous_ids:
            selection_kwargs["exclude_hotel_ids"] = previous_ids
        try:
            options = select_hotel_candidates(
                destination,
                destination_id,
                people,
                **selection_kwargs,
            )
        except (NoHotelsMatchAmenities, NoHotelsMatchRating):
            # `exclude_hotel_ids` is an APPEND optimization -- it exists so a
            # follow-up search adds unseen hotels instead of re-listing the
            # ones already on screen. It must never be able to decide that a
            # constraint is unsatisfiable, because the hotels it hid are
            # exactly the ones that satisfied it.
            #
            # Reported as an unstable search: Nha Trang 1-4/7 with a
            # breakfast filter returned one hotel, and the same search minutes
            # later returned "không có khách sạn nào ... Bao gồm bữa sáng".
            # Liberty Central was the destination's only breakfast hotel, so
            # once it had been shown, excluding it emptied the candidate set
            # and the binding-constraint diagnostic -- computed over that
            # emptied set -- stated something false about the whole city.
            # Deterministic, not flaky: it happens whenever the hotels
            # matching a hard filter are all already on screen.
            if not previous_ids:
                raise
            selection_kwargs.pop("exclude_hotel_ids", None)
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
        # Same diagnostic-retry idea as the dateless probe below, checked first
        # since it's the more specific, user-stated constraint: re-run without
        # `min_guests` to tell "no hotel here can seat this many people, even
        # split across rooms" apart from a generic "nothing matched at all".
        if people_count:
            capacity_probe_kwargs = {**selection_kwargs, "min_guests": None}
            capacity_probe_kwargs.pop("exclude_hotel_ids", None)
            try:
                capacity_probe_options = select_hotel_candidates(
                    destination, destination_id, people, **capacity_probe_kwargs
                )
            except Exception:
                capacity_probe_options = []
            if capacity_probe_options:
                return _result("no_results_capacity", _capacity_reply(people_count, language))
        # A generic "no hotel found" reads as "there are no hotels here at
        # all" -- when the real cause is the date range, that's misleading
        # and unactionable. Re-run the exact same filters minus the dates to
        # isolate the cause: if hotels exist without the date constraint,
        # the dates are the reason, not the destination.
        if start_date or end_date:
            dateless_kwargs = {**selection_kwargs, "start_date": None, "end_date": None}
            dateless_kwargs.pop("exclude_hotel_ids", None)
            try:
                dateless_options = select_hotel_candidates(destination, destination_id, people, **dateless_kwargs)
            except Exception:
                dateless_options = []
            if dateless_options:
                return _result(
                    "no_results_dates",
                    t(
                        "Có khách sạn tại {dest}, nhưng không còn phòng trống cho khoảng ngày bạn chọn. "
                        "Hãy thử một khoảng ngày khác.",
                        language,
                        dest=destination,
                    ),
                )
        return _result("no_results", t("Không tìm thấy khách sạn phù hợp tại {dest}.", language, dest=destination))

    ranked = rank_hotel_candidates(options, target_price=target_price)
    amenity_catalog = _amenity_catalog_labels()
    active_preferences = [
        {"id": tag, "label": _amenity_label(tag, amenity_catalog)} for tag in required_amenities
    ]
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
