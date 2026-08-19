"""`extract_patch` — one LLM call producing `{intent, changes[], reason}`
(doc §36 `understand_request`), replacing the three separate extraction
calls the legacy plane still runs (`_llm_extract_intake_facts`,
`TripPreferenceUpdate.from_message`, `plan_trip_edit`). `intent` never
selects a WORKER — `detect_impact` + `WORKFLOW_TO_WORKER` does that, off the
validated patch (`validate_patch`/`apply_patch`) — but it does separate
read-only Q&A from state-changing turns on one routing edge (Phase 15,
`routing.is_intake_question`); see `state.py`'s field comment. `reason`
selects no route by itself either — it only feeds `routing.is_incomplete_edit`,
which reads it alongside `intent` and `patch` (see `plan.md`'s "Decided
while planning" table).

Defensive parsing mirrors `trip_edit_planner.plan_trip_edit`'s proven shape:
strict JSON parse -> structural validate -> retry once with the rejection
reason. Unlike that function, a fallback here never raises —
`{"patch": [], "intent": "general_question"}` lets the turn complete exactly
as an empty patch always has (`validate_patch`/`apply_patch` commit nothing,
`pending_tasks` stays empty, the supervisor's existing IMPACT_MAP/LLM
fallback takes it from there). `reason` is parsed non-strictly, unlike
`intent`/`changes`: it is an enhancement on top of that same fallback shape,
not part of the turn's own correctness, so a missing key, a null, a
non-string, or an unrecognized value all fall open to `""` rather than
spending the retry (see `_parse_extraction_payload`).

Two things `apply_patch`'s validators do NOT enforce, so this node grounds
them itself before a change is handed off:
- `destination` against the real destinations table (`_match_known_destination`)
- the closed label sets for `preferences.themes` / `.companions` / `.pace`
  / `.day_rhythm` (`trip_intake.py`'s vocabulary, kept as the grounding
  authority per this phase's plan)

The prompt sees exactly one message, never the transcript. Its cross-turn
context is the pending slot names (`_pending_slots`), which is what makes a
short reply ("Hồ Chí Minh", "1", "20/7") interpretable without paying for
unbounded history on every turn -- plus, for a message too short to mean
anything on its own, the previous reply alone (`_acknowledgement_context`).
That second one exists because a bare agreement carries its meaning entirely
in the offer it accepts: "có nha" answering "muốn mình tìm khách sạn có hồ
bơi không?" states nothing, extracted to `general_question` with an empty
patch, and routed to the read-only worker -- which cannot search hotels, so
it improvised a question about districts the destination data has no rows
for, and re-asked it forever. Both gates there keep every substantive
message extracting from its own words exactly as before.

Day-scope resolution ("ngày 1", "hôm đầu", "ngày cuối") is deterministic,
not model-decided: `_resolve_day_scope`/`_rewrite_day_scope` force any
theme-shaped change to `daily_preferences.<day>.theme` when the message
names a day, removing the prompt collision `trip_edit_planner.py:442/445`
used to have between "day theme" and "vibe/preferences" routing.

`pending_clarify_day` (Phase 16) extends that same rewrite across a turn
boundary. This prompt is single-message with no transcript (see
`_pending_slots` below), so a bare follow-up reply to `intake_qa`'s clarify
question ("which theme for day 1?" -> "biển") names no day itself and would
otherwise land as a trip-wide `preferences.themes` change instead of that
day's. `state["pending_clarify_day"]`, read back at the top of the next
call as a fallback when the new message names no day of its own and no slot
is missing, is not reset by `load_context` (same convention as
`missing_slots`) so it survives the turn boundary. It is always overwritten
on the way out -- to the ONE day this message itself named (never the
carried-over one, and never when it named more than one), whenever that
leaves the patch empty with `patch_reason: "missing_value"` on an included
intent, or to `None` otherwise. Persisting only a message's own mention
(not the effective, fallback-inclusive one) is what keeps this from
renewing indefinitely: an unrelated later turn that also comes back empty
and `missing_value` -- a budget edit with no amount, say -- clears the
anchor rather than re-arming it for a message two turns later that never
mentioned any day at all.

This is a single-hop anchor, not a durable one, and it has a known gap:
three graph paths never call this node at all -- `scope_guard` blocking a
turn, `POST /hotels/select`'s `Command(goto="hotel_node", ...)`, and an
interrupt resume's `Command(resume=...)` (`routes.py`) -- so a day named
right before any of them can still be read back on whichever LATER turn
finally reaches this node again, past the one-turn boundary the rest of
this mechanism assumes. Accepted for now: closing it means clearing the
field from outside this node, on paths this module doesn't own.
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
from src.agents.graph.routing import _INCOMPLETE_EDIT_INTENTS
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
# The one intent that states nothing about the trip. Deterministic grounding
# rescues stay out of it entirely -- see `_ground_amenity`.
_READ_ONLY_INTENT = "general_question"
_OPERATIONS = frozenset({"set", "unset", "append", "remove"})
# Parsed non-strictly (see module docstring) -- anything else, including a
# non-string value that `in` can't even hash, falls open to "".
_PATCH_REASONS = frozenset({"missing_value", "no_change"})
_MAX_DAY_NUMBER_FALLBACK = 90  # mirrors travel_state.py's own pre-dates ceiling
# Longest a message can be and still be treated as a bare agreement worth
# reading against the previous reply ("có nha", "ok tìm giúp mình"). Anything
# longer states enough to extract from on its own.
_ACKNOWLEDGEMENT_CHAR_LIMIT = 40
# Bounds the previous reply pasted into the prompt -- a reply can be a whole
# itinerary listing, and this prompt is otherwise constant-size.
_PREVIOUS_REPLY_CHAR_LIMIT = 600

# Theme-shaped paths eligible for the deterministic day-scope rewrite --
# everything else (budget, destination, amenities, ...) passes through
# untouched even inside a day-scoped message.
_THEME_PATH_RE = re.compile(r"^(preferences\.themes|daily_preferences\.\d+\.theme)$")

_FIRST_DAY_RE = re.compile(r"\b(?:ngay|hom)\s+dau(?:\s+tien)?\b")
_LAST_DAY_RE = re.compile(r"\b(?:ngay|hom)\s+cuoi(?:\s+cung)?\b")
_DURATION_DAYS_RE = re.compile(r"\b(?P<days>[1-9]\d?)\s*(?:ngay|day)\b")
_BREAKFAST_INCLUDED_RE = re.compile(r"\b(?:bao\s+gom|included)\s+(?:(?:an|bua)\s+sang|breakfast)\b")
_BREAKFAST_NEGATED_RE = re.compile(r"\b(?:khong|without|no)\s+(?:bao\s+gom\s+)?(?:(?:an|bua)\s+sang|breakfast)\b")
# Same phrasing set as schemas.py's _AMENITY_INTENT_ALIASES["sea_view"], plus
# "huong bien" (another common Vietnamese phrasing not in that keyword list).
_SEA_VIEW_RE = re.compile(r"\b(?:view\s*bien|nhin\s+ra\s+bien|huong\s+bien|sea\s*view|ocean\s*view)\b")
_SEA_VIEW_NEGATED_RE = re.compile(
    r"\b(?:khong|without|no)\s+(?:can\s+)?(?:view\s*bien|nhin\s+ra\s+bien|huong\s+bien|sea\s*view|ocean\s*view)\b"
)
# The exact template compose-intake-message.ts always sends for the
# date-range picker: "từ ngày D/M/Y đến ngày D/M/Y" (normalized: no
# diacritics). Day is NOT zero-padded, month IS (Intl.DateTimeFormat's
# {day: 'numeric', month: '2-digit'}), so both are matched loosely.
_EXPLICIT_DATE_RANGE_RE = re.compile(
    r"tu\s+ngay\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+den\s+ngay\s+(\d{1,2})/(\d{1,2})/(\d{4})"
)

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


def _previous_assistant_reply(state: TravelGraphState) -> str:
    """The reply the user is answering, tail-trimmed, or "" when there is none.

    `respond` appends every reply it sends back to `messages` as an
    `AIMessage`, so the newest AI message is what the user actually read
    before typing this turn's message. The TAIL is what's kept when it is
    long: an offer is made at the end of a reply ("... Muốn mình tìm thêm
    khách sạn có hồ bơi không?"), so trimming the front keeps the part a
    bare "có nha" is agreeing to while bounding a reply that could otherwise
    be a whole itinerary listing.
    """
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) != "ai":
            continue
        reply = str(getattr(message, "content", "") or "").strip()
        return reply[-_PREVIOUS_REPLY_CHAR_LIMIT:] if len(reply) > _PREVIOUS_REPLY_CHAR_LIMIT else reply
    return ""


def _acknowledgement_context(state: TravelGraphState, message: str, pending_slots: tuple[str, ...]) -> str:
    """The previous reply, but only for the turn that cannot be read without
    it: a message short enough to be a bare agreement, with no slot question
    open.

    Both gates keep this from widening the prompt's single-message design
    (see the module docstring) any further than the bug requires. The length
    gate leaves every substantive message extracting from its own words
    alone, exactly as before. The `pending_slots` gate hands short replies to
    `pending_suffix` instead whenever a slot question is open, so the two
    hints never compete to explain the same "1" or "Hồ Chí Minh".
    """
    if pending_slots or len(message.strip()) > _ACKNOWLEDGEMENT_CHAR_LIMIT:
        return ""
    return _previous_assistant_reply(state)


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


def _rewrite_day_scope(changes: list[dict[str, Any]], day_scope: tuple[int, ...] | None) -> list[dict[str, Any]]:
    """Pure rewrite: forces any theme-shaped change to `daily_preferences.
    <day>.theme` for each day in `day_scope`. Resolving `day_scope` itself
    is the caller's job (`extract_patch`) -- this is reused for both a
    message's own day mention and Phase 16's carried-over clarify-day
    fallback, which is exactly the same rewrite once a day number is known,
    however it was known.

    `preferences.themes` is a list of closed-set labels; `daily_preferences.
    <day>.theme` is one free-text string (`_validate_daily_theme`). A change
    rewritten from the former keeps the latter's shape too, joining the
    list -- otherwise a day-scoped theme silently fails `validate_patch`
    and never applies, with nothing telling the user why."""
    if not day_scope:
        return changes

    rewritten: list[dict[str, Any]] = []
    for change in changes:
        path = str(change.get("path") or "")
        if not _THEME_PATH_RE.match(path):
            rewritten.append(change)
            continue
        value = change.get("value")
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        for day in day_scope:
            rewritten.append({**change, "path": f"daily_preferences.{day}.theme", "value": value})
    return rewritten


def _ground_amenity(
    changes: list[dict[str, Any]],
    message: str,
    *,
    intent: str,
    phrase_re: re.Pattern[str],
    negated_re: re.Pattern[str],
    canonical_id: str,
) -> list[dict[str, Any]]:
    """Bind one hotel-amenity phrase to its canonical catalog ID.

    A deterministic rescue for the case the extractor drops one half of a
    compound request ("view biển và có bao bữa sáng" coming back with only
    the breakfast amenity). It does two things the extractor alone can't be
    relied on for, and deliberately does neither outside a stating turn.

    `intent` gate: this only ever runs for a message that STATES a
    requirement. A read-only question that merely names the amenity
    ("trong số những khách sạn đó cái nào có view biển?") is
    `general_question`, and prompts.py's extract-patch contract says so in
    as many words -- but this rescue used to run regardless of intent, so
    it appended a `hotel_preferences.amenities` change the model had
    correctly declined to make. A non-empty patch makes `pending_tasks`
    non-empty, which sends the supervisor's zero-LLM fast path straight to
    `hotel_node`: the question was answered with a whole new hotel search
    (reported: a question about one already-shown hotel returned "mình tìm
    được 9 khách sạn" instead of an answer). Because the injection was
    deterministic, so was the bug -- it reproduced on every such message.

    Raw-alias replacement: the extractor usually ALSO emits the user's own
    wording for the same amenity ("view biển"). That spelling is not a
    catalog keyword, so `resolve_hotel_amenity_ids` leaves it unresolved
    forever in an append-only slot, and `hotel_node` reports it as
    unsupported in the very same reply that applies the canonical filter --
    "Không có khách sạn nào vừa có đủ các tiện ích: Nhìn ra biển ... Mình
    chưa hỗ trợ lọc theo: view biển". Any amenity value that is itself a
    spelling of this phrase is therefore dropped in favour of the canonical
    ID rather than kept beside it.
    """
    if intent == _READ_ONLY_INTENT:
        return changes
    normalized = _normalize(message)
    if not phrase_re.search(normalized) or negated_re.search(normalized):
        return changes

    kept: list[dict[str, Any]] = []
    has_canonical = False
    for change in changes:
        if change.get("path") != "hotel_preferences.amenities":
            kept.append(change)
            continue
        value = str(change.get("value") or "").strip()
        if value.lower() == canonical_id:
            has_canonical = True
            kept.append(change)
            continue
        # A raw spelling of the amenity the canonical ID already covers.
        # The canonical ID itself never matches here: every alternative in
        # these patterns is whitespace-separated, and the IDs are
        # underscore-joined ("sea_view").
        if phrase_re.search(_normalize(value)):
            continue
        kept.append(change)

    if has_canonical:
        return kept
    return [*kept, {"path": "hotel_preferences.amenities", "operation": "append", "value": canonical_id}]


def _ground_included_breakfast(
    changes: list[dict[str, Any]], message: str, intent: str
) -> list[dict[str, Any]]:
    """Bind an included-breakfast hotel request to the canonical amenity ID.

    The phrase is a hotel-search constraint, not an itinerary breakfast item.
    It must therefore reach ``hotel_preferences.amenities`` even when the
    extractor only returns the other amenity in a compound request.
    """
    return _ground_amenity(
        changes,
        message,
        intent=intent,
        phrase_re=_BREAKFAST_INCLUDED_RE,
        negated_re=_BREAKFAST_NEGATED_RE,
        canonical_id="breakfast",
    )


def _ground_sea_view(changes: list[dict[str, Any]], message: str, intent: str) -> list[dict[str, Any]]:
    """Bind a sea-view hotel request to the canonical amenity ID -- the same
    rescue `_ground_included_breakfast` applies for breakfast, and for the
    same reason: a compound request ("view biển và có bao bữa sáng") can
    have the extractor return only one of the two amenities, and sea view
    had no deterministic backstop, so it could vanish with nothing to catch
    it (reported: the assistant never acknowledged the sea-view half of a
    two-amenity request, only the breakfast half).
    """
    return _ground_amenity(
        changes,
        message,
        intent=intent,
        phrase_re=_SEA_VIEW_RE,
        negated_re=_SEA_VIEW_NEGATED_RE,
        canonical_id="sea_view",
    )


def _derive_dates_from_explicit_range(changes: list[dict[str, Any]], message: str) -> list[dict[str, Any]]:
    """Force dates.start/dates.end from an explicit "từ ngày D/M/Y đến ngày
    D/M/Y" range stated verbatim, overriding whatever the LLM extracted for
    those two paths.

    This is the exact, fully-regular template `compose-intake-message.ts`
    always sends for the date-range picker -- unambiguous enough that a
    deterministic parse is strictly safer than trusting the model to copy
    two dates correctly out of one sentence (reported: a picked 3-night
    range was confirmed back as 2 nights -- the checkout date the user
    picked and the one the turn echoed back didn't match). Values are kept
    as raw `D/M/Y` text, same convention as every other numeric date this
    node hands off -- the deterministic resolver in `travel_state.py`
    parses that safely, never guessing a day/month order itself.
    """
    match = _EXPLICIT_DATE_RANGE_RE.search(_normalize(message))
    if not match:
        return changes
    start_day, start_month, start_year, end_day, end_month, end_year = match.groups()
    filtered = [change for change in changes if change.get("path") not in ("dates.start", "dates.end")]
    return [
        *filtered,
        {"path": "dates.start", "operation": "set", "value": f"{start_day}/{start_month}/{start_year}"},
        {"path": "dates.end", "operation": "set", "value": f"{end_day}/{end_month}/{end_year}"},
    ]


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


def _parse_extraction_payload(payload: object) -> tuple[str, list[dict[str, Any]], str]:
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

    # Non-strict on purpose (module docstring): `isinstance` first so a
    # non-string value (a list, a number) never reaches `in` on a frozenset,
    # which would raise for anything unhashable instead of falling open.
    raw_reason = payload.get("reason")
    reason = raw_reason if isinstance(raw_reason, str) and raw_reason in _PATCH_REASONS else ""
    return intent, changes, reason


def _extract_with_llm(
    message: str,
    travel_state: TravelState,
    destination_names: Sequence[str | DestinationOption],
    *,
    pending_slots: tuple[str, ...] = (),
    previous_reply: str = "",
    llm: Any | None = None,
) -> tuple[str, list[dict[str, Any]], str, bool]:
    """Ask the configured model once, retrying exactly once for invalid
    output (`plan_trip_edit`'s proven shape) — never more than that, and
    never raises: a fallback here must still let the turn complete.

    The last return value is `extraction_failed` — True only when both
    attempts were unusable, so `route_ask_slot` (Phase 15) can tell that
    apart from a parse that genuinely concluded "no change" and never route
    a provider outage or garbled JSON to `intake_qa` as if it were a
    real question. `reason` (third) is "" on that same fallback, for the
    same reason.
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
                previous_reply=previous_reply,
                repair=str(last_error) if attempt else None,
            )
            response = model.invoke(prompt)
            payload = json.loads(_strip_json_fence(getattr(response, "content", response)))
            intent, changes, reason = _parse_extraction_payload(payload)
            return intent, changes, reason, False
        except (json.JSONDecodeError, PatchExtractionError, TypeError, ValueError) as exc:
            last_error = exc
        except Exception as exc:  # provider failures must never crash the turn
            last_error = exc

    logger.warning("Patch extraction failed for message %r: %s", message, last_error)
    return "general_question", [], "", True


def extract_patch(state: TravelGraphState) -> dict[str, Any]:
    message = _last_human_message(state)
    if not message:
        return {
            "patch": [],
            "intent": "general_question",
            "extraction_failed": True,
            "patch_reason": "",
            "pending_clarify_day": None,
        }

    travel_state = TravelState.from_dict(state.get("travel_state"))
    destination_names = _get_destination_names()

    pending_slots = _pending_slots(travel_state)
    intent, raw_changes, reason, extraction_failed = _extract_with_llm(
        message,
        travel_state,
        destination_names,
        pending_slots=pending_slots,
        previous_reply=_acknowledgement_context(state, message, pending_slots),
    )

    # This message's own day mention, falling back to the day
    # `intake_qa`'s clarify question asked about last turn -- but only when
    # this turn is in the same context that question was: no slot missing.
    # `missing_slots` here is the value `ask_slot` left at the END of the
    # PREVIOUS turn (`load_context` deliberately preserves it, same value
    # `_pending_slots` above already relies on) -- gating on it stops a day
    # named mid-intake from anchoring a later intake reply that has nothing
    # to do with it.
    own_day_scope = _resolve_day_scope(message, trip_duration_days(travel_state))
    carried_day = state.get("pending_clarify_day") if not state.get("missing_slots") else None
    day_scope = own_day_scope or ((carried_day,) if carried_day is not None else None)

    changes = _rewrite_day_scope(raw_changes, day_scope)
    changes = _ground_changes(changes, destination_names)
    changes = _ground_included_breakfast(changes, message, intent)
    changes = _ground_sea_view(changes, message, intent)
    changes = _derive_dates_from_explicit_range(changes, message)
    changes = _derive_end_date_from_duration(changes, message, travel_state)

    # Persist the day THIS message itself named -- never the carried-over
    # one, or a later turn that also happens to be empty/missing_value but
    # is about something else entirely (a budget edit with no amount, say)
    # would silently renew the old anchor instead of expiring it. A
    # multi-day mention ("ngày 1 và ngày 2") isn't persisted either: one
    # int can't carry both, and guessing day 1 while silently dropping day
    # 2 is worse than the follow-up simply landing trip-wide.
    pending_clarify_day = (
        own_day_scope[0]
        if (
            not changes
            and reason == "missing_value"
            and intent in _INCOMPLETE_EDIT_INTENTS
            and own_day_scope
            and len(own_day_scope) == 1
        )
        else None
    )

    # Written unconditionally, not only when truthy: these keys gate
    # Phase 15/16's `intake_qa` routing branches, and a node's partial
    # return is merged over whatever the channel already held -- an omitted
    # key here would leave a stale value in place for any caller that
    # invokes this node outside `load_context`'s per-turn reset (a future
    # subgraph, a resume path, a test), silently misrouting on stale state.
    return {
        "patch": changes,
        "intent": intent,
        "extraction_failed": extraction_failed,
        "patch_reason": reason,
        "pending_clarify_day": pending_clarify_day,
    }
