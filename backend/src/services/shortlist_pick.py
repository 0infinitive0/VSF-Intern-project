"""Which card on screen a chat message points at, decided by the model.

The deterministic alternatives this replaces both failed on the long tail.
A keyword-anchored ordinal regex reads "khách sạn số 1" and nothing else --
not "cái rẻ nhất ấy", not "khách sạn Nhật kia", not a typo'd name. A name
matcher adds one more shape and still misses the next one, and every shape
added is another rule that can fire on a sentence that was never a pick
("khách sạn 2 sao" is a filter, "cho 2 người" is a party size).

Matching a sentence to a thing on screen is language understanding, so the
model does it. What the model never does is name the record: it returns a
POSITION in the closed list it was shown, validated here against that
list's length, and the caller maps position to row. That is the same
boundary `trip_edit_planner` draws ("the model is deliberately limited to
describing an edit ... it never selects a database record") and the reason
`qa_node` has no `select_place` tool. Booking the wrong hotel is the most
expensive version of that mistake this product can make.

`None` means "no card", never a guess: the model is told to return null
when the message points at nothing, an out-of-range or unparseable answer
is discarded, and a provider failure returns None too. The caller asks the
user rather than acting on an unresolved pick.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.services.llm import get_fast_llm

logger = logging.getLogger(__name__)

#: Cards beyond this are not offered to the model. The shortlist a user is
#: choosing from is short by construction (`_HOTEL_DISPLAY_LIMIT`); this is a
#: prompt-size backstop for a merged list that grew across several searches.
_MAX_CANDIDATES = 30


class ShortlistPick(BaseModel):
    """`position` is 1-based into the list the model was shown, or null."""

    position: int | None = Field(default=None)
    reasoning: str = ""  # audit only — never shown to the user


_SYSTEM_PROMPT = """You are matching one chat message against the numbered cards currently on the user's screen.

Return the POSITION of the single card the user is pointing at, or null.

Return null when:
- the message names no card ("tìm khách sạn khác", "giá bao nhiêu?", a greeting);
- it describes a FILTER rather than a choice ("khách sạn 5 sao", "dưới 1 triệu") — a filter is a new search, not a pick;
- several cards fit equally well and nothing separates them.

A number in the message is only a position when the user means the printed number. "khách sạn số 2" is position 2; "khách sạn 2 sao" is a star rating and "cho 2 người" is a party size — both are null.

Match on whatever the user actually used: the printed number, the name (with or without Vietnamese diacritics, possibly misspelled or shortened), or a description that fits exactly one card ("cái rẻ nhất", "cái gần trung tâm nhất").

reasoning is one short sentence for an audit log, never shown to the user."""


def _card_line(position: int, option: dict[str, Any]) -> str:
    parts = [f"{position}. {str(option.get('name') or '').strip()}"]
    star = option.get("star_rating")
    if star:
        parts.append(f"{star} sao")
    price = option.get("average_nightly_price") or option.get("lowest_price")
    if price:
        parts.append(f"{int(float(price)):,} VND/đêm".replace(",", "."))
    score = option.get("review_score")
    if score:
        parts.append(f"điểm đánh giá {score}")
    area = option.get("area_name") or option.get("address")
    if area:
        parts.append(str(area))
    return " — ".join(parts)


def pick_shown_option(message: str, options: list[dict[str, Any]]) -> int | None:
    """1-based position of the card *message* points at, or None.

    Never raises: a provider outage is an unresolved pick, not a failed
    turn, and the caller already has to handle "couldn't tell which one".
    """
    if not message or not message.strip():
        return None
    candidates = [option for option in options if isinstance(option, dict)][:_MAX_CANDIDATES]
    if not candidates:
        return None

    cards = "\n".join(_card_line(position, option) for position, option in enumerate(candidates, start=1))
    prompt = f'{_SYSTEM_PROMPT}\n\nCards on screen:\n{cards}\n\nMessage: "{message.strip()}"'

    try:
        llm = get_fast_llm(temperature=0)
        pick = llm.with_structured_output(ShortlistPick).invoke(prompt)
    except Exception:
        logger.exception("pick_shown_option: model call failed; treating as unresolved")
        return None

    position = getattr(pick, "position", None)
    if not isinstance(position, int) or isinstance(position, bool):
        return None
    # Out of range is discarded, not clamped: "số 12" against 9 cards means
    # the user is looking at something we are not, and the nearest card is
    # not a better guess than asking.
    if not 1 <= position <= len(candidates):
        return None
    return position
