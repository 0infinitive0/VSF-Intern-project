"""Renders retrieved/expected places as stable, human-readable context strings
for the LLM-judged metrics, plus the inverse (pull the ID back out) so the
report can name which place a low score is actually about.

Both sides of a Faithfulness sample - the retrieved contexts and the answer
text being checked against them - are rendered here, through the same
`_fact_line` formatter. An NLI judge compares strings: "950.000đ" in the
answer against "950,000 VND" in the context is a formatting mismatch it can
score as unsupported, so the two renderings must not drift apart. That is
why the answer-side renderer lives next to the context-side one instead of
in `e2e_eval.py`.
"""

import re

_ID_PREFIX_RE = re.compile(r"^\[([0-9a-fA-F-]{36})\]")

# Row keys `match_hotels_with_rooms` actually returns (see
# backend/scripts/migrations/20260820_add_guest_capacity_filter_to_match_hotels_
# with_rooms.sql). Fields the app adds later by hydration - address, area_name,
# amenity labels - are deliberately NOT rendered on either side: they never pass
# through retrieval, so a judge has nothing to verify them against and would score
# every mention of them as unsupported. What retrieval returned is what gets judged.


def _money(value, currency: str | None) -> str | None:
    """Thousands-separated integer amount, or None when there is nothing to show.

    Prices arrive as SQL `numeric` (Decimal) on the context side and as float on
    the response side; both round to the same string here so the judge sees one
    number, not two spellings of it.
    """
    if value is None:
        return None
    try:
        amount = round(float(value))
    except (TypeError, ValueError):
        return None
    return f"{amount:,} {currency or 'VND'}"


def _fact_line(
    *,
    star_rating=None,
    average_nightly_price=None,
    total_stay_price=None,
    stay_night_count=None,
    currency: str | None = None,
) -> str:
    """The shared ' — <fact> — <fact>' tail appended to a hotel on both sides."""
    facts: list[str] = []
    if star_rating is not None:
        facts.append(f"{star_rating:g} sao")
    nightly = _money(average_nightly_price, currency)
    if nightly:
        facts.append(f"{nightly}/đêm")
    total = _money(total_stay_price, currency)
    if total:
        nights = f" cho {stay_night_count} đêm" if stay_night_count else ""
        facts.append(f"tổng {total}{nights}")
    return "".join(f" — {fact}" for fact in facts)


def as_context(place: dict, *, city: str | None = None, detail: bool = False) -> str:
    """Stable, ID-anchored rendering: '[<uuid>] <name>', optionally ', <city>'.

    `city`, when given, must be the place's OWN verified destination (looked up from
    the database, e.g. `retrieval_eval.py`'s `_city_names_for`), never the query's
    target destination assumed onto every result. Neither the hotel/attraction RPC
    rows nor `place` here carry a destination name — without this, an LLM judge
    asked "is this hotel in Nha Trang" has no way to verify location from the
    rendered context at all, and silently defaults to unsure/no regardless of
    whether the result actually is in the right city. Injecting the query's target
    city instead of the place's real one would make a genuine wrong-city result
    read as verified-correct to the judge - the opposite of what this is for.

    `detail` appends the star rating and prices the row carries, for the e2e layer,
    where the answer being judged is a list of hotel cards quoting exactly those
    numbers. Off by default: the retrieval layer's scores were established against
    the bare '[id] name, city' form, and silently widening it would move Layer 1's
    numbers without anyone changing Layer 1. A row without those keys (attractions,
    itineraries) renders identically either way."""
    place_id = place.get("id") or place.get("hotel_id") or place.get("attraction_id") or ""
    name = place.get("name", "")
    suffix = f", {city}" if city else ""
    detail_suffix = (
        _fact_line(
            star_rating=place.get("star_rating"),
            average_nightly_price=place.get("average_nightly_price"),
            total_stay_price=place.get("total_stay_price"),
            stay_night_count=place.get("stay_night_count"),
            currency=place.get("currency"),
        )
        if detail
        else ""
    )
    return f"[{place_id}] {name}{suffix}{detail_suffix}"


def hotel_options_as_answer(reply: str, hotel_options) -> str:
    """The reply text plus the hotel cards it introduces, as one answer string.

    `hotel_node`'s chat text is a caption ("Mình tìm được 5 khách sạn phù hợp") -
    the answer the user actually receives is the `hotel_options` list the client
    renders as cards. Judging the caption alone asks the judge to verify a bare
    count against a context set that has no counts in it: structurally 0.0 no
    matter how honest the agent was, while a wrong price on a card - the failure
    worth catching - goes unseen because it was never shown to the judge.

    Returns `reply` unchanged when there are no options, so non-hotel turns keep
    the exact text they had before.
    """
    if not hotel_options:
        return reply
    lines = [reply]
    for index, option in enumerate(hotel_options, start=1):
        facts = _fact_line(
            star_rating=option.star_rating,
            average_nightly_price=option.average_nightly_price,
            total_stay_price=option.total_stay_price,
            stay_night_count=option.stay_night_count,
            currency=option.currency,
        )
        lines.append(f"{index}. {option.name}{facts}")
    return "\n".join(lines)


def context_id(context: str) -> str | None:
    """Inverse of as_context: pull the UUID back out of a rendered context string."""
    match = _ID_PREFIX_RE.match(context)
    return match.group(1) if match else None
