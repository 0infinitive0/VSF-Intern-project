"""LLM-based fact collection for the terminal trip-planning conversation.

The LLM interprets free-form language; every fact it proposes is grounded
before it becomes state:
- `destination` is accepted only if it matches a real `destinations` row
  (name or alias) — an unmatched guess is discarded, not stored.
- `preference_labels` are accepted only if they are in the fixed closed set.
- `duration`/`people` are stored as canonically formatted strings derived
  from validated integers, never the model's raw text.

This mirrors `normalize_day_themes()` in `trip_scheduler.py`: the LLM
proposes, a pure function (`_ground_extracted_facts`) validates.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from src.services.llm import get_llm

logger = logging.getLogger(__name__)

_PREFERENCE_LABELS = (
    "biển",
    "văn hóa",
    "ẩm thực",
    "thiên nhiên",
    "lịch sử",
    "mua sắm",
    "cuộc sống về đêm",
    "trẻ em",
)


@dataclass(frozen=True)
class DestinationOption:
    name: str
    aliases: tuple[str, ...] = ()


def destination_options_from_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[DestinationOption, ...]:
    options = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        raw_aliases = row.get("aliases")
        aliases = (
            tuple(
                dict.fromkeys(
                    str(alias).strip()
                    for alias in raw_aliases
                    if str(alias).strip()
                )
            )
            if isinstance(raw_aliases, Sequence) and not isinstance(raw_aliases, str)
            else ()
        )
        options.append(DestinationOption(name=name, aliases=aliases))
    return tuple(options)


@dataclass(frozen=True)
class TripIntakeState:
    destination: str | None = None
    duration: str | None = None
    people: str | None = None
    preferences: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return bool(self.destination and self.duration and self.people)

    def with_message(
        self,
        message: str,
        destination_names: Sequence[str | DestinationOption],
    ) -> TripIntakeState:
        known_facts = {
            "destination": self.destination,
            "duration": self.duration,
            "people": self.people,
        }
        raw = _llm_extract_intake_facts(message, known_facts, destination_names)
        grounded = _ground_extracted_facts(raw, destination_names)

        # Destination aliases are authoritative database data, so they remain
        # safe to resolve when the extraction model returns malformed JSON.
        # This keeps inputs such as "HCM" usable without guessing a place.
        deterministic_destination = (
            _match_known_destination(message, destination_names)
            if not str(raw.get("destination") or "").strip()
            else None
        )
        destination = self.destination or grounded["destination"] or deterministic_destination
        duration = self.duration or grounded["duration"]
        people = self.people or grounded["people"]

        preferences = list(self.preferences)
        for label in grounded["preference_labels"]:
            if label not in preferences:
                preferences.append(label)

        return replace(
            self,
            destination=destination,
            duration=duration,
            people=people,
            preferences=tuple(preferences),
        )

    def next_question(
        self,
        destination_names: Sequence[str | DestinationOption] = (),
    ) -> str | None:
        if not self.destination:
            # Naming the supported destinations matters when the user asked for one
            # we don't cover: the grounding layer correctly refuses to guess, but a
            # bare "Bạn muốn đi đâu?" gives them no way to know that, so they retype
            # the same unsupported city and the conversation deadlocks.
            choices = ", ".join(
                option.name if isinstance(option, DestinationOption) else str(option)
                for option in destination_names
            )
            if choices:
                return f"Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}."
            return "Bạn muốn đi đâu?"
        if not self.duration:
            return "Bạn dự định đi trong bao lâu?"
        if not self.people:
            return "Chuyến đi có bao nhiêu người?"
        return None

    def tool_arguments(self) -> dict[str, str]:
        if not self.is_complete:
            raise ValueError("Destination, duration, and people are required.")
        return {
            "destination": str(self.destination),
            "duration": str(self.duration),
            "people": str(self.people),
            "preferences": ", ".join(self.preferences),
        }


def _llm_extract_intake_facts(
    message: str,
    known_facts: Mapping[str, str | None],
    destination_names: Sequence[str | DestinationOption],
    model: str | None = None,
) -> dict[str, Any]:
    """Thin LLM call: extract raw trip facts from one message. Fails soft to
    `{}` on any error so `with_message()` just re-asks the same question,
    mirroring `extract_search_filters`'s fallback in `supabase_search.py`."""
    destination_choices = ", ".join(
        (option.name if isinstance(option, DestinationOption) else str(option))
        for option in destination_names
    )
    known_parts = [f"{key}={value}" for key, value in known_facts.items() if value]
    known_summary = "; ".join(known_parts) if known_parts else "none yet"
    allowed_labels = ", ".join(_PREFERENCE_LABELS)

    prompt = f"""You are extracting trip-planning facts from a Vietnamese chat message.
Already confirmed this conversation: {known_summary}
Destinations this system supports, for reference only: {destination_choices or "unknown"}

Copy the destination the user actually named. Do NOT substitute a different city,
even when the one they named is missing from the list above — "Hội An" must stay
"Hội An", never become "Hà Nội" or "Đà Nẵng". Use null when they named none. A
separate validation step matches your answer against the supported list, so an
unsupported city is handled correctly; silently swapping it sends the user on a
trip to the wrong place.

Return ONLY valid JSON (no markdown fences) matching this schema:
{{
  "destination": "string or null - the destination the user named, copied verbatim",
  "duration_days": "integer or null - trip length in days (convert weeks/months to days, e.g. '1 tuần' = 7)",
  "people_count": "integer or null - number of travelers (e.g. 'vợ chồng tôi' = 2, 'một mình' = 1)",
  "preference_labels": "array of zero or more of these exact strings only: {allowed_labels}"
}}

Message: "{message}"
"""
    try:
        llm = get_llm(model=model, temperature=0.0)
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke(
            [
                SystemMessage(content="You extract structured trip-planning facts and return valid JSON only."),
                HumanMessage(content=prompt),
            ]
        )
        content = str(response.content).strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        parsed = json.loads(content.strip())
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        logger.warning("Intake fact extraction failed for message %r", message, exc_info=True)
        return {}


