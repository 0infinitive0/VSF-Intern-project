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

# Safety net for when `_llm_extract_intake_facts` fails soft (returns `{}`,
# so `skip_preferences` defaults to False): without this, a plain "không"
# reply would be stored as a literal custom preference instead of being
# skipped. Only consulted when extraction produced nothing (see
# `with_message`'s `llm_unavailable` check) — a healthy LLM's
# `skip_preferences` answer is trusted as-is, since this set's broader
# substring forms ("khong can", "khong co") would otherwise also match — and
# discard — a real preference like "không cần khách sạn sang trọng, thích biển".
_NEGATIVE_RESPONSES = {
    "khong", "khong can", "khong co", "no", "none", "skip", "n/a", "k", "ko",
    "khong can dau", "khong co yeu cau gi", "khong co gi", "ko can",
}


_DECLINE_TRAILING_PARTICLES = {"a"}  # normalized "ạ" (politeness particle)


def _looks_like_decline(message: str) -> bool:
    normalized = _normalize(message).strip(" .!,;")
    tokens = normalized.split()
    if tokens and tokens[-1] in _DECLINE_TRAILING_PARTICLES:
        tokens = tokens[:-1]
    normalized = " ".join(tokens)
    return normalized in _NEGATIVE_RESPONSES or any(
        neg in normalized for neg in ("khong can", "khong co", "ko can")
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
    asked_preferences: bool = False

    @property
    def is_complete(self) -> bool:
        return bool(self.destination and self.duration and self.people and self.asked_preferences)

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

        destination = self.destination or grounded["destination"]
        duration = self.duration or grounded["duration"]
        people = self.people or grounded["people"]

        preferences = list(self.preferences)
        for label in grounded["preference_labels"]:
            if label not in preferences:
                preferences.append(label)

        asked_preferences = self.asked_preferences
        if self.destination and self.duration and self.people and not self.asked_preferences:
            asked_preferences = True
            # The deterministic decline check only applies when extraction produced
            # nothing at all (LLM/network failure) — when the LLM is healthy it owns
            # the skip decision via `skip_preferences`. Applying this check
            # unconditionally would let it override a working LLM and silently
            # discard legitimate preference text that happens to start with "không"
            # (e.g. "không cần khách sạn sang trọng, thích biển").
            llm_unavailable = not raw
            is_negative_response = llm_unavailable and _looks_like_decline(message)
            if not grounded["skip_preferences"] and not is_negative_response:
                clean_custom = message.strip()
                if clean_custom and clean_custom not in preferences:
                    preferences.append(clean_custom)

        return replace(
            self,
            destination=destination,
            duration=duration,
            people=people,
            preferences=tuple(preferences),
            asked_preferences=asked_preferences,
        )

    def next_question(self, selected_hotel: str | None = None) -> str | None:
        if not self.destination:
            return "Bạn muốn đi đâu?"
        if not self.duration:
            return "Bạn dự định đi trong bao lâu?"
        if not self.people:
            return "Chuyến đi có bao nhiêu người?"
        if not self.asked_preferences:
            ctx_parts = []
            if self.destination:
                ctx_parts.append(f"tại {self.destination}")
            if self.duration:
                ctx_parts.append(f"{self.duration}")
            if self.people:
                ctx_parts.append(f"cho {self.people}")
            if selected_hotel:
                ctx_parts.append(f"ở {selected_hotel}")
            ctx_str = f" ({', '.join(ctx_parts)})" if ctx_parts else ""

            dest_lower = (self.destination or "").lower()
            if "biển" in dest_lower or any(d in dest_lower for d in ("đà nẵng", "nha trang", "phú quốc", "vũng tàu", "quy nhơn")):
                ex = "'tập trung tắm biển', 'thưởng thức hải sản', 'du lịch nghỉ dưỡng', 'dạo phố đêm'"
            elif any(d in dest_lower for d in ("hà nội", "huế", "hội an")):
                ex = "'du lịch lịch sử', 'khám phá ẩm thực dân tộc', 'dạo quanh phố cổ', 'check-in địa danh'"
            elif any(d in dest_lower for d in ("hồ chí minh", "sài gòn")):
                ex = "'dạo vòng quanh thành phố', 'du lịch lịch sử & bảo tàng', 'trải nghiệm ẩm thực', 'mua sắm & cà phê'"
            elif "đà lạt" in dest_lower:
                ex = "'săn mây & check-in', 'cà phê ngắm cảnh', 'tham quan vườn hoa', 'nghỉ dưỡng yên bình'"
            else:
                ex = "'du lịch lịch sử', 'tập trung tắm biển', 'dạo vòng quanh thành phố', 'thưởng thức ẩm thực địa phương'"

            return (
                f"Bạn có yêu cầu hay lưu ý đặc biệt nào cho chuyến đi{ctx_str} không?\n"
                f"(Gợi ý ví dụ: {ex}... hoặc gõ 'không' để bỏ qua)"
            )
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
Known valid destinations (pick the closest match, or null if none fit): {destination_choices or "unknown"}

Return ONLY valid JSON (no markdown fences) matching this schema:
{{
  "destination": "string or null - a destination name from the known list above, or the user's best-guess destination text if not yet confirmed",
  "duration_days": "integer or null - trip length in days (convert weeks/months to days, e.g. '1 tuần' = 7)",
  "people_count": "integer or null - number of travelers (e.g. 'vợ chồng tôi' = 2, 'một mình' = 1)",
  "preference_labels": "array of zero or more of these exact strings only: {allowed_labels}",
  "skip_preferences": "true only if the message explicitly declines to give extra preferences (e.g. 'không', 'khong can', 'skip')"
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
        "skip_preferences": bool(raw.get("skip_preferences")),
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
