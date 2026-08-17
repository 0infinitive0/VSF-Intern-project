"""`extract_patch` — one LLM call producing `{intent, changes[]}` (doc §36
`understand_request`), replacing the three separate extraction calls the
legacy plane still runs (`_llm_extract_intake_facts`, `TripPreferenceUpdate
.from_message`, `plan_trip_edit`). `intent` never selects a WORKER —
`detect_impact` + `WORKFLOW_TO_WORKER` does that, off the validated patch
(`validate_patch`/`apply_patch`) — but it does separate read-only Q&A from
state-changing turns on one routing edge (Phase 15,
`routing.is_intake_question`); see `state.py`'s field comment.

Defensive parsing mirrors `trip_edit_planner.plan_trip_edit`'s proven shape:
strict JSON parse -> structural validate -> retry once with the rejection
reason. Unlike that function, a fallback here never raises —
`{"patch": [], "intent": "general_question"}` lets the turn complete exactly
as an empty patch always has (`validate_patch`/`apply_patch` commit nothing,
`pending_tasks` stays empty, the supervisor's existing IMPACT_MAP/LLM
fallback takes it from there).

Two things `apply_patch`'s validators do NOT enforce, so this node grounds
them itself before a change is handed off:
- `destination` against the real destinations table (`_match_known_destination`)
- the closed label sets for `preferences.themes` / `.companions` / `.pace`
  / `.day_rhythm` (`trip_intake.py`'s vocabulary, kept as the grounding
  authority per this phase's plan)

The prompt sees exactly one message, never the transcript. The only
cross-turn context it gets is the pending slot names (`_pending_slots`),
which is what makes a short reply ("Hồ Chí Minh", "1", "20/7") interpretable
without paying for unbounded history on every turn.

Day-scope resolution ("ngày 1", "hôm đầu", "ngày cuối") is deterministic,
not model-decided: `_resolve_day_scope`/`_rewrite_day_scope` force any
theme-shaped change to `daily_preferences.<day>.theme` when the message
names a day, removing the prompt collision `trip_edit_planner.py:442/445`
used to have between "day theme" and "vibe/preferences" routing.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from src.agents.graph.prompts import build_extract_patch_prompt
from src.agents.graph.state import TravelGraphState
from src.domain.slot_registry import pending_question_slots
from src.domain.travel_state import TravelState, trip_duration_days
from src.services.llm import get_reasoning_llm
from src.services.trip_intake import (
    _COMPANION_LABELS,
    _DAY_RHYTHM_LABELS,
    _PACE_LABELS,
    _PREFERENCE_LABELS,
    DestinationOption,
    _match_known_destination,
)
from src.services.trip_planner import _get_destination_names
from src.services.trip_scheduler import parse_day_scope

logger = logging.getLogger(__name__)

_INTENTS = frozenset(
    {"hotel_search", "update_itinerary", "update_trip", "select_hotel", "finalize", "general_question"}
)
_OPERATIONS = frozenset({"set", "unset", "append", "remove"})
_MAX_DAY_NUMBER_FALLBACK = 90  # mirrors travel_state.py's own pre-dates ceiling

# Theme-shaped paths eligible for the deterministic day-scope rewrite --
# everything else (budget, destination, amenities, ...) passes through
# untouched even inside a day-scoped message.
_THEME_PATH_RE = re.compile(r"^(preferences\.themes|daily_preferences\.\d+\.theme)$")

_FIRST_DAY_RE = re.compile(r"\b(?:ngay|hom)\s+dau(?:\s+tien)?\b")
_LAST_DAY_RE = re.compile(r"\b(?:ngay|hom)\s+cuoi(?:\s+cung)?\b")
_DURATION_DAYS_RE = re.compile(r"\b(?P<days>[1-9]\d?)\s*(?:ngay|day)\b")
_BREAKFAST_INCLUDED_RE = re.compile(r"\b(?:bao\s+gom|included)\s+(?:(?:an|bua)\s+sang|breakfast)\b")
_BREAKFAST_NEGATED_RE = re.compile(r"\b(?:khong|without|no)\s+(?:bao\s+gom\s+)?(?:(?:an|bua)\s+sang|breakfast)\b")

_CLOSED_LIST_PATHS: dict[str, tuple[str, ...]] = {
    "preferences.themes": _PREFERENCE_LABELS,
    "preferences.day_rhythm": _DAY_RHYTHM_LABELS,
}
_CLOSED_SCALAR_PATHS: dict[str, tuple[str, ...]] = {
    "preferences.companions": _COMPANION_LABELS,
    "preferences.pace": _PACE_LABELS,
}


class PatchExtractionError(ValueError):
    """The model's `{intent, changes}` response cannot safely be used."""


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def _last_human_message(state: TravelGraphState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) == "human":
            return str(getattr(message, "content", "") or "")
    return ""


