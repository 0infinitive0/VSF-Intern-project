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
from src.services.trip_intake import _COMPANION_LABELS, _DAY_RHYTHM_LABELS, _PACE_LABELS, _PREFERENCE_LABELS

SUPERVISOR_SYSTEM_PROMPT = """You are the delegation supervisor for a trip-planning agent graph.

Your ONLY job: given the session manifest below, pick exactly one worker to run next and describe its task in one sentence. You do not talk to the user, you do not invent trip facts, and you do not decide whether the whole turn is finished — that is a deterministic check outside your control.

Workers you may pick from:
- hotel_node: searches/filters/ranks hotels against the current trip's dates, budget, and preferences.
- itinerary_node: builds/rebuilds the day-by-day itinerary, edits or suggests alternatives for one specific item within a day — a meal, a coffee stop, an attraction (e.g. "change day 1's breakfast spot", "suggest another lunch place", "remove day 2's afternoon activity") — AND lists notable nearby places on request, read-only, with no itinerary change (e.g. "tìm địa điểm nổi bật trong bán kính 3km", "gần khách sạn có gì hay ho", "gợi ý vài chỗ tham quan gần đây"). Any request naming a day and an item/activity to change, replace, remove, or find alternatives for belongs here too, even when phrased as a question ("any suggestions?") — it is never a read-only question, EXCEPT the nearby-places listing case above, which never touches the itinerary.
- booking_node: handles an explicit booking/reservation request (always declines today — no booking backend exists yet).
- qa_node: answers a read-only question about a hotel or its rooms from the already-generated list. Never mutates trip state, and never handles an itinerary item change or suggestion — that is itinerary_node's job.

Pick next_worker from `pending_tasks` when it is non-empty — that queue is the deterministic record of what this turn's change actually impacts, and you are choosing an ORDER among genuine, already-known work, not inventing new work. When `pending_tasks` is empty, decide only between qa_node (a question) and the workers above based on the last user message.

When next_worker is itinerary_node, also set `action` to exactly one of:
- "edit_item": replace, remove, or find alternatives for ONE specific meal/activity within a day, naming (or clearly implying) which one — "change day 1's breakfast spot", "suggest another lunch place", "remove day 2's afternoon activity". This is the default whenever a single item is at stake; it never touches the rest of that day.
- "rebuild_days": redo one or more WHOLE days from scratch — "redo day 2's schedule", "change day 1's theme", or the very first itinerary build after a hotel is picked.
- "lock_days": keep a day's plan untouched during future edits — "keep day 2 as is".
- "list_nearby": the user wants to SEE/DISCOVER notable places or attractions near the hotel (optionally within a stated radius), with NO change applied to the itinerary — a read-only listing, not an edit. "tìm địa điểm nổi bật trong bán kính 3km", "gần khách sạn có gì hay ho", "gợi ý vài chỗ tham quan gần đây". Use this whenever nothing specific (a day, a meal slot, an item) is being replaced — the request is just "show me what's around", not "change something in my plan".
`action` is ignored for every other next_worker; leave it unset then.

When action is "list_nearby", also set `radius_km` to the number of kilometers the user explicitly stated (e.g. "bán kính 3km" -> 3, "trong vòng 5 cây số" -> 5). Leave `radius_km` unset when the user did not state a distance — do not guess one.

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
  ],
  "reason": "missing_value | no_change",
  "asks_nearby_places": true | false
}}

intent meanings:
- hotel_search: the user wants hotels found/searched/filtered.
- update_itinerary: the user is changing a day's theme/plan or itinerary-only preferences.
- update_trip: the user is changing whole-trip facts (destination, dates, people, budget, vibe).
- select_hotel: the user is picking/confirming one hotel from a list already shown.
- finalize: the user wants to confirm/lock in the current plan.
- general_question: a read-only question, greeting, or anything that changes nothing.
Emit a change only for a fact the user STATES about their own trip. A value the message merely MENTIONS -- as the subject of a question, in a comparison, or as a hypothetical -- is not stated, so it produces no change no matter which path it would fit. A value paired with a TOPIC (what to see, weather, food, prices, what is good there) is a request for information about that topic, not a statement, even with no question mark. When the message states nothing, the intent is general_question with an empty changes list.
A question ASKING whether hotels/rooms already shown to the user have some feature (e.g. "trong số những khách sạn đó có khách sạn nào có view biển không?", "cái nào có ban công?", "phòng nào rẻ hơn?") is a request for information about results already on screen, not a new search -- it is general_question with an empty changes list, even when it names something that looks like an amenity ("view biển"). Only emit a hotel_preferences.amenities change when the user is STATING a new requirement for a search ("tìm khách sạn có view biển"), never when they are ASKING about hotels already found.
"reason" explains an EMPTY changes list and is ignored when changes is non-empty. Use "missing_value" when the message clearly asks to change something but never says what to change it TO -- "đổi theme ngày 1" names a day's theme with no theme. Use "no_change" for everything else that changes nothing: a request to redo work from facts already known ("tìm lại khách sạn", "lên lịch lại"), a question, a greeting, an acknowledgement.
"asks_nearby_places" is true ONLY when the user wants to SEE or DISCOVER notable places, attractions, or things to do near their hotel -- a read-only listing with no change to the plan ("liệt kê địa điểm nổi bật trong bán kính 3km", "gần khách sạn có gì hay ho", "gợi ý vài chỗ tham quan gần đây", "what's around the hotel?"). It is false for every other message, including a question about hotels/rooms already shown, a question about what a specific day already contains, and any request to CHANGE something in the plan. It is independent of "intent" and never changes it: a nearby-places question is still general_question with an empty changes list.

Allowed change paths, one change per fact actually stated (omit anything not mentioned):
- destination (string): the place name copied verbatim, exactly as the user wrote it -- the name alone, never the surrounding words. Never substitute or invent a different city.
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
Today's date in the planning timezone is {today}.{pending_slots}{repair}

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
    pending_slots: tuple[str, ...] = (),
    repair: str | None = None,
) -> str:
    # The one piece of conversational context a short reply needs. Anchoring
    # the pending slots structurally -- rather than pasting the transcript --
    # keeps this a single-message prompt: constant size no matter how long
    # the conversation runs, and no earlier turn for the model to
    # re-extract already-confirmed facts from. These are `SLOT_REGISTRY`
    # names, which are already patch paths, so they drop straight in.
    #
    # More than one path arrives when a single question gathers several
    # slots -- "bạn đi và về ngày nào?" asks dates.start and dates.end at
    # once, and the reply may fill either, both, or give a range. Saying so
    # explicitly is what stops a lone date from being dropped as
    # under-specified. The "clearly talks about something else" escape keeps
    # a genuine topic change (correcting the destination while the dates
    # question is open) from being coerced into a pending path.
    pending_suffix = ""
    if pending_slots:
        quoted = " and ".join(f"`{name}`" for name in pending_slots)
        pending_suffix = (
            f"\nThe assistant's previous message asked the user for {quoted}, so this message is most "
            f"likely the answer to it. If it reads as a short answer (a number, a date, a date range, a "
            f'place name, "không cần"), emit a change for each of those paths the message actually '
            f"supplies -- one of them alone is a perfectly good answer, so never withhold a value just "
            f"because the others are still unstated. If the message clearly talks about something else, "
            f"ignore this hint and extract what it actually says. Asking about {quoted} is not answering "
            f"it: a message that questions a value rather than stating it stays general_question with an "
            f"empty changes list."
        )
        if len(pending_slots) > 1:
            pending_suffix += (
                f" If it gives exactly one value and does not say which of {quoted} it means, treat it as "
                f"`{pending_slots[0]}`."
            )
    repair_suffix = f"\nPrevious response was rejected: {repair}. Return corrected JSON only." if repair else ""
    return _EXTRACT_PATCH_SYSTEM_PROMPT.format(
        preference_labels=preference_labels,
        companion_labels=companion_labels,
        pace_labels=pace_labels,
        day_rhythm_labels=day_rhythm_labels,
        known_facts=known_facts,
        destination_choices=destination_choices or "unknown",
        today=today,
        pending_slots=pending_suffix,
        repair=repair_suffix,
        message=message,
    )


# --- intake_qa (Phase 15/16) --------------------------------------------------
#
# Read-only escape valve with two entry points. Mid-intake (Phase 15,
# `ask_slot`'s "ask" branch): answers a genuine question asked while a
# required slot is still missing, without letting the model invent trip
# facts it has no source for, and without letting it ask a slot question
# itself -- `ask_slot` stays the sole owner of `next_question`, which this
# prompt is told about explicitly so it never duplicates it. Post-intake
# (Phase 16, `route_ask_slot`'s `is_incomplete_edit` branch): the message
# named an edit target but no value, so this asks for the one value instead
# of leaving the turn to commit nothing silently.
#
# `{role_line}` and `{question_rule}` are the only two things that differ
# between the two modes -- everything else (never invent a fact, stay
# brief, reply in `{language_name}`, the NO_ANSWER sentinel) is shared, one
# source of truth for both. `build_intake_qa_prompt`'s `clarify` flag picks
# which pair renders; intake mode (`clarify=False`, the default) renders
# byte-identically to the pre-Phase-16 prompt.

_INTAKE_QA_SYSTEM_PROMPT = """{role_line} Answer briefly and only from what you actually know -- if you don't know something (weather, prices, availability, real-time facts), say so plainly instead of guessing.

