"""Which turn gets which metric, and why — the policy, with no scoring in it.

Kept apart from `e2e_eval.py` for two reasons: it imports no `ragas`, so the
backend suite can pin these rules without the eval venv
(`backend/tests/test_eval_turn_metrics.py`), and `transcripts.py` needs the same
rules to explain an `N/A` without importing the runner that imports it.

The rules exist because Faithfulness measures a *relationship* - answer against
retrieved context - and that relationship is absent on most turns of a scripted
booking conversation. Scoring those turns anyway does not produce a low score, it
produces a meaningless one, which is worse, because it looks like a finding.

`ResponseRelevancy` was dropped from Layer 2 entirely on 2026-08-20; the answer
checks below cover the turns it used to score, exactly and without a judge.
"""

import re
from collections.abc import Sequence

from harness.context_format import context_id

# How a turn's text should be read, keyed on the node that produced it. Replaces the
# legacy plane's `TurnResult.tool` names one-for-one:
#   recommend_hotels / select_hotel  -> hotel_node
#   finalize_trip_plan               -> booking_node, budget_check
#   execute_trip_edit_request        -> itinerary_node
# Templated turns render mostly from a fixed template; mixed turns blend template and
# generated prose and get their own bucket so neither average is inflated by the
# other's character. No worker at all (`ask_slot`, `intake_qa`, `qa_node`) is prose.
TEMPLATE_WORKERS = frozenset({"hotel_node", "booking_node", "budget_check"})
MIXED_WORKERS = frozenset({"itinerary_node"})

# Where Faithfulness is a valid measurement, not merely a computable one. It checks an
# answer against what retrieval returned, so it means something only where the answer's
# facts CAME from retrieval: hotel cards (`hotel_node`), day and place names
# (`itinerary_node`), and `qa_node`/`intake_qa` replies built on the contexts captured
# that turn (those report `worker is None` - `qa_node`'s subgraph writes no
# `task_results` entry - and are allowed through).
#
# `booking_node` and `budget_check` are excluded: their replies quote figures the app
# COMPUTED - a stay total, a per-night average, an over-budget delta - and no retrieved
# context contains a computed number. Scoring them compares two unrelated things and
# reports the mismatch as hallucination. Those turns need an arithmetic check instead.
FAITHFULNESS_WORKERS = frozenset({"hotel_node"})

# `itinerary_node` is judged by `ungrounded_itinerary_places` below instead. Its reply
# is a schedule — "Ngày 1: Ăn sáng tại Cơm Cậu Cả, Tham quan Công viên Văn hoá Lê Thị
# Riêng, …" — so almost every statement RAGAS extracts asserts a day and a meal slot,
# and the contexts are an unordered list of place names carrying neither. Measured on
# `conv-hcm-finalize-4d`: faithfulness 0.0 while all 7 places named were present in the
# conversation's retrieved contexts. That is the metric having nothing to check, not the
# agent inventing places — and "0.0" in a report reads as the opposite.
#
# What a judge cannot check here, an exact comparison can: every place the itinerary
# schedules must have come out of retrieval.
_ITINERARY_PLACE_RE = re.compile(
    r"(?:Ăn sáng tại|Ăn trưa tại|Ăn tối tại|Tham quan|Nghỉ ngơi tại|Thư giãn tại|quanh)\s+"
    r"([^,\n.]+)"
)
_ITINERARY_DAY_RE = re.compile(r"Ngày\s+\d+\s*:")


# --- Answer checks: did the reply carry the information the question asked for? -------
#
# `ResponseRelevancy` answers a nearby question badly for this product. It scores
# `cosine(user_input, question-reverse-generated-from-the-answer)`, which means a MORE
# complete answer scores LOWER: list the prices too and the generated question becomes
# "…which room types and at what price?", further from a user who only asked "which room
# types?". Measured ceiling for a perfect Vietnamese paraphrase is 0.7877, and an LLM
# `noncommittal` flag multiplies the whole thing to 0.0 unpredictably - two runs of the
# same conversation scored 0.632 and 0.0 on answers of equal quality.
#
# An answer check asks the question directly instead, with no embedding in the path: the
# user asked which rooms exist, so the reply must name rooms that exist. The dataset
# declares WHICH check applies to which turn; the truth comes from the product's own
# data at replay time, never from a string frozen into the dataset.
KNOWN_ANSWER_CHECKS = frozenset({"lists_rooms_of_selected_hotel"})


