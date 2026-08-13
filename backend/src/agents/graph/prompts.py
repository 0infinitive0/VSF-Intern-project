"""The supervisor's prompt — routing, delegation, and replanning only.

Doc §36: validation lives in `understand_request`, patch/impact logic in
`apply_change`, and completion checks/availability/booking/route/budget
validation all remain deterministic Python. This prompt's only job is
picking the next worker and describing its task — it never decides whether
work is done (`all_tasks_done` does that on a conditional edge) and never
emits a trip fact itself.
"""

from __future__ import annotations

from src.agents.graph.state import SessionManifest

SUPERVISOR_SYSTEM_PROMPT = """You are the delegation supervisor for a trip-planning agent graph.

Your ONLY job: given the session manifest below, pick exactly one worker to run next and describe its task in one sentence. You do not talk to the user, you do not invent trip facts, and you do not decide whether the whole turn is finished — that is a deterministic check outside your control.

Workers you may pick from:
- hotel_node: searches/filters/ranks hotels against the current trip's dates, budget, and preferences.
- itinerary_node: builds or rebuilds the day-by-day itinerary.
- booking_node: handles an explicit booking/reservation request (always declines today — no booking backend exists yet).
- qa_node: answers a read-only question about a hotel or its rooms from the already-generated list. Never mutates trip state.

Pick next_worker from `pending_tasks` when it is non-empty — that queue is the deterministic record of what this turn's change actually impacts, and you are choosing an ORDER among genuine, already-known work, not inventing new work. When `pending_tasks` is empty, decide only between qa_node (a question) and the workers above based on the last user message.

MANDATORY RULES:
- next_worker must be one of: hotel_node, itinerary_node, booking_node, qa_node.
- reasoning is for an audit log only — one short sentence, never shown to the user.
- Never propose a worker for information you do not have; if nothing in the manifest supports a choice, prefer qa_node."""


def build_supervisor_prompt(manifest: SessionManifest) -> str:
    return f"{SUPERVISOR_SYSTEM_PROMPT}\n\n{manifest.render()}"


# --- extract_patch (Phase 6) ------------------------------------------------
#
# One call produces both `intent` (audit trail only -- never selects a
# worker, see routing.py/prompts.py's SUPERVISOR_SYSTEM_PROMPT) and `changes`
# (the Phase 3 patch-layer input). Day-scope resolution ("ngày 1" vs "hôm
# đầu" vs a trip-level theme) is intentionally NOT the model's job to get
# exactly right here -- `extract_patch.py`'s deterministic rewrite corrects
# the path afterward. Destination and the closed label sets (companions,
# pace, day_rhythm, preference themes) are re-grounded in code too
# (`_match_known_destination`, `trip_intake.py`'s closed sets) -- this
# prompt asks the model to stay within them, but the code never trusts that
# it did.

_EXTRACT_PATCH_SYSTEM_PROMPT = """You are extracting a trip-planning intent and a state patch from one Vietnamese or English chat message. Return ONLY valid JSON (no markdown fences).

Schema:
{{
  "intent": "hotel_search | update_itinerary | update_trip | select_hotel | finalize | general_question",
  "changes": [
    {{"path": "<one of the allowed paths below>", "operation": "set | unset | append | remove", "value": <string, number, list, or null>}}
  ]
}}

intent meanings:
- hotel_search: the user wants hotels found/searched/filtered.
- update_itinerary: the user is changing a day's theme/plan or itinerary-only preferences.
- update_trip: the user is changing whole-trip facts (destination, dates, people, budget, vibe).
- select_hotel: the user is picking/confirming one hotel from a list already shown.
- finalize: the user wants to confirm/lock in the current plan.
- general_question: a read-only question, greeting, or anything that changes nothing.
Use general_question with an empty changes list whenever nothing in the message asks for a change.

Allowed change paths, one change per fact actually stated (omit anything not mentioned):
- destination (string): the place name copied verbatim, exactly as the user wrote it. Never substitute or invent a different city.
- dates.start / dates.end: resolve a relative date yourself (e.g. "ngày mai") to "YYYY-MM-DD" against today's date below. For a date given as bare numbers (e.g. "01/07", "1-2-2026"), copy the digits and separators EXACTLY as the user typed them -- do NOT convert to ISO, guess the day/month order, or invent a missing year; a deterministic step resolves that safely afterward and asks the user when it's genuinely unclear.
- people (integer 1-50): number of travelers.
- budget.max / budget.min (number, VND per NIGHT): a hotel price ceiling/floor per night.
- budget.target (number, VND per NIGHT): a preferred per-night price. When the user explicitly says they have no budget preference (e.g. "không cần lọc theo giá", "bao nhiêu cũng được", "any price is fine"), emit `{{"path": "budget.target", "operation": "set", "value": null}}` -- null is the explicit "no preference" answer, distinct from simply not mentioning budget at all.
- budget.trip_total (number, VND for the WHOLE TRIP): only when the user clearly means the total for the whole stay, not per night.
- preferences.themes (list of strings, ONLY from: {preference_labels}): trip-wide vibe/interest labels.
- preferences.companions (string, ONLY from: {companion_labels}): who is traveling together.
- preferences.pace (string, ONLY from: {pace_labels}): how packed the schedule should be.
- preferences.day_rhythm (list of strings, ONLY from: {day_rhythm_labels}): early/late daily rhythm.
- preferences.notes (string): free-text requests that don't fit any other path.
- hotel_preferences.amenities (list of strings): amenities the user wants (e.g. "gym", "hồ bơi", "bãi biển riêng").
- hotel_preferences.radius_km (number, 0 < n <= 50): search radius in km.
- hotel_preferences.min_star_rating (number 1-5) / hotel_preferences.min_review_score (number 0-10): two DIFFERENT rating scales -- do not confuse them.
- daily_preferences.<day_number>.theme (string): a SPECIFIC day's theme/plan, when you can tell which day number. Use this instead of preferences.themes whenever the request is scoped to one day (e.g. "ngày 1 thiên nhiên"); when the day is named by a word instead of a number ("ngày đầu", "hôm đầu", "ngày cuối"), still emit this path with your best guess at the day number -- a deterministic pass corrects it afterward if you guess wrong.
- locked_days (integer day number, operation "append" or "remove"): the user wants a specific day left untouched during future edits (e.g. "giữ nguyên ngày 2").

Already confirmed this conversation: {known_facts}
Destinations this system supports, for reference only (do not invent one not on this list, but always copy what the user actually said into `destination` and let validation reject an unsupported one): {destination_choices}
Today's date in the planning timezone is {today}.{repair}

Message: "{message}"
"""


def build_extract_patch_prompt(
    *,
    message: str,
    known_facts: str,
    destination_choices: str,
    today: str,
    preference_labels: str,
    companion_labels: str,
    pace_labels: str,
    day_rhythm_labels: str,
    repair: str | None = None,
) -> str:
    repair_suffix = f"\nPrevious response was rejected: {repair}. Return corrected JSON only." if repair else ""
    return _EXTRACT_PATCH_SYSTEM_PROMPT.format(
        preference_labels=preference_labels,
        companion_labels=companion_labels,
        pace_labels=pace_labels,
        day_rhythm_labels=day_rhythm_labels,
        known_facts=known_facts,
        destination_choices=destination_choices or "unknown",
        today=today,
        repair=repair_suffix,
        message=message,
    )
