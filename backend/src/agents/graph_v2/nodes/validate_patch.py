"""`validate_patch` — runs the Phase 3 patch layer's validators, and is the
ONLY node that calls `interrupt()` (Phase 7).

Computes what applying `state["patch"]` *would* produce without committing
it: the result lands in `proposed_travel_state`, and `apply_patch` (the
node) is the only one that writes `travel_state`. Keeping validation and
commit as two nodes is what lets this phase insert an `interrupt` between
them (asking the user to resolve an ambiguous date) without either node's
contract changing.

Standing constraint (binds every later phase too, see plan
`phase-07-slots-and-interrupt.md`): LangGraph re-runs a node from its start
on every resume, so a node calling `interrupt()` must be pure, or idempotent,
up to that call. This module imports nothing from `services` and makes no
LLM/DB/API call anywhere -- `domain.travel_state.apply_patch` is a pure
function, so calling it twice (once before the interrupt, once again when
the node re-executes on resume) is always safe.

One acknowledged, very-low-probability impurity: `apply_patch`'s date
validators read `date.today()`, so a thread paused across midnight and
resumed the next day could see a different ambiguity on re-run than the one
the interrupt message described (`interrupt()` matches resume values to
calls by position within the node, so this changes what a given resume
value answers, not whether the resume succeeds at all).
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from langgraph.types import interrupt

from src.agents.graph_v2.state import TravelGraphState
from src.domain.travel_state import DateAmbiguity, TravelState, apply_patch, detect_impact
from src.i18n import t

# A real patch never has more than a handful of date changes -- this only
# bounds a pathological loop, it is never expected to be hit.
_MAX_AMBIGUITY_ROUNDS = 8

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DAY_MONTH_RE = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})\s*$")


def _interrupt_payload(ambiguity: DateAmbiguity, language: str) -> dict[str, Any]:
    if ambiguity.kind == "missing_year":
        message = t(
            "Bạn muốn nói ngày {raw} năm nào? Cho mình biết năm cụ thể nhé.",
            language,
            raw=ambiguity.raw_value,
        )
    else:
        option_a, option_b = ambiguity.candidates
        message = t(
            "Ngày {raw} bạn nói có thể hiểu theo hai cách. Trả lời 1 hoặc 2:\n1. {a}\n2. {b}",
            language,
            raw=ambiguity.raw_value,
            a=option_a,
            b=option_b,
        )
    return {
        "kind": ambiguity.kind,
        "path": ambiguity.path,
        "raw_value": ambiguity.raw_value,
        "candidates": ambiguity.candidates,
        "message": message,
    }


def _resolve_missing_year(ambiguity: DateAmbiguity, resume_text: str) -> str | None:
    year_match = _YEAR_RE.search(resume_text)
    day_month_match = _DAY_MONTH_RE.match(ambiguity.raw_value)
    if not year_match or not day_month_match:
        return None
    day, month = day_month_match.groups()
    return f"{day}-{month}-{year_match.group(0)}"


def _resolve_day_month_order(ambiguity: DateAmbiguity, resume_text: str) -> str | None:
    # The interrupt message renders candidates as a numbered 1/2 list --
    # mirrors services/guided_question.py's numbered-menu convention, so a
    # bare digit reply is the expected, reliable shape.
    stripped = resume_text.strip()
    if stripped in ("1", "2"):
        return ambiguity.candidates[int(stripped) - 1]
    return None


def _resolved_value_for_resume(ambiguity: DateAmbiguity, resume_text: str) -> str | None:
    """Turns the human's raw reply to an `interrupt()` question back into a
    corrected patch value for `ambiguity.path` -- or None when the reply
    doesn't resolve it. A reply that fails to resolve simply drops that one
    change (never a second silent guess, never an infinite interrupt loop);
    the rest of the patch still applies, and `ask_slot` picks up the
    still-missing slot next."""
    if ambiguity.kind == "missing_year":
        return _resolve_missing_year(ambiguity, resume_text)
    return _resolve_day_month_order(ambiguity, resume_text)


def _replace_change(patch: list[dict[str, Any]], ambiguity: DateAmbiguity, resolved_value: str | None) -> list[dict[str, Any]]:
    remaining = [
        change
        for change in patch
        if not (change.get("path") == ambiguity.path and change.get("operation") == "set")
    ]
    if resolved_value is not None:
        remaining.append({"path": ambiguity.path, "operation": "set", "value": resolved_value})
    return remaining


def validate_patch(state: TravelGraphState) -> dict[str, Any]:
    travel_state = TravelState.from_dict(state.get("travel_state"))
    patch = list(state.get("patch") or [])
    language = state.get("language") or "vi"

    # Set when a resume reply fails to resolve its ambiguity -- the raw
    # text the human actually typed, so `_run_turn_via_graph` (routes.py)
    # can hand it back through a NORMAL turn instead of silently dropping
    # it. Without this, a reply to a paused interrupt that answers a
    # DIFFERENT intent (e.g. "thôi đổi điểm đến sang Huế" instead of
    # answering the date question) is never seen by `extract_patch` at all
    # -- exactly the "pending question isn't interruptible" class this
    # phase exists to kill, just recreated one level down.
    unresolved_resume_text: str | None = None

    result = apply_patch(travel_state, patch)
    for _ in range(_MAX_AMBIGUITY_ROUNDS):
        if not result.ambiguous:
            break
        ambiguity = result.ambiguous[0]
        resume_text = str(interrupt(_interrupt_payload(ambiguity, language)) or "")
        resolved_value = _resolved_value_for_resume(ambiguity, resume_text)
        if resolved_value is None:
            unresolved_resume_text = resume_text
        else:
            unresolved_resume_text = None
        patch = _replace_change(patch, ambiguity, resolved_value)
        result = apply_patch(travel_state, patch)

    impacted = sorted(detect_impact(result.applied))

    return {
        "proposed_travel_state": result.state.to_dict(),
        "applied_changes": [asdict(change) for change in result.applied],
        "rejected_changes": [asdict(rejection) for rejection in result.rejected],
        "impacted_workflows": impacted,
        "unresolved_resume_text": unresolved_resume_text,
    }