def _pending_slots(travel_state: TravelState) -> tuple[str, ...]:
    """The slots the user is answering right now — the one piece of
    conversational context a short reply needs before it means anything.

    Shares `pending_question_slots` with `ask_slot` so the paths this prompt
    will accept are exactly the ones the question put to the user. That
    matters most for dates: one question asks "đi và về ngày nào?", and the
    reply may name both dates, either one alone, or a range.

    Derived from the registry rather than read off `state["missing_slots"]`
    even though `load_context` preserves that field, because the two agree
    everywhere except the case that matters most: `missing_slots` is empty
    on a thread's FIRST turn (nothing has been asked yet), which is exactly
    the turn carrying the opening "Hồ Chí Minh". The registry answers from
    `travel_state`, which this node reads before any of this turn's changes
    are applied, so it names the same slots `ask_slot` asked at the end of
    the previous turn — and names `destination` on turn one.

    Without an anchor the model reads a short reply as changing nothing:
    "Hồ Chí Minh" and "1" both come back `general_question` with an empty
    patch, and the slot gate re-asks the same question forever. Measured,
    not assumed — the same message extracts correctly once anchored.

    Passed as slot NAMES rather than as conversation history on purpose:
    `messages` carries no assistant turns at all (`respond` writes only
    `response`), it grows without bound, and replaying earlier turns
    invites the model to re-emit already-confirmed facts as fresh changes.
    `SLOT_REGISTRY` names are already patch paths, so no mapping is needed.
    """
    return pending_question_slots(travel_state)


def _known_facts_summary(travel_state: TravelState) -> str:
    parts = [f"{path}={info['value']}" for path, info in travel_state.to_dict().items()]
    return "; ".join(parts) if parts else "none yet"


def _destination_choices(destination_names: Sequence[str | DestinationOption]) -> str:
    return ", ".join(
        option.name if isinstance(option, DestinationOption) else str(option) for option in destination_names
    )


def _resolve_day_scope(message: str, known_duration_days: int | None) -> tuple[int, ...] | None:
    """Deterministic day-scope resolution feeding `_rewrite_day_scope`.
    Numeric/range phrasing delegates to `trip_scheduler.parse_day_scope`
    (already proven against `trip_edit_planner`'s day-filtering); ordinal
    "first"/"last" phrasing is added here because that caller always has a
    real, already-built itinerary length, unlike this node. "Last day"
    only resolves once this trip's real length is known — guessing it off
    the generous pre-dates fallback would silently target the wrong day."""
    normalized = _normalize(message)
    if _FIRST_DAY_RE.search(normalized):
        return (1,)
    if _LAST_DAY_RE.search(normalized):
        return (known_duration_days,) if known_duration_days else None
    return parse_day_scope(message, known_duration_days or _MAX_DAY_NUMBER_FALLBACK)


def _rewrite_day_scope(
    changes: list[dict[str, Any]], message: str, travel_state: TravelState
) -> list[dict[str, Any]]:
    day_scope = _resolve_day_scope(message, trip_duration_days(travel_state))
    if not day_scope:
        return changes

    rewritten: list[dict[str, Any]] = []
    for change in changes:
        path = str(change.get("path") or "")
        if not _THEME_PATH_RE.match(path):
            rewritten.append(change)
            continue
        for day in day_scope:
            rewritten.append({**change, "path": f"daily_preferences.{day}.theme"})
    return rewritten