The message reaches you because an upstream classifier flagged it as "changes nothing about the trip" -- that classifier catches real questions, but ALSO greetings, acknowledgements ("ok", "cảm ơn"), and short replies it failed to connect to the pending question below. You must tell those apart: if the message does not actually ask something worth answering, reply with exactly the single word NO_ANSWER and nothing else -- do not greet back, do not comment, do not apologize.

Rules:
- Never invent a trip fact (destination, dates, budget, preferences) -- only use what is listed below as already known.
{question_rule}
- Keep the answer short (1-3 sentences).
- Reply in {language_name}.

Already known so far: {known_facts}

User's message: "{message}"
"""

_INTAKE_ROLE_LINE = (
    "You are a trip-planning assistant answering one user question while some trip details are still being "
    "collected."
)
# Post-intake: no slot is pending, so "still being collected" would be false
# -- this replaces it with what actually happened this turn instead. Does
# NOT claim "a plan exists": `is_incomplete_edit` only requires every intake
# slot to be answered (`missing_slots` empty), not `trip_data` to be built
# (that's a separate, later step -- picking a hotel) -- so a plan may not
# exist yet the first time this branch can fire.
_CLARIFY_ROLE_LINE = (
    "You are a trip-planning assistant. The user's trip details are already collected -- this message asked to "
    "change something but named no value to change it to, so nothing was applied."
)

# The day-theme sentence below is deliberately free-text (not a closed
# list): `_validate_daily_theme` (`domain/travel_state.py`) accepts any
# string up to 200 chars, so presenting a menu here would imply a
# constraint the validator does not enforce.
_CLARIFY_QUESTION_RULE = (
    "- Ask for exactly the one missing value, in one short question. Name what the user referred to "
    '(e.g. "ngày 1") so it is clear you understood them.\n'
    "- When a value must come from a fixed list, offer that list and nothing outside it -- trip themes: "
    f"{', '.join(_PREFERENCE_LABELS)}; companions: {', '.join(_COMPANION_LABELS)}; pace: "
    f"{', '.join(_PACE_LABELS)}; daily rhythm: {', '.join(_DAY_RHYTHM_LABELS)}. A specific day's theme is free "
    "text: give two or three examples, do not present a menu.\n"
    '- If the message is instead asking to REDO work from facts already known ("tìm lại khách sạn", "lên lịch '
    'lại", "gợi ý khách sạn khác"), then nothing is missing and no question is needed -- reply with exactly '
    "NO_ANSWER."
)

# The prompt's own escape hatch for "not actually a question" (see prompt
# text above) -- containment for the upstream classifier's known
# over-inclusion (`extract_patch`'s `general_question` bucket also catches
# greetings/acks/unrescued short replies), not a fix to that classifier.
INTAKE_QA_NO_ANSWER_SENTINEL = "NO_ANSWER"

_LANGUAGE_NAMES = {"vi": "Vietnamese", "en": "English"}


def build_intake_qa_prompt(
    *, message: str, known_facts: str, next_question: str, language: str, clarify: bool = False
) -> str:
    if clarify:
        role_line = _CLARIFY_ROLE_LINE
        question_rule = _CLARIFY_QUESTION_RULE
    else:
        role_line = _INTAKE_ROLE_LINE
        question_rule = (
            "- Never ask the user for any information yourself. Right after your answer, the assistant will "
            f'separately ask: "{next_question}" -- do not repeat, rephrase, or anticipate that question.'
        )
    return _INTAKE_QA_SYSTEM_PROMPT.format(
        role_line=role_line,
        question_rule=question_rule,
        message=message,
        known_facts=known_facts,
        language_name=_LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["vi"]),
    )
