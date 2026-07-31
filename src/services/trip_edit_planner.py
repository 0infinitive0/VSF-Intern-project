"""Stateless LLM planning and validation for saved-trip edits.

The model is deliberately limited to describing an edit.  It never selects a
database record or modifies an itinerary; those responsibilities stay in the
deterministic planner layer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from src.services.llm import get_llm
from src.services.trip_scheduler import parse_day_scope

EditDecision = Literal["apply", "clarify", "not_edit"]
EditOperationName = Literal[
    "replace_item",
    "remove_item",
    "update_time",
    "add_item",
    "set_schedule_policy",
    "set_meal_preference",
    "change_hotel",
    "replan_day",
]
ItemKind = Literal["breakfast", "attraction", "lunch", "rest", "coffee", "dinner", "evening"]

_OPERATIONS = frozenset(
    {
        "replace_item",
        "remove_item",
        "update_time",
        "add_item",
        "set_schedule_policy",
        "set_meal_preference",
        "change_hotel",
        "replan_day",
    }
)
_TARGETED_OPERATIONS = frozenset({"replace_item", "remove_item", "update_time"})
_ITEM_KINDS = frozenset({"breakfast", "attraction", "lunch", "rest", "coffee", "dinner", "evening"})
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")


class TripEditPlanError(ValueError):
    """The LLM result cannot safely be used to change a trip."""


@dataclass(frozen=True)
class ItemTarget:
    item_id: str | None = None
    day_number: int | None = None
    item_kind: ItemKind | None = None
    reference_id: str | None = None
    name_hint: str | None = None


@dataclass(frozen=True)
class NewItemRequirements:
    item_kind: ItemKind
    semantic_query: str
    included_categories: tuple[str, ...] = ()
    excluded_categories: tuple[str, ...] = ()
    near: Literal["hotel", "day_anchor", "target", "previous_item", "next_item"] = "day_anchor"
    preferred_start_time: str | None = None
    preferred_end_time: str | None = None
    duration_minutes: int | None = None
    preserve_start_time: bool = False
    preserve_duration: bool = False
    real_place_required: bool = True


@dataclass(frozen=True)
class EditOperation:
    operation: EditOperationName
    target: ItemTarget | None = None
    requirements: NewItemRequirements | None = None
    day_number: int | None = None
    day_numbers: tuple[int, ...] = ()
    gap_policy: Literal["leave_blank", "close_gap", "replace"] | None = None
    start_time: str | None = None
    end_time: str | None = None
    shift_minutes: int | None = None
    cascade_policy: Literal["repair_day", "shift_following", "preserve_following"] = "repair_day"
    meal_kind: Literal["breakfast", "lunch", "dinner"] | None = None
    meal_preference: Literal["self_selected", "automatic"] | None = None
    latest_start_time: str | None = None
    latest_end_time: str | None = None
    theme: dict[str, Any] | None = None
    hotel_query: str | None = None
    placement: dict[str, Any] | None = None


@dataclass(frozen=True)
class TripEditPlan:
    decision: EditDecision
    summary: str
    operations: tuple[EditOperation, ...] = ()
    confidence: float | None = None
    clarification_question: str | None = None
    raw_request: str = ""


def build_trip_edit_context(
    trip_data: dict[str, Any],
    modification_request: str = "",
) -> dict[str, Any]:
    """Return the compact, authoritative plan snapshot shown to the model."""
    itineraries = trip_data.get("itineraries") or [{}]
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    hotel = trip_data.get("hotel") or {}
    requested_days = parse_day_scope(modification_request, _duration_days(trip_data))
    items = []
    for item in trip_data.get("itinerary_items") or []:
        if requested_days and int(item.get("day_number") or 0) not in requested_days:
            continue
        items.append(
            {
                "item_id": str(item.get("id") or ""),
                "day_number": item.get("day_number"),
                "order_index": item.get("order_index"),
                "item_kind": item.get("item_kind") or item.get("kind"),
                "reference_id": item.get("reference_id"),
                "activity": item.get("activity"),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
            }
        )
    return {
        "itinerary": {
            "id": itinerary.get("id"),
            "duration_days": itinerary.get("duration_days"),
            "day_themes": itinerary.get("day_themes") or [],
            "planning_constraints": itinerary.get("planning_constraints") or {},
        },
        "hotel": {
            "id": hotel.get("id"),
            "name": hotel.get("name"),
            "destination_id": hotel.get("destination_id"),
            "coordinates": hotel.get("coordinates"),
            "covered_meals": hotel.get("covered_meals") or [],
        },
        "items": items,
    }


def _strip_json_fence(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_time(value: object, field_name: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip()
    if not _TIME_PATTERN.fullmatch(normalized):
        raise TripEditPlanError(f"{field_name} must use HH:MM or HH:MM:SS")
    return normalized if len(normalized) == 8 else f"{normalized}:00"


def _duration_days(trip_data: dict[str, Any]) -> int:
    itineraries = trip_data.get("itineraries") or [{}]
    itinerary = itineraries[0] if isinstance(itineraries, list) else itineraries
    try:
        return max(1, int(itinerary.get("duration_days") or 1))
    except (TypeError, ValueError):
        return 1


def _parse_days(value: object, duration_days: int) -> tuple[int, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, list) else [value]
    parsed = []
    for raw in values:
        try:
            day = int(raw)
        except (TypeError, ValueError) as exc:
            raise TripEditPlanError("day_number must be an integer") from exc
        if not 1 <= day <= duration_days:
            raise TripEditPlanError("day_number is outside this itinerary")
        if day not in parsed:
            parsed.append(day)
    return tuple(parsed)


def _parse_target(value: object, trip_data: dict[str, Any]) -> ItemTarget:
    if not isinstance(value, dict):
        raise TripEditPlanError("target is required")
    item_id = str(value.get("item_id") or "").strip() or None
    duration_days = _duration_days(trip_data)
    day_number = _parse_days(value.get("day_number"), duration_days)
    item_kind_value = value.get("item_kind")
    if item_kind_value is not None and str(item_kind_value) not in _ITEM_KINDS:
        raise TripEditPlanError("target.item_kind is invalid")
    target = ItemTarget(
        item_id=item_id,
        day_number=day_number[0] if day_number else None,
        item_kind=str(item_kind_value) if item_kind_value is not None else None,
        reference_id=str(value.get("reference_id") or "").strip() or None,
        name_hint=str(value.get("name_hint") or "").strip() or None,
    )
    items = trip_data.get("itinerary_items") or []
    if target.item_id:
        item = next((row for row in items if str(row.get("id")) == target.item_id), None)
        if item is None:
            raise TripEditPlanError("target.item_id is not present in the current itinerary")
        if target.day_number is not None and int(item.get("day_number") or 0) != target.day_number:
            raise TripEditPlanError("target day_number does not match target.item_id")
        item_kind = str(item.get("item_kind") or item.get("kind") or "")
        if target.item_kind is not None and item_kind != target.item_kind:
            raise TripEditPlanError("target item_kind does not match target.item_id")
        if target.reference_id and str(item.get("reference_id") or "") != target.reference_id:
            raise TripEditPlanError("target reference_id does not match target.item_id")
        return ItemTarget(
            item_id=target.item_id,
            day_number=int(item.get("day_number") or 0),
            item_kind=item_kind if item_kind in _ITEM_KINDS else None,
            reference_id=str(item.get("reference_id") or "") or None,
            name_hint=target.name_hint,
        )

    matches = [
        row
        for row in items
        if (target.day_number is None or int(row.get("day_number") or 0) == target.day_number)
        and (target.item_kind is None or str(row.get("item_kind") or row.get("kind") or "") == target.item_kind)
        and (target.reference_id is None or str(row.get("reference_id") or "") == target.reference_id)
    ]
    if target.name_hint:
        hint = target.name_hint.casefold()
        matches = [row for row in matches if hint in str(row.get("activity") or "").casefold()]
    if len(matches) != 1:
        raise TripEditPlanError("target must identify exactly one current itinerary item")
    row = matches[0]
    kind = str(row.get("item_kind") or row.get("kind") or "")
    return ItemTarget(
        item_id=str(row.get("id") or ""),
        day_number=int(row.get("day_number") or 0),
        item_kind=kind if kind in _ITEM_KINDS else None,
        reference_id=str(row.get("reference_id") or "") or None,
        name_hint=target.name_hint,
    )


def _parse_requirements(value: object) -> NewItemRequirements | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TripEditPlanError("requirements must be an object")
    item_kind = str(value.get("item_kind") or "")
    if item_kind not in _ITEM_KINDS:
        raise TripEditPlanError("requirements.item_kind is invalid")
    query = str(value.get("semantic_query") or "").strip()
    if not query:
        raise TripEditPlanError("requirements.semantic_query is required")
    near = str(value.get("near") or "day_anchor")
    if near not in {"hotel", "day_anchor", "target", "previous_item", "next_item"}:
        raise TripEditPlanError("requirements.near is invalid")
    duration = value.get("duration_minutes")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError) as exc:
            raise TripEditPlanError("requirements.duration_minutes is invalid") from exc
        if duration <= 0:
            raise TripEditPlanError("requirements.duration_minutes must be positive")
    return NewItemRequirements(
        item_kind=item_kind,
        semantic_query=query,
        included_categories=_string_list(value.get("included_categories") or value.get("preferred_categories")),
        excluded_categories=_string_list(value.get("excluded_categories") or value.get("avoid_categories")),
        near=near,
        preferred_start_time=_parse_time(value.get("preferred_start_time"), "requirements.preferred_start_time"),
        preferred_end_time=_parse_time(value.get("preferred_end_time"), "requirements.preferred_end_time"),
        duration_minutes=duration,
        preserve_start_time=bool(value.get("preserve_start_time")),
        preserve_duration=bool(value.get("preserve_duration")),
        real_place_required=value.get("real_place_required") is not False,
    )


def _parse_operation(value: object, trip_data: dict[str, Any]) -> EditOperation:
    if not isinstance(value, dict):
        raise TripEditPlanError("each operation must be an object")
    operation = str(value.get("operation") or "")
    if operation not in _OPERATIONS:
        raise TripEditPlanError("operation is invalid")
    target_value = value.get("target")
    if operation in _TARGETED_OPERATIONS and target_value is None and value.get("item_id"):
        # The configured local model sometimes flattens a single-field target.
        # It remains safe because _parse_target still validates the ID against
        # the authoritative itinerary snapshot.
        target_value = {
            "item_id": value.get("item_id"),
            "day_number": value.get("day_number"),
            "item_kind": value.get("item_kind"),
            "reference_id": value.get("reference_id"),
            "name_hint": value.get("name_hint"),
        }
    target = _parse_target(target_value, trip_data) if operation in _TARGETED_OPERATIONS else None
    requirements_source = value.get("requirements") or value.get("replacement_requirements") or value.get("new_item_requirements")
    requirements = _parse_requirements(requirements_source) if operation in {"replace_item", "add_item"} else None
    if operation in {"replace_item", "add_item"} and requirements is None:
        raise TripEditPlanError(f"{operation} requires requirements")
    if operation == "replace_item" and target and requirements and target.item_kind != requirements.item_kind:
        raise TripEditPlanError("replacement item_kind must match the target item kind")
    duration_days = _duration_days(trip_data)
    days = _parse_days(value.get("day_numbers"), duration_days)
    day_values = _parse_days(value.get("day_number"), duration_days)
    day_number = day_values[0] if day_values else (target.day_number if target else None)
    if operation in {"add_item", "replan_day"} and day_number is None:
        raise TripEditPlanError(f"{operation} requires day_number")
    gap_policy = value.get("gap_policy")
    if operation == "remove_item":
        gap_policy = str(gap_policy or "leave_blank")
        if gap_policy not in {"leave_blank", "close_gap", "replace"}:
            raise TripEditPlanError("remove_item.gap_policy is invalid")
        if gap_policy == "replace" and requirements is None:
            requirements = _parse_requirements(requirements_source)
        if gap_policy == "replace" and requirements is None:
            raise TripEditPlanError("remove_item replace policy requires requirements")
    elif gap_policy is not None:
        raise TripEditPlanError("gap_policy is only valid for remove_item")
    cascade = str(value.get("cascade_policy") or "repair_day")
    if cascade not in {"repair_day", "shift_following", "preserve_following"}:
        raise TripEditPlanError("cascade_policy is invalid")
    meal_kind = value.get("meal_kind")
    if meal_kind is not None and str(meal_kind) not in {"breakfast", "lunch", "dinner"}:
        raise TripEditPlanError("meal_kind is invalid")
    preference = value.get("meal_preference") or value.get("preference")
    if preference is not None and str(preference) not in {"self_selected", "automatic"}:
        raise TripEditPlanError("meal_preference is invalid")
    if operation == "set_meal_preference" and (meal_kind is None or preference is None):
        raise TripEditPlanError("set_meal_preference requires meal_kind and meal_preference")
    if operation == "replan_day" and not isinstance(value.get("theme"), dict):
        raise TripEditPlanError("replan_day requires theme")
    return EditOperation(
        operation=operation,
        target=target,
        requirements=requirements,
        day_number=day_number,
        day_numbers=days,
        gap_policy=gap_policy,
        start_time=_parse_time(value.get("start_time"), "start_time"),
        end_time=_parse_time(value.get("end_time"), "end_time"),
        shift_minutes=int(value["shift_minutes"]) if value.get("shift_minutes") is not None else None,
        cascade_policy=cascade,
        meal_kind=str(meal_kind) if meal_kind is not None else None,
        meal_preference=str(preference) if preference is not None else None,
        latest_start_time=_parse_time(value.get("latest_start_time"), "latest_start_time"),
        latest_end_time=_parse_time(value.get("latest_end_time"), "latest_end_time"),
        theme=dict(value["theme"]) if isinstance(value.get("theme"), dict) else None,
        hotel_query=str(value.get("hotel_query") or "").strip() or None,
        placement=dict(value["placement"]) if isinstance(value.get("placement"), dict) else None,
    )


def parse_trip_edit_plan(payload: object, trip_data: dict[str, Any], *, raw_request: str = "") -> TripEditPlan:
    """Validate a model response at the external boundary before execution."""
    if not isinstance(payload, dict):
        raise TripEditPlanError("edit planner response must be a JSON object")
    decision = str(payload.get("decision") or "")
    if decision not in {"apply", "clarify", "not_edit"}:
        raise TripEditPlanError("decision is invalid")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise TripEditPlanError("summary is required")
    confidence_value = payload.get("confidence")
    confidence = None
    if confidence_value is not None:
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError) as exc:
            raise TripEditPlanError("confidence is invalid") from exc
        if not 0 <= confidence <= 1:
            raise TripEditPlanError("confidence must be between 0 and 1")
    operations = tuple(_parse_operation(item, trip_data) for item in payload.get("operations") or [])
    question = str(payload.get("clarification_question") or "").strip() or None
    if decision == "apply" and not operations:
        raise TripEditPlanError("apply requires at least one operation")
    if decision == "clarify" and not question:
        raise TripEditPlanError("clarify requires clarification_question")
    if decision != "apply" and operations:
        raise TripEditPlanError("only apply may include operations")
    if any(operation.operation == "change_hotel" for operation in operations) and len(operations) != 1:
        raise TripEditPlanError("change_hotel must be the only operation")
    return TripEditPlan(
        decision=decision,
        summary=summary,
        operations=operations,
        confidence=confidence,
        clarification_question=question,
        raw_request=raw_request,
    )


def _planner_prompt(modification_request: str, trip_data: dict[str, Any], repair_message: str | None = None) -> str:
    context = json.dumps(
        build_trip_edit_context(trip_data, modification_request),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    repair = f"\nPrevious response was rejected: {repair_message}. Return corrected JSON only." if repair_message else ""
    return f"""You are a Vietnamese travel itinerary edit planner. Return one raw JSON object, no Markdown.
