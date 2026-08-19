"""LLM-based fact collection for the terminal trip-planning conversation.

The LLM interprets free-form language; every fact it proposes is grounded
before it becomes state:
- `destination` is accepted only if it matches a real `destinations` row
  (name or alias) — an unmatched guess is discarded, not stored.
- `preference_labels` are accepted only if they are in the fixed closed set.
- `duration`/`people` are stored as canonically formatted strings derived
  from validated integers, never the model's raw text. The duration is the
  number of nights calculated from the confirmed start and exclusive end date.

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
from datetime import date, timedelta
from typing import Any

from src.domain.travel_state import Presence, TravelState, apply_patch
from src.i18n import t
from src.services.llm import get_fast_llm as get_llm
from src.services.llm import response_text

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
    "cổ điển",
    "cảnh đô thị",
)

# Fixed closed sets for the travel-style taxonomy added by the Trip Parameters
# Intake Form plan (260803-1713). These mirror the UI's fixed chip options
# (frontend/src/strings.ts) — the backend is the source of truth for grounding;
# if a label ever changes here, update that file too.
_COMPANION_LABELS = (
    "đi một mình",
    "đi cùng gia đình",
    "đi cùng người yêu hoặc vợ chồng",
    "đi cùng bạn bè",
    "có người lớn tuổi trong đoàn",
)

_PACE_LABELS = (
    "dày đặc",
    "vừa phải",
    "thư thái",
)

_DAY_RHYTHM_LABELS = (
    "bắt đầu sớm",
    "về khuya",
)


@dataclass(frozen=True)
class DestinationOption:
    name: str
    aliases: tuple[str, ...] = ()


class TripPreferenceUpdateError(ValueError):
    """A requested whole-trip preference change is missing or unsafe."""


@dataclass(frozen=True)
class TripPreferenceUpdate:
    """Validated, partial replacement of already-confirmed trip facts."""

    changed_fields: frozenset[str]
    destination: str | None = None
    duration: str | None = None
    start_date: str | None = None
    people: str | None = None
    preferences: tuple[str, ...] | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> TripPreferenceUpdate:
        if not isinstance(raw, Mapping):
            raise TripPreferenceUpdateError("Không xác định được thay đổi sở thích chuyến đi.")

        allowed_fields = {"destination", "duration", "start_date", "people", "preferences"}
        raw_changed_fields = raw.get("changed_fields")
        if isinstance(raw_changed_fields, list):
            changed_fields = {
                str(field).strip() for field in raw_changed_fields if str(field).strip() in allowed_fields
            }
        else:
            changed_fields = set()
            if str(raw.get("destination") or "").strip():
                changed_fields.add("destination")
            if raw.get("duration_days") is not None:
                changed_fields.add("duration")
            if raw.get("start_date") is not None:
                changed_fields.add("start_date")
            if raw.get("people_count") is not None:
                changed_fields.add("people")
            if isinstance(raw.get("preference_labels"), list) and raw.get("preference_labels"):
                changed_fields.add("preferences")

        if not changed_fields:
            raise TripPreferenceUpdateError("Không xác định được thông tin chuyến đi cần thay đổi.")

        destination = str(raw.get("destination") or "").strip() or None
        duration = _format_duration_days(raw.get("duration_days"))
        start_date = _format_start_date(raw.get("start_date"))
        people = _format_people_count(raw.get("people_count"))

        raw_labels = raw.get("preference_labels")
        label_set = (
            {str(item).strip() for item in raw_labels if str(item).strip()}
            if isinstance(raw_labels, list)
            else set()
        )
        preferences = (
            tuple(label_set)
            if "preferences" in changed_fields
            else None
        )

        invalid_fields = []
        if "destination" in changed_fields and destination is None:
            changed_fields.remove("destination")
        if "duration" in changed_fields and duration is None:
            invalid_fields.append("số ngày")
        if "start_date" in changed_fields and start_date is None:
            invalid_fields.append("ngày bắt đầu")
        if "people" in changed_fields and people is None:
            invalid_fields.append("số người")
        if "preferences" in changed_fields and not preferences:
            invalid_fields.append("sở thích")
        if invalid_fields:
            raise TripPreferenceUpdateError(
                "Không thể xác nhận an toàn: " + ", ".join(invalid_fields) + "."
            )

        return cls(
            changed_fields=frozenset(changed_fields),
            destination=destination,
            duration=duration,
            start_date=start_date,
            people=people,
            preferences=preferences,
        )

    @classmethod
    def from_message(
        cls,
        message: str,
        current: TripIntakeState,
        destination_names: Sequence[str | DestinationOption],
    ) -> TripPreferenceUpdate:
        raw = _llm_extract_intake_facts(
            message,
            {
                "destination": current.destination,
                "duration": current.duration,
                "start_date": current.start_date,
                "people": current.people,
            },
            destination_names,
        )
        return cls.from_raw(raw)

    def apply_to(
        self,
        current: TripIntakeState,
        destination_names: Sequence[str | DestinationOption],
    ) -> TripIntakeState:
        destination = current.destination
        if "destination" in self.changed_fields:
            destination = _match_known_destination(str(self.destination or ""), destination_names)
            if destination is None:
                raise TripPreferenceUpdateError("Không thể xác nhận điểm đến được hỗ trợ.")

        return replace(
            current,
            destination=destination,
            duration=self.duration if "duration" in self.changed_fields else current.duration,
            start_date=self.start_date if "start_date" in self.changed_fields else current.start_date,
            stay_end_date=(
                None
                if {"duration", "start_date"}.intersection(self.changed_fields)
                else current.stay_end_date
            ),
            people=self.people if "people" in self.changed_fields else current.people,
            preferences=(
                tuple(self.preferences or ())
                if "preferences" in self.changed_fields
                else current.preferences
            ),
        )


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
    start_date: str | None = None
    stay_end_date: str | None = None
    people: str | None = None
    preferences: tuple[str, ...] = ()
    companions: str | None = None
    pace: str | None = None
    day_rhythm: tuple[str, ...] = ()
    notes: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.destination and self.duration and self.start_date and self.end_date and self.people)

    @property
    def end_date(self) -> str | None:
        if self.stay_end_date:
            return self.stay_end_date
        if not self.start_date or not self.duration:
            return None
        try:
            start = date.fromisoformat(self.start_date)
            duration_days = int(self.duration.split(maxsplit=1)[0])
        except (TypeError, ValueError):
            return None
        return (start + timedelta(days=duration_days)).isoformat()

    @property
    def has_explicit_stay_dates(self) -> bool:
        """Whether the user supplied a valid check-in and exclusive checkout.

        Legacy callers can still construct a state from duration + start date,
        but guided intake must wait for a real end date so it never converts a
        duration answer into a hidden checkout date.
        """
        return bool(_duration_from_stay_dates(self.start_date, self.stay_end_date))

    def with_message(
        self,
        message: str,
        destination_names: Sequence[str | DestinationOption],
    ) -> TripIntakeState:
        known_facts = {
            "destination": self.destination,
            "duration": self.duration,
            "start_date": self.start_date,
            "end_date": self.end_date,
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
        start_date = self.start_date or grounded["start_date"]
        stay_end_date = self.stay_end_date or grounded["end_date"]
        duration = (
            _duration_from_stay_dates(start_date, stay_end_date)
            or self.duration
            or grounded["duration"]
        )
        people = self.people or grounded["people"]

        preferences = list(self.preferences)
        for label in grounded["preference_labels"]:
            if label not in preferences:
                preferences.append(label)

        # companions/pace: first non-null wins (a later blank must not erase an
        # already-confirmed fact). day_rhythm: union of selections. notes: last
        # non-empty wins — one coherent block per form submission, never
        # concatenated across messages.
        companions = self.companions or grounded["companions"]
        pace = self.pace or grounded["pace"]
        day_rhythm = list(self.day_rhythm)
        for label in grounded["day_rhythm"]:
            if label not in day_rhythm:
                day_rhythm.append(label)
        notes = grounded["notes"] or self.notes

        return replace(
            self,
            destination=destination,
            duration=duration,
            start_date=start_date,
            stay_end_date=stay_end_date,
            people=people,
            preferences=tuple(preferences),
            companions=companions,
            pace=pace,
            day_rhythm=tuple(day_rhythm),
            notes=notes,
        )

    def with_stay_dates(self, start_date: str, end_date: str) -> TripIntakeState:
        """Apply the frontend's date-range input after validating both edges."""
        clean_start_date = _format_start_date(start_date)
        clean_end_date = _format_start_date(end_date)
        duration = _duration_from_stay_dates(clean_start_date, clean_end_date)
        if not clean_start_date or not clean_end_date or not duration:
            raise ValueError("Ngày kết thúc phải sau ngày bắt đầu và thời gian lưu trú không quá 90 đêm.")
        return replace(
            self,
            start_date=clean_start_date,
            stay_end_date=clean_end_date,
            duration=duration,
        )

    def next_question(
        self,
        destination_names: Sequence[str | DestinationOption] = (),
        language: str = "vi",
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
                return t(
                    "Bạn muốn đi đâu? Hiện mình có dữ liệu cho: {choices}.",
                    language,
                    choices=choices,
                )
            return t("Bạn muốn đi đâu?", language)
        if not self.people:
            return t("Tuyệt vời. Chuyến đi này có bao nhiêu người tham gia?", language)
        if not self.start_date:
            return t("Bạn dự định bắt đầu chuyến đi vào ngày nào?", language)
        if not self.has_explicit_stay_dates:
            return t("Bạn dự định kết thúc chuyến đi vào ngày nào?", language)
        return None

    def tool_arguments(self) -> dict[str, str]:
        if not self.is_complete:
            raise ValueError("Destination, people, start date, and end date are required.")
        return {
            "destination": str(self.destination),
            "duration": str(self.duration),
            "start_date": str(self.start_date),
            "end_date": str(self.end_date),
            "people": str(self.people),
            "preferences": ", ".join(self.preferences),
        }

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for TripState. `asdict` at call sites would
        work too, but a single method here is the one place to fix when a
        field is added."""
        return {
            "destination": self.destination,
            "duration": self.duration,
            "start_date": self.start_date,
            "stay_end_date": self.stay_end_date,
            "people": self.people,
            "preferences": list(self.preferences),
            "companions": self.companions,
            "pace": self.pace,
            "day_rhythm": list(self.day_rhythm),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TripIntakeState:
        """Inverse of `to_dict`. JSON has no tuple type, so `preferences`/
        `day_rhythm` come back as lists — coerced to tuples here, the one
        place that matters."""
        return cls(
            destination=data.get("destination"),
            duration=data.get("duration"),
            start_date=data.get("start_date"),
            stay_end_date=data.get("stay_end_date"),
            people=data.get("people"),
            preferences=tuple(data.get("preferences") or ()),
            companions=data.get("companions"),
            pace=data.get("pace"),
            day_rhythm=tuple(data.get("day_rhythm") or ()),
            notes=data.get("notes") or "",
        )

    def to_travel_state(self) -> TravelState:
        """Read-through view over the canonical state (Phase 3 foundation —
        `TripState.travel_state` doesn't consume this yet). A fact this state
        never captured (destination unset, no preferences chosen) stays
        UNKNOWN; `TripIntakeState` has no "user explicitly opted out" concept
        of its own, so nothing here becomes NOT_APPLICABLE.

        Routed through `apply_patch` rather than constructing `Slot`s
        directly, so every value here passes the same validators a real patch
        would — a value this dataclass could hold but `apply_patch` would
        reject (e.g. `people="0 người"`) is dropped, not silently stored as a
        Slot no patch could ever have produced. Uses `stay_end_date`, never
        the derived `end_date` property: an end date computed from `duration`
        is not something the user actually confirmed (see
        `has_explicit_stay_dates`), so it must not appear as canonical SET."""
        changes: list[dict[str, Any]] = []
        if self.destination:
            changes.append({"path": "destination", "operation": "set", "value": self.destination})
        if self.start_date:
            changes.append({"path": "dates.start", "operation": "set", "value": self.start_date})
        if self.stay_end_date:
            changes.append({"path": "dates.end", "operation": "set", "value": self.stay_end_date})
        people_count = _leading_int(self.people)
        if people_count is not None:
            changes.append({"path": "people", "operation": "set", "value": people_count})
        if self.preferences:
            changes.append({"path": "preferences.themes", "operation": "set", "value": list(self.preferences)})
        if self.companions:
            changes.append({"path": "preferences.companions", "operation": "set", "value": self.companions})
        if self.pace:
            changes.append({"path": "preferences.pace", "operation": "set", "value": self.pace})
        if self.day_rhythm:
            changes.append({"path": "preferences.day_rhythm", "operation": "set", "value": list(self.day_rhythm)})
        if self.notes:
            changes.append({"path": "preferences.notes", "operation": "set", "value": self.notes})
        return apply_patch(TravelState(), changes).state

    @classmethod
    def from_travel_state(cls, state: TravelState) -> TripIntakeState:
        """Inverse of `to_travel_state`. `duration` has no canonical path of
        its own — it is derived from `dates.start`/`dates.end`, the same
        relationship `end_date` already encodes for this class."""

        def _set_value(path: str) -> Any | None:
            slot = state.get(path)
            return slot.value if slot.presence is Presence.SET else None

        destination = _set_value("destination")
        start_date = _set_value("dates.start")
        end_date = _set_value("dates.end")
        people = _set_value("people")
        themes = _set_value("preferences.themes") or ()
        companions = _set_value("preferences.companions")
        pace = _set_value("preferences.pace")
        day_rhythm = _set_value("preferences.day_rhythm") or ()
        notes = _set_value("preferences.notes")

        return cls(
            destination=str(destination) if destination is not None else None,
            duration=_duration_from_stay_dates(start_date, end_date) if start_date and end_date else None,
            start_date=str(start_date) if start_date is not None else None,
            stay_end_date=str(end_date) if end_date is not None else None,
            people=_format_people_count(people) if people is not None else None,
            preferences=tuple(themes),
            companions=str(companions) if companions is not None else None,
            pace=str(pace) if pace is not None else None,
            day_rhythm=tuple(day_rhythm),
            notes=str(notes) if notes is not None else "",
        )


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
    allowed_companions = ", ".join(_COMPANION_LABELS)
    allowed_paces = ", ".join(_PACE_LABELS)
    allowed_day_rhythms = ", ".join(_DAY_RHYTHM_LABELS)

    prompt = f"""You are extracting trip-planning facts from a Vietnamese chat message.
Already confirmed this conversation: {known_summary}
Destinations this system supports, for reference only: {destination_choices or "unknown"}
Today's date in the planning timezone is {date.today().isoformat()}.

Copy the destination the user actually named. Do NOT substitute a different city,
even when the one they named is missing from the list above — "Hội An" must stay
"Hội An", never become "Hà Nội" or "Đà Nẵng". Use null when they named none. A
separate validation step matches your answer against the supported list, so an
unsupported city is handled correctly; silently swapping it sends the user on a
trip to the wrong place.

Return ONLY valid JSON (no markdown fences) matching this schema:
{{
  "destination": "string or null - the destination the user named, copied verbatim",
  "start_date": "YYYY-MM-DD or null - only when the user explicitly provided a trip start date; resolve relative dates using today's date above",
  "end_date": "YYYY-MM-DD or null - only when the user explicitly provided the exclusive trip end/check-out date; it must be after start_date",
  "duration_days": "integer or null - trip length in days (convert weeks/months to days, e.g. '1 tuần' = 7)",
  "people_count": "integer or null - number of travelers (e.g. 'vợ chồng tôi' = 2, 'một mình' = 1)",
  "preference_labels": "array of strings - extracts the user's explicit preferences or requirements (e.g. 'ẩm thực', 'Spa', 'bể bơi', 'yên tĩnh'). Can include any unstructured request.",
  "companions": "string or null - exactly one of these exact strings: {allowed_companions} (or null when none is stated)",
  "pace": "string or null - exactly one of these exact strings: {allowed_paces} (or null when none is stated)",
  "day_rhythm": "array of zero or more of these exact strings only: {allowed_day_rhythms}",
  "notes": "string or empty string - the user's free-text other needs / requests, copied verbatim (truncate to 1000 characters)",
  "changed_fields": "array containing only destination, duration, start_date, people, preferences when the user explicitly asks to replace that already-confirmed field"
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
        content = response_text(response).strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        parsed = json.loads(content.strip())
        print(f"DEBUG LLM EXTRACTED FACTS: {parsed}", flush=True)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
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

    def _closed_singleton(allowed: Sequence[str], value: Any) -> str | None:
        if value is None:
            return None
        candidate = str(value).strip()
        return candidate if candidate in allowed else None

    raw_rhythms = raw.get("day_rhythm")
    rhythm_set = {str(item).strip() for item in raw_rhythms} if isinstance(raw_rhythms, list) else set()
    raw_notes = raw.get("notes")
    notes = str(raw_notes).strip()[:1000] if raw_notes is not None else ""

    return {
        "destination": _match_known_destination(str(raw.get("destination") or "").strip(), destination_names),
        "duration": _format_duration_days(raw.get("duration_days")),
        "start_date": _format_start_date(raw.get("start_date")),
        "end_date": _format_start_date(raw.get("end_date")),
        "people": _format_people_count(raw.get("people_count")),
        "preference_labels": tuple(label for label in _PREFERENCE_LABELS if label in label_set),
        "companions": _closed_singleton(_COMPANION_LABELS, raw.get("companions")),
        "pace": _closed_singleton(_PACE_LABELS, raw.get("pace")),
        "day_rhythm": tuple(label for label in _DAY_RHYTHM_LABELS if label in rhythm_set),
        "notes": notes,
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


def _format_start_date(value: Any) -> str | None:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


def _format_people_count(value: Any) -> str | None:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if not 0 < count <= 50:
        return None
    return f"{count} người"


def _leading_int(value: str | None) -> int | None:
    """Extract the leading integer from a formatted count string ("2 người"
    -> 2), the same convention `end_date` already uses for `duration`."""
    if not value:
        return None
    try:
        return int(value.split(maxsplit=1)[0])
    except (TypeError, ValueError):
        return None


def _duration_from_stay_dates(start_date: str | None, end_date: str | None) -> str | None:
    """Return the number of nights for an exclusive check-out date."""
    try:
        nights = (date.fromisoformat(str(end_date)) - date.fromisoformat(str(start_date))).days
    except (TypeError, ValueError):
        return None
    return _format_duration_days(nights)


def _contains_phrase(normalized_text: str, normalized_phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", normalized_text))


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
    return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()
