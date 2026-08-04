"""Reusable chat-turn guided questions: a numbered-option menu that also accepts
free text (via an optional parser) rather than forcing a strict menu pick.

Generic infrastructure, not owned by hotel selection or itinerary scheduling —
either can define its own `GuidedQuestion`s and reuse `format_guided_question`/
`resolve_guided_reply` without rebuilding the numbered-menu/free-text/skip logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class GuidedOption:
    label: str
    value: Any = None


@dataclass(frozen=True)
class GuidedQuestion:
    prompt: str
    options: tuple[GuidedOption, ...] = field(default_factory=tuple)
    free_text_parser: Callable[[str], Any | None] | None = None
    required: bool = True


def format_guided_question(question: GuidedQuestion) -> str:
    lines = [question.prompt]
    for index, option in enumerate(question.options, start=1):
        lines.append(f"{index}. {option.label}")
    return "\n".join(lines)


_PURE_NUMBER_LIST = re.compile(r"[\d\s,;/]+")


def resolve_guided_reply(question: GuidedQuestion, reply: str) -> tuple[bool, tuple[Any, ...]]:
    """Resolve a chat reply against a guided question.

    A reply is only treated as a numbered menu pick when it consists ENTIRELY of
    digits/separators (e.g. "2", "1,3", "1, 3") — this disambiguates a bare menu
    pick from free text that happens to contain a digit, e.g. "4 triệu" must be
    parsed as a price by free_text_parser, not misread as picking option 4. Any
    reply that isn't a pure number list goes straight to free_text_parser (if
    given), then falls back to (False, ()) for a required question (caller should
    re-ask) or (True, ()) for an optional one.
    """
    stripped = reply.strip()

    if stripped and _PURE_NUMBER_LIST.fullmatch(stripped):
        numbers = [int(token) for token in re.findall(r"\d+", stripped)]
        matched_values: list[Any] = []
        seen: set[int] = set()
        for number in numbers:
            if number in seen or not (1 <= number <= len(question.options)):
                continue
            seen.add(number)
            option = question.options[number - 1]
            if option.value is None:
                # A None-valued option is the canonical "skip" pick — wins outright.
                return True, ()
            matched_values.append(option.value)
        if matched_values:
            return True, tuple(matched_values)

    if question.free_text_parser is not None:
        parsed = question.free_text_parser(stripped)
        if parsed is not None:
            return True, (parsed,)

    if question.required:
        return False, ()
    return True, ()