The user request is: {modification_request}
Current authoritative itinerary context: {context}

Return this schema:
{{"decision":"apply|clarify|not_edit","summary":"Vietnamese summary","confidence":0.0,"clarification_question":null,"operations":[]}}

Operations are replace_item, remove_item, update_time, add_item, set_schedule_policy, set_meal_preference, change_hotel, replan_day.
For a targeted operation, use exactly {{"target":{{"item_id":"one context.items item_id"}}}}. Never invent an item_id, venue UUID, venue name, hours, coordinates, or availability.
replace_item/add_item requirements must contain item_kind and semantic_query; express desired categories, location, time and duration as requirements only.
remove_item gap_policy is leave_blank, close_gap, or replace. A bare removal is leave_blank.
For time changes use start_time, end_time, or shift_minutes and cascade_policy.
For time limits like 'after Xh do not go out' or 'do nothing after Xh' (e.g. không làm gì sau Xh), you MUST use set_schedule_policy. Example: {{"operation": "set_schedule_policy", "latest_end_time": "18:00"}}. NEVER use remove_item because it only removes one item.
For ANY requests to change the theme/focus of an entire day (e.g. "ngày đầu đi thưởng thức ẩm thực", "hôm sau đi mua sắm"), ALWAYS use replan_day. Example: {{"operation": "replan_day", "day_number": 1, "theme": {{"selection_mode":"user_specified", "title":"...", "semantic_query":"..."}}}}.
For adding a new item, use add_item. Example: {{"operation": "add_item", "day_number": 1, "requirements": {{"item_kind": "attraction", "semantic_query": "địa điểm vui chơi"}}, "latest_start_time": "20:00"}}.
For replacing an item, use replace_item. Example: {{"operation": "replace_item", "target": {{"item_id": "1"}}, "requirements": {{"item_kind": "lunch", "semantic_query": "quán ăn trưa"}}}}.
If the user wants to handle a meal/activity themselves (e.g. "tự ăn sáng", "tự túc ăn trưa"), ALWAYS use remove_item to delete it. Do NOT use replace_item.
The semantic_query for a day theme must describe multiple attractions or experiences; do not use a single meal such as breakfast as the whole-day query.
Use clarify only when the target or requested result is materially ambiguous. Use not_edit for ordinary questions that do not change this itinerary.{repair}"""


def plan_trip_edit(
    modification_request: str,
    trip_data: dict[str, Any],
    *,
    llm: Any | None = None,
) -> TripEditPlan:
    """Ask the configured model once, retrying exactly once for invalid output."""
    model = llm or get_llm(temperature=0.0)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = model.invoke(_planner_prompt(modification_request, trip_data, str(last_error) if attempt else None))
            payload = json.loads(_strip_json_fence(getattr(response, "content", response)))
            return parse_trip_edit_plan(payload, trip_data, raw_request=modification_request)
        except (json.JSONDecodeError, TripEditPlanError, TypeError, ValueError) as exc:
            last_error = exc
        except Exception as exc:  # provider failures must never trigger an edit fallback
            last_error = TripEditPlanError(f"LLM edit planner unavailable: {exc}")
    raise TripEditPlanError(f"Could not safely understand this edit request: {last_error}")
