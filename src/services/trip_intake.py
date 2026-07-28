"""Deterministic fact collection for the terminal trip-planning conversation."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

_NUMBER_WORDS = {
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
    "muoi": 10,
}

_PREFERENCE_TERMS = (
    ("biển", ("bien", "beach", "coast")),
    ("văn hóa", ("van hoa", "culture", "heritage")),
    ("ẩm thực", ("am thuc", "food", "cuisine")),
    ("thiên nhiên", ("thien nhien", "nature", "outdoor")),
    ("lịch sử", ("lich su", "history", "historical")),
    ("mua sắm", ("mua sam", "shopping")),
    ("cuộc sống về đêm", ("cuoc song ve dem", "nightlife")),
    ("trẻ em", ("tre em", "children", "kids", "family")),
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
        destination = self.destination or _extract_destination(message, destination_names)
        duration = self.duration or _extract_duration(message)
        people = self.people or _extract_people(message)
        preferences = list(self.preferences)
        normalized = _normalize(message)
        for label, aliases in _PREFERENCE_TERMS:
            if label not in preferences and any(_contains_phrase(normalized, alias) for alias in aliases):
                preferences.append(label)
        return replace(
            self,
            destination=destination,
            duration=duration,
            people=people,
            preferences=tuple(preferences),
        )

    def next_question(self) -> str | None:
        if not self.destination:
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


def _extract_destination(
    message: str,
    destination_names: Sequence[str | DestinationOption],
) -> str | None:
    normalized = _normalize(message)
    matches = []
    for destination in destination_names:
        option = destination if isinstance(destination, DestinationOption) else DestinationOption(destination)
        if not option.name:
            continue
        normalized_name = _normalize(option.name)
        normalized_aliases = tuple(
            normalized_alias
            for alias in option.aliases
            if (normalized_alias := _normalize(alias).strip())
        )
        phrases = (normalized_name, *normalized_aliases)
        if any(_contains_phrase(normalized, phrase) for phrase in phrases):
            matches.append(option.name)
    return max(matches, key=len) if matches else None


def _extract_duration(message: str) -> str | None:
    match = re.search(
        r"\b(\d+|một|mot|hai|ba|bốn|bon|tư|tu|năm|nam|sáu|sau|bảy|bay|tám|tam|chín|chin|mười|muoi)"
        r"\s*(ngày|ngay|tuần|tuan|tháng|thang|day|days|week|weeks|month|months)\b",
        message,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip() if match else None


def _extract_people(message: str) -> str | None:
    normalized = _normalize(message)
    match = re.search(
        r"\b(\d+|mot|hai|ba|bon|tu|nam|sau|bay|tam|chin|muoi)\s*"
        r"(nguoi|people|persons?)\b",
        normalized,
    )
    if match:
        token = match.group(1)
        count = int(token) if token.isdigit() else _NUMBER_WORDS[token]
        return f"{count} người"
    if any(
        phrase in normalized
        for phrase in ("mot minh", "minh toi", "chi minh", "just me", "by myself")
    ):
        return "1 người"
    if any(
        phrase in normalized
        for phrase in (
            "cung vo",
            "voi vo",
            "cung chong",
            "voi chong",
            "hai vo chong",
            "couple",
            "my wife",
            "my husband",
        )
    ):
        return "2 người"
    return None


def _contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text))


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()
