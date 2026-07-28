"""Supabase client factory and paginated fetch, shared by ingest scripts.

The service_role key bypasses row-level security, so it is kept out of
`src.config.Settings` (loaded by the public-facing FastAPI backend) and typed
`SecretStr` here so it never lands in a traceback in plain text."""

import os
from functools import lru_cache

from pydantic import SecretStr
from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_ingest_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = SecretStr(os.environ.get("SUPABASE_SERVICE_KEY", ""))
    if not url or not key.get_secret_value():
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment.")
    return create_client(url, key.get_secret_value())


def fetch_all(table: str, columns: str, page_size: int = 1000) -> list[dict]:
    """Page through PostgREST's row cap via `.range()` until a short page
    returns — a bare `.select()` silently truncates at `page_size` rows."""
    client = get_ingest_supabase_client()
    rows: list[dict] = []
    start = 0
    while True:
        page = client.table(table).select(columns).range(start, start + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows
