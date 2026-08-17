"""Shared Supabase client accessor.

Thin re-export of `supabase_search.get_supabase_client` -- unblocks
`src.services.place_search`'s import (it expected a `src.clients` package
that didn't exist yet, breaking every route that transitively imports
`build_graph`). Not a new implementation: `supabase_search.get_supabase_client`
stays the single `@lru_cache`d connection factory; this module only gives it
a second import path under the name the newer code expects.
"""

from __future__ import annotations

from src.services.supabase_search import get_supabase_client

__all__ = ["get_supabase_client"]
