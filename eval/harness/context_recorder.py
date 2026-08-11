"""Captures every Supabase RPC result during a chat turn by wrapping
supabase_search._execute_rpc for the duration of a `with` block.

_execute_rpc is the single chokepoint every hotel and attraction RPC passes
through (backend/src/services/supabase_search.py:100), so wrapping it
captures the whole retrieved-context set for a turn without touching
production code. All call sites reference the bare module-level name inside
the same module, so replacing the module attribute reaches them (verified:
they resolve `_execute_rpc` at call time, not at import time).
"""

import contextlib

from src.services import supabase_search


@contextlib.contextmanager
def record_contexts():
    """Yields a list that fills with every RPC result row during the block.

    Restoration in `finally` is not optional - a leaked patch would corrupt
    every later call in the same process, eval or otherwise.
    """
    captured: list[dict] = []
    original = supabase_search._execute_rpc

    def recording(rpc_name: str, params: dict) -> list:
        rows = original(rpc_name, params)
        captured.extend(rows)
        return rows

    supabase_search._execute_rpc = recording
    try:
        yield captured
    finally:
        supabase_search._execute_rpc = original