def _name_variants(name: str) -> tuple[str, ...]:
    """A room name and each parenthesised half of it.

    Room names are stored bilingually — "Phòng Deluxe Giường Đôi Hướng Phố (Deluxe City
    View Double Room)" — and an answer that uses only the Vietnamese half is naming the
    same room, not a different one.
    """
    stripped = name.strip()
    if not stripped:
        return ()
    outside = re.sub(r"\([^)]*\)", " ", stripped)
    inside = re.findall(r"\(([^)]*)\)", stripped)
    candidates = (stripped, outside, *inside)
    return tuple(trimmed for candidate in candidates if (trimmed := candidate.strip()))


def mentioned_items(reply: str, items: Sequence[str]) -> tuple[str, ...]:
    """Which of `items` the reply names, matching either half of a bilingual name."""
    haystack = reply.casefold()
    return tuple(
        item
        for item in items
        if any(variant.casefold() in haystack for variant in _name_variants(item))
    )


def answer_coverage(reply: str, items: Sequence[str]) -> float | None:
    """Fraction of `items` the reply names, or None when there is nothing to cover.

    Reported, never gated: an answer that omits sold-out rooms is not wrong, so a ratio
    below 1.0 is information rather than a failure. What IS a failure is naming none of
    them - the question then went unanswered - and `e2e_eval` checks that separately.
    """
    if not items:
        return None
    return len(mentioned_items(reply, items)) / len(items)


def ungrounded_hotel_ids(hotel_options, contexts: Sequence[str]) -> tuple[str, ...]:
    """Ids on the cards that no retrieval in this conversation returned.

    The guarantee "the agent never invents a hotel" is the one this product cannot get
    wrong, and an LLM judge is the wrong instrument for it. Measured on
    `conv-hue-thin-corpus-probe`: all five cards matched their retrieved context
    character for character, and Faithfulness still scored the turn **0.0** — one bad
    judge call moved the suite average from ~0.87 to 0.78. An exact id comparison cannot
    do that, in either direction.

    Compared against the CUMULATIVE contexts because `hotel_node` carries
    `previous_options` forward: a card retrieved two turns ago is still legitimately on
    screen. Ids are read back out of the rendered context strings with
    `context_format.context_id`, so there is one definition of "what retrieval
    returned" and not a second one that can drift from it.
    """
    retrieved = {cid for context in contexts if (cid := context_id(context))}
    return tuple(
        str(option.id)
        for option in (hotel_options or [])
        if option.id and str(option.id) not in retrieved
    )


def itinerary_places(reply: str) -> tuple[str, ...]:
    """Place names an itinerary reply schedules, in order, deduplicated."""
    return tuple(dict.fromkeys(name.strip() for name in _ITINERARY_PLACE_RE.findall(reply) if name.strip()))


def ungrounded_itinerary_places(reply: str, contexts: Sequence[str]) -> tuple[str, ...]:
    """Places the itinerary names that no retrieved context mentions — the
    hallucination this turn can actually commit.

    Contexts are `[uuid] Name — facts` strings, so a substring test against the whole
    line is enough and survives the facts suffix. Returns empty for a reply that is not
    an itinerary listing; a reply that IS one (`"Ngày 1:"`) but parses to no place at
    all is reported through `("<unparsed itinerary reply>",)` rather than passing
    silently, because a template change would otherwise turn this check off with
    nothing to show for it.
    """
    places = itinerary_places(reply)
    if not places:
        return ("<unparsed itinerary reply>",) if _ITINERARY_DAY_RE.search(reply) else ()
    joined = "\n".join(contexts).casefold()
    return tuple(place for place in places if place.casefold() not in joined)


def turn_class(worker: str | None) -> str:
    if worker in TEMPLATE_WORKERS:
        return "template"
    if worker in MIXED_WORKERS:
        return "mixed"
    return "generated"  # no worker ran, or a worker added after this map was written


def scores_faithfulness(*, worker: str | None, hotel_pick: bool, has_contexts: bool) -> bool:
    """A hotel-card click carries no factual claims of its own, a turn with no captured
    contexts has nothing to be faithful to, and a computed-figure worker has nothing in
    the contexts to match. Everything else with contexts is scoreable."""
    if hotel_pick or not has_contexts:
        return False
    if worker is not None and worker not in FAITHFULNESS_WORKERS:
        return False
    return True
