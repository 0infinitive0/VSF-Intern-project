"""The hotel cards currently on the user's screen, for the read-only Q&A tools.

`query_hotel` and `query_hotel_rooms` both used to read
`state["hotel_options"]` -- a key `TravelGraphState` has never defined. The
lookup therefore returned `None` on every single call, and both tools
answered every question with "SYSTEM ERROR: Không có danh sách khách sạn nào
hiện đang được chọn", which the model then relayed as "mình không thấy danh
sách khách sạn hiện tại" while the cards sat visible on screen beside it.

`previous_hotel_options` is the right source and the only durable one:
`hotel_node` writes the merged card list there after every successful search
(`nodes/hotel_node.py`), and unlike `task_results` it deliberately survives
`load_context`'s per-turn reset (`graph/state.py`). A question turn never
runs `hotel_node`, so `task_results` is empty by the time these tools run --
reading it instead would reintroduce the same "no list" failure one turn
later, which is exactly the trap the original code fell into.

The `task_results` fallback covers the one turn where both are populated
(the search turn itself), so a question asked in the same breath as a search
still resolves.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.services.amenity_catalog import all_approved_amenities

logger = logging.getLogger(__name__)

# "khách sạn số 1", "ks 2", "hotel #3", "cái số 1", "option 2" -- a card
# named by the number printed on it. The keyword prefix is required: without
# it "trong bán kính 3 km" and "khách sạn 4 sao" both read as ordinal 3/4,
# and the `sao|star` lookahead rejects the star rating even when the keyword
# is there ("khách sạn 5 sao" is a filter, not a pick).
_ORDINAL_PATTERN = re.compile(
    r"(?:khách\s*sạn|khach\s*san|ks|hotel|option|lựa\s*chọn|lua\s*chon|cái|cai|số|so|#)"
    r"\s*(?:số|so|#)?\s*(\d{1,2})\b(?!\s*(?:sao|star))",
    re.IGNORECASE,
)


def hotel_option_at_ordinal(options: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    """The shown hotel card a message points at by its printed number.

    Positional, because position IS the number the user sees: the cards are
    numbered by enumerating this same list in this same order
    (`to_hotel_options_payload`), so `options[n - 1]` and "khách sạn số n"
    are the same card by construction — no `index` key needed on the raw
    dicts, which do not all carry one.

    Returns None when the message names no number, or names one past the end
    of the shortlist ("số 12" against 9 cards) — the caller asks rather than
    silently answering about a different hotel.
    """
    match = _ORDINAL_PATTERN.search(message or "")
    if not match:
        return None
    ordinal = int(match.group(1))
    if 1 <= ordinal <= len(options):
        return options[ordinal - 1]
    return None


def shown_hotel_options(state: Any) -> list[dict[str, Any]]:
    """Every hotel card the user has been shown, newest search merged in.

    Returns `[]` when no search has produced cards yet -- the caller turns
    that into a user-facing "no list yet" reply, which is honest at that
    point in the conversation and is NOT the failure described above.
    """
    if state is None:
        return []
    get = getattr(state, "get", None)
    if get is None:
        return []

    previous = get("previous_hotel_options")
    if isinstance(previous, list) and previous:
        return [option for option in previous if isinstance(option, dict)]

    # Same turn as the search: hotel_node's result is still in task_results
    # and `previous_hotel_options` may not have been merged back yet.
    task_results = get("task_results") or []
    if isinstance(task_results, list):
        for result in reversed(task_results):
            if not isinstance(result, dict):
                continue
            search_result = result.get("hotel_search_result")
            if isinstance(search_result, dict):
                options = search_result.get("options")
                if isinstance(options, list) and options:
                    return [option for option in options if isinstance(option, dict)]
    return []


def labelled_amenities(tags: Any, *, language: str = "vi") -> list[str]:
    """Canonical amenity IDs turned into the labels the user already sees.

    Hotel cards store canonical IDs (`swimming_pool`, `hot_spring_bath`).
    Handing those to the model verbatim gets them read straight back out to
    the user -- "khách sạn số 1 có bể bơi (swimming_pool), onsen
    (hot_spring_bath)" -- which is the same raw-ID leak already fixed once
    on the hotel-search reply path, arriving instead through the Q&A tools.
    Resolving here means the model never sees an ID it could echo.

    Unknown IDs fall through unchanged rather than being dropped: an amenity
    missing from the catalog is still a real fact about the hotel, and a
    slightly ugly label beats silently withholding it. A catalog lookup
    failure degrades the same way, for the same reason.
    """
    if not isinstance(tags, (list, tuple)):
        return []
    raw = [str(tag).strip() for tag in tags if isinstance(tag, str) and str(tag).strip()]
    if not raw:
        return []
    try:
        entries = all_approved_amenities()
    except Exception:  # noqa: BLE001 - a label lookup must never fail a question
        logger.warning("labelled_amenities: catalog unavailable, using raw ids", exc_info=True)
        return raw
    prefer_english = language.startswith("en")
    catalog = {
        entry.id: ((entry.label_en or entry.label) if prefer_english else (entry.label or entry.label_en))
        for entry in entries
    }
    return [catalog.get(tag) or tag for tag in raw]


def without_unknowns(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop keys whose value is unknown, so the model has no `null` to quote.

    The Q&A tools serialize their result straight into the prompt, and the
    model reports the shape it is handed. Given `max_guests: null` it wrote
    "nhiều phòng có trường max_guests = null" to a customer -- a database
    column name and a JSON literal, in a sentence meant for someone choosing
    a family room. Omitting the key removes the vocabulary entirely; the
    tool's preamble tells the model that absent means unknown.

    Empty lists go too: "meals included: []" reads as a fact about the hotel
    when it only means nobody recorded one. Zero and False are kept -- those
    are real answers, not missing ones.
    """
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None or value == "" or (isinstance(value, (list, tuple, dict)) and not value):
            continue
        cleaned[key] = value
    return cleaned