def _ground_extracted_facts(
    raw: Mapping[str, Any],
    destination_names: Sequence[str | DestinationOption],
) -> dict[str, Any]:
    """Pure validation/formatting layer: never trust `raw` directly. Unit
    test this function with hand-built dicts, the same convention as
    `normalize_day_themes()` in `trip_scheduler.py`."""
    raw_labels = raw.get("preference_labels")
    label_set = {str(item).strip() for item in raw_labels} if isinstance(raw_labels, list) else set()
    return {
        "destination": _match_known_destination(str(raw.get("destination") or "").strip(), destination_names),
        "duration": _format_duration_days(raw.get("duration_days")),
        "people": _format_people_count(raw.get("people_count")),
        "preference_labels": tuple(label for label in _PREFERENCE_LABELS if label in label_set),
    }


def _match_known_destination(
    guess: str,
    destination_names: Sequence[str | DestinationOption],
) -> str | None:
    if not guess:
        return None
    normalized_guess = _normalize(guess)
    if not normalized_guess:
        return None

    options = tuple(
        destination if isinstance(destination, DestinationOption) else DestinationOption(destination)
        for destination in destination_names
    )
    options = tuple(option for option in options if option.name)

    def normalized_phrases(option: DestinationOption) -> tuple[str, ...]:
        return tuple(
            phrase
            for phrase in (_normalize(option.name), *(_normalize(alias).strip() for alias in option.aliases))
            if phrase
        )

    # An exact match (name or alias) is unambiguous by construction — short-circuit
    # before the fuzzy containment pass below, which can otherwise collide on short
    # guesses (e.g. "Đà" containing/contained-by both "Đà Nẵng" and "Đà Lạt").
    for option in options:
        if normalized_guess in normalized_phrases(option):
            return option.name

    # Reverse containment (a known name/alias contains the guess) is only trusted
    # for multi-word guesses — a single truncated word ("Nông", "Nam") must not
    # silently resolve to an arbitrary destination sharing that substring.
    guess_is_multi_word = len(normalized_guess.split()) >= 2
    matches: set[str] = set()
    for option in options:
        for phrase in normalized_phrases(option):
            if _contains_phrase(normalized_guess, phrase):
                matches.add(option.name)
            elif guess_is_multi_word and _contains_phrase(phrase, normalized_guess):
                matches.add(option.name)

    return matches.pop() if len(matches) == 1 else None


def _format_duration_days(value: Any) -> str | None:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    if not 0 < days <= 90:
        return None
    return f"{days} ngày"


def _format_people_count(value: Any) -> str | None:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if not 0 < count <= 50:
        return None
    return f"{count} người"


def _contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text))


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()
