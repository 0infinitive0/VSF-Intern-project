"""Captures every Supabase vector-search RPC result during a chat turn.

Used to wrap `supabase_search._execute_rpc` alone, on the established fact
that it was "the single interception point for capturing retrieved contexts
during an e2e turn" (the original harness plan, 2026-08-07). That stopped
being true on 2026-08-20: `itinerary_store.py` calls
`self._client.rpc("match_itineraries", params)` directly, invisible to a
patch on `_execute_rpc` (plan
260820-1106-eval-harness-graph-cutover-restore, phase 4).

`get_supabase_client()` (`supabase_search.py`) returns a brand-new `Client`
instance on every call rather than a cached singleton, and `ItineraryStore`
builds its own instance at construction time — the two never share an
object, so patching an instance's `.rpc` would miss whichever side didn't
happen to hold that instance. Patching `Client.rpc` on the class instead
reaches every instance, present and future, in one place — actually a
stronger version of "the single interception point" than the original plan
had, since it no longer depends on which factory function happened to build
the client.

Filtered to an explicit `match_*` allow-list, not a deny-list: a new WRITE
rpc silently entering the recorded context set (and corrupting faithfulness
scoring in the opposite direction) is worse than a new SEARCH rpc being
briefly missed until `test_rpc_call_sites_known.py` catches it.
"""

import contextlib

from supabase import Client


def _is_vector_search(rpc_name: str) -> bool:
    return rpc_name.startswith("match_")


@contextlib.contextmanager
def record_contexts():
    """Yields a list that fills with every vector-search RPC result row
    during the block.

    Restoration in `finally` is not optional - a leaked patch would corrupt
    every later call in the same process, eval or otherwise.
    """
    captured: list[dict] = []
    original_rpc = Client.rpc

    def recording_rpc(self, fn: str, params: dict | None = None, *args, **kwargs):
        builder = original_rpc(self, fn, params, *args, **kwargs)
        if not _is_vector_search(fn):
            return builder

        original_execute = builder.execute

        def recording_execute(*a, **kw):
            response = original_execute(*a, **kw)
            captured.extend(response.data or [])
            return response

        builder.execute = recording_execute
        return builder

    Client.rpc = recording_rpc
    try:
        yield captured
    finally:
        Client.rpc = original_rpc
