"""Guards `eval/harness/context_recorder.py`'s founding assumption: every
Supabase RPC name `backend/src` calls is accounted for, so a new vector-search
path shows up as a red test here instead of a silently wrong faithfulness
score (see plans/260820-1106-eval-harness-graph-cutover-restore/phase-04-*).

`context_recorder.py` intercepts every `Client.rpc(fn, ...)` call and records
the ones whose name starts with `match_` as retrieved context. This test
re-enumerates every RPC name literal `backend/src` actually passes — directly
via `.rpc(...)`, or through the two dynamic-name wrappers that exist today
(`supabase_search._execute_rpc`, `booking_service._call`) — and fails if one
appears that isn't in the list below, so a reviewer has to make the "is this
a vector search that needs capturing?" call explicitly rather than by accident.
"""

import re
from pathlib import Path

_BACKEND_SRC = Path(__file__).resolve().parents[1] / "src"

#: Every RPC name `backend/src` calls today (verified 2026-08-20 by
#: re-running the scan below). `match_*` ones are vector searches
#: `context_recorder.py` must capture; the rest are writes/lookups it must
#: NOT capture (over-broad capture would corrupt faithfulness scoring the
#: other way).
_KNOWN_RPC_NAMES = {
    # vector search -- captured by context_recorder.py
    "match_hotels_with_rooms",
    "match_attractions",
    "match_itineraries",
    # not vector search -- must NOT be captured
    "get_room_availability",
    "persist_session_checkpoint",
    "persist_itinerary_bundle",
    "finalize_itinerary",
    "update_itinerary_embedding",
    "create_booking_reservation",
    "confirm_booking_reservation",
    "cancel_booking",
    "next_manual_hotel_source_id",
    "next_manual_room_source_id",
    "admin_upsert_room_prices",
}

#: Call patterns whose first argument is an RPC name: the direct
#: `client.rpc("name", ...)` call, and the two functions in `backend/src`
#: that take `rpc_name` as a parameter and forward it to `.rpc(...)`
#: themselves (`supabase_search._execute_rpc`, `booking_service._call`) --
#: their OWN call sites pass the literal, not the `.rpc(` line itself.
_CALL_PATTERN = re.compile(r"(?:\.rpc|_execute_rpc|_call)\(\s*[\"']([a-zA-Z_][a-zA-Z0-9_]*)[\"']")


def _rpc_names_in_source() -> set[str]:
    names: set[str] = set()
    for path in _BACKEND_SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        names.update(_CALL_PATTERN.findall(text))
    return names


def test_every_rpc_call_site_is_a_known_name() -> None:
    found = _rpc_names_in_source()
    unrecognised = found - _KNOWN_RPC_NAMES
    assert not unrecognised, (
        f"Unrecognised RPC name(s) {sorted(unrecognised)} found in backend/src. "
        "Decide whether each is a vector search that eval/harness/context_recorder.py "
        "must capture (add to the match_* allow-list there and to _KNOWN_RPC_NAMES "
        "above) or a write/lookup that must stay uncaptured (add to _KNOWN_RPC_NAMES "
        "above only)."
    )


def test_known_rpc_names_are_still_actually_called() -> None:
    """The inverse check: a name that stops appearing means this list rotted
    stale, not that the RPC went away — keep it honest in both directions."""
    found = _rpc_names_in_source()
    missing = _KNOWN_RPC_NAMES - found
    assert not missing, f"RPC name(s) {sorted(missing)} no longer appear in backend/src - remove them from _KNOWN_RPC_NAMES."
