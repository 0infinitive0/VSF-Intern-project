"""Renders retrieved/expected places as stable, human-readable context strings
for the LLM-judged metrics, plus the inverse (pull the ID back out) so the
report can name which place a low score is actually about.
"""

import re

_ID_PREFIX_RE = re.compile(r"^\[([0-9a-fA-F-]{36})\]")


def as_context(place: dict) -> str:
    """Stable, ID-anchored rendering: '[<uuid>] <name>'."""
    place_id = place.get("id") or place.get("hotel_id") or place.get("attraction_id") or ""
    return f"[{place_id}] {place.get('name', '')}"


def context_id(context: str) -> str | None:
    """Inverse of as_context: pull the UUID back out of a rendered context string."""
    match = _ID_PREFIX_RE.match(context)
    return match.group(1) if match else None