def _ground_included_breakfast(changes: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Bind an included-breakfast hotel request to the canonical amenity ID.

    The phrase is a hotel-search constraint, not an itinerary breakfast item.
    It must therefore reach ``hotel_preferences.amenities`` even when the
    extractor only returns the other amenity in a compound request.
    """
    normalized = _normalize(message)
    if not _BREAKFAST_INCLUDED_RE.search(normalized) or _BREAKFAST_NEGATED_RE.search(normalized):
        return changes
    has_breakfast = any(
        change.get("path") == "hotel_preferences.amenities" and str(change.get("value") or "").strip().lower() == "breakfast"
        for change in changes
    )
    if has_breakfast:
        return changes
    return [*changes, {"path": "hotel_preferences.amenities", "operation": "append", "value": "breakfast"}]


def _derive_end_date_from_duration(
    changes: list[dict[str, Any]], message: str, travel_state: TravelState
) -> list[dict[str, Any]]:
    """Fill the exclusive checkout date from an explicit day count and ISO start.

    The graph stores an end date rather than a duration slot.  A phrase such
    as ``2 ngày từ 2026-07-01`` is therefore complete hotel-search input and
    must not trigger a redundant checkout-date question.  An explicit end
    date returned by the extractor always wins.
    """
    if any(change.get("path") == "dates.end" for change in changes):
        return changes

    match = _DURATION_DAYS_RE.search(_normalize(message))
    if match is None:
        return changes

    start_value: Any = travel_state.get("dates.start").value
    for change in reversed(changes):
        if change.get("path") == "dates.start" and change.get("operation") == "set":
            start_value = change.get("value")
            break

    try:
        start = date.fromisoformat(str(start_value))
    except (TypeError, ValueError):
        return changes

    days = int(match.group("days"))
    return [
        *changes,
        {
            "path": "dates.end",
            "operation": "set",
            "value": (start + timedelta(days=days)).isoformat(),
        },
    ]


def _ground_closed_label(value: Any, allowed: tuple[str, ...]) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    return candidate if candidate in allowed else None


def _ground_closed_label_list(value: Any, allowed: tuple[str, ...]) -> list[str]:
    if not isinstance(value, list):
        return []
    requested = {str(item).strip() for item in value}
    return [label for label in allowed if label in requested]


def _ground_changes(
    changes: list[dict[str, Any]], destination_names: Sequence[str | DestinationOption]
) -> list[dict[str, Any]]:
    """Re-applies the two grounding contracts `apply_patch`'s own validators
    don't enforce (see module docstring). A change that fails grounding is
    dropped here rather than passed through — an ungrounded guess must
    never reach the patch layer, the same rule `_ground_extracted_facts`
    already enforces for the legacy plane."""
    grounded: list[dict[str, Any]] = []
    for change in changes:
        path = str(change.get("path") or "")
        operation = change.get("operation")
        value = change.get("value")

        if path == "destination" and operation == "set":
            destination = _match_known_destination(str(value or "").strip(), destination_names)
            if destination is None:
                continue
            grounded.append({**change, "value": destination})
            continue

        if path in _CLOSED_LIST_PATHS:
            allowed = _CLOSED_LIST_PATHS[path]
            if operation == "set":
                labels = _ground_closed_label_list(value, allowed)
                if not labels:
                    continue
                grounded.append({**change, "value": labels})
            elif operation in ("append", "remove"):
                label = _ground_closed_label(value, allowed)
                if label is None:
                    continue
                grounded.append({**change, "value": label})
            else:
                grounded.append(change)
            continue

        if path in _CLOSED_SCALAR_PATHS and operation == "set":
            label = _ground_closed_label(value, _CLOSED_SCALAR_PATHS[path])
            if label is None:
                continue
            grounded.append({**change, "value": label})
            continue

        grounded.append(change)
    return grounded


def _strip_json_fence(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_extraction_payload(payload: object) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise PatchExtractionError("response must be a JSON object")
    intent = str(payload.get("intent") or "")
    if intent not in _INTENTS:
        raise PatchExtractionError(f"intent must be one of {sorted(_INTENTS)}")

    raw_changes = payload.get("changes")
    if raw_changes is None:
        raw_changes = []
    if not isinstance(raw_changes, list):
        raise PatchExtractionError("changes must be a list")

    changes: list[dict[str, Any]] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            raise PatchExtractionError("each change must be an object")
        path = item.get("path")
        operation = item.get("operation")
        if not isinstance(path, str) or not path.strip():
            raise PatchExtractionError("each change requires a non-empty string path")
        if operation not in _OPERATIONS:
            raise PatchExtractionError(f"each change's operation must be one of {sorted(_OPERATIONS)}")
        changes.append({"path": path.strip(), "operation": operation, "value": item.get("value")})
    return intent, changes


def _extract_with_llm(
    message: str,
    travel_state: TravelState,
    destination_names: Sequence[str | DestinationOption],
    *,
    pending_slots: tuple[str, ...] = (),
    llm: Any | None = None,
) -> tuple[str, list[dict[str, Any]], bool]:
    """Ask the configured model once, retrying exactly once for invalid
    output (`plan_trip_edit`'s proven shape) — never more than that, and
    never raises: a fallback here must still let the turn complete.

    The third return value is `extraction_failed` — True only when both
    attempts were unusable, so `route_ask_slot` (Phase 15) can tell that
    apart from a parse that genuinely concluded "no change" and never route
    a provider outage or garbled JSON to `intake_qa` as if it were a
    real question.
    """
    destination_choices = _destination_choices(destination_names)
    known_facts = _known_facts_summary(travel_state)
    today = date.today().isoformat()

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            # Constructing the model is retried too -- a provider/factory
            # failure (e.g. `get_reasoning_llm` itself, not just `.invoke()`)
            # must hit the same fallback, never crash the turn.
            model = llm or get_reasoning_llm(temperature=0.0)
            prompt = build_extract_patch_prompt(
                message=message,
                known_facts=known_facts,
                destination_choices=destination_choices,
                today=today,
                preference_labels=", ".join(_PREFERENCE_LABELS),
                companion_labels=", ".join(_COMPANION_LABELS),
                pace_labels=", ".join(_PACE_LABELS),
                day_rhythm_labels=", ".join(_DAY_RHYTHM_LABELS),
                pending_slots=pending_slots,
                repair=str(last_error) if attempt else None,
            )
            response = model.invoke(prompt)
            payload = json.loads(_strip_json_fence(getattr(response, "content", response)))
            intent, changes = _parse_extraction_payload(payload)
            return intent, changes, False
        except (json.JSONDecodeError, PatchExtractionError, TypeError, ValueError) as exc:
            last_error = exc
        except Exception as exc:  # provider failures must never crash the turn
            last_error = exc

    logger.warning("Patch extraction failed for message %r: %s", message, last_error)
    return "general_question", [], True


def extract_patch(state: TravelGraphState) -> dict[str, Any]:
    message = _last_human_message(state)
    if not message:
        return {"patch": [], "intent": "general_question", "extraction_failed": True}

    travel_state = TravelState.from_dict(state.get("travel_state"))
    destination_names = _get_destination_names()

    intent, raw_changes, extraction_failed = _extract_with_llm(
        message, travel_state, destination_names, pending_slots=_pending_slots(travel_state)
    )
    changes = _rewrite_day_scope(raw_changes, message, travel_state)
    changes = _derive_end_date_from_duration(changes, message, travel_state)
    changes = _ground_changes(changes, destination_names)
    changes = _ground_included_breakfast(changes, message)

    # Written unconditionally, not only when True: this key gates Phase 15's
    # `intake_qa` routing branch, and a node's partial return is merged over
    # whatever the channel already held -- an omitted key here would leave
    # a stale `True` in place for any caller that invokes this node outside
    # `load_context`'s per-turn reset (a future subgraph, a resume path, a
    # test), fail-closed-disabling that branch silently.
    return {"patch": changes, "intent": intent, "extraction_failed": extraction_failed}
