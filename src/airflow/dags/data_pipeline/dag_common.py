import os
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor

from destination_geo import resolve_location_context
from hotel_pipeline import _HOTEL_COLUMNS
from osm_pipeline import get_or_create_destination, get_vietnam_region, load_attractions_to_db


DB_KWARGS = {
    "dbname": os.getenv("VSF_DB_NAME", "vsf_database"),
    "user": os.getenv("VSF_DB_USER", "airflow"),
    "password": os.getenv("AIRFLOW_DB_PASSWORD", "airflow"),
    "host": os.getenv("VSF_DB_HOST", "postgres"),
    "port": os.getenv("VSF_DB_PORT", "5432"),
}


def optional_location_coords_param_kwargs() -> Dict[str, Any]:
    return {
        "default": None,
        "type": ["null", "string"],
        "description": (
            "Optional latitude,longitude center. Leave empty to use the "
            "destination's administrative boundary."
        ),
    }


def prepare_destination_task(**kwargs: Any) -> Dict[str, Any]:
    params = kwargs.get("params") or {}
    destination_name = str(params.get("destination_name") or "").strip()
    if not destination_name:
        raise ValueError("destination_name is required.")
    location_context = resolve_location_context(
        destination_name,
        str(params.get("location_coords") or ""),
        int(params.get("radius_meters") or 20_000),
    )
    destination_id = get_or_create_destination(
        destination_name,
        location_context["destination_coordinates"],
        DB_KWARGS,
    )
    payload = {
        "destination_name": destination_name,
        "destination_id": destination_id,
        "location_context": location_context,
    }
    kwargs["ti"].xcom_push(key="destination", value=payload)
    return payload


def destination_from_xcom(source_task_id: str, **kwargs: Any) -> Dict[str, Any]:
    destination = kwargs["ti"].xcom_pull(
        task_ids=source_task_id,
        key="destination",
    )
    if not destination:
        raise ValueError("Destination setup was not found in XCom.")
    return destination


def load_records_task(records_task_id: str, records_key: str, **kwargs: Any) -> str:
    records = kwargs["ti"].xcom_pull(task_ids=records_task_id, key=records_key)
    if not records:
        raise ValueError("No geographically valid attraction records were produced.")
    load_attractions_to_db(records, DB_KWARGS)
    return f"Loaded {len(records)} attractions into PostgreSQL"


def _create_supabase_client():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        from supabase import create_client, Client
    except ImportError:
        raise ImportError("Missing supabase library.")

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment variables.")

    return create_client(supabase_url, supabase_key)


def load_records_to_supabase_task(records_task_id: str, records_key: str, **kwargs: Any) -> str:
    records = kwargs["ti"].xcom_pull(task_ids=records_task_id, key=records_key)
    if not records:
        raise ValueError("No geographically valid attraction records were produced.")

    supabase = _create_supabase_client()

    allowed_keys = {
        "id", "destination_id", "name", "description", "category", "is_tour",
        "estimated_duration_minutes", "opening_time", "closing_time", "departure_schedule",
        "ticket_price_adult", "ticket_price_child", "rating", "review_count",
        "coordinates", "images"
    }

    sanitized_data = []
    for record in records:
        sanitized = {k: v for k, v in record.items() if k in allowed_keys}
        sanitized_data.append(sanitized)

    batch_size = 100
    for i in range(0, len(sanitized_data), batch_size):
        batch = sanitized_data[i:i+batch_size]
        supabase.table("attractions").upsert(batch).execute()

    return f"Loaded {len(records)} attractions into Supabase"


def _serialize_value(value: Any) -> Any:
    """JSON-safe coercion for Postgres row values read back via psycopg2
    (hotel_pipeline normalizes scraped_at/price_check_*_date to real
    date/datetime objects, which postgrest-py's JSON encoder rejects)."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


# Same columns local Postgres's `hotels` table has (hotel_pipeline._HOTEL_COLUMNS).
# `id` is deliberately excluded — Supabase assigns its own primary key,
# distinct from the local Postgres row id.
_HOTEL_SUPABASE_ALLOWED_KEYS = set(_HOTEL_COLUMNS)


def _resolve_supabase_destination_ids(
    supabase, destination_names: List[Optional[str]]
) -> Dict[str, str]:
    """Get-or-create by `name` against Supabase's own `destinations` table.
    Local Postgres's `destinations.id` (written by `get_or_create_destination`
    during `load_hotels_to_db`) is a *different* UUID space from Supabase's —
    forwarding it verbatim trips `hotels_destination_id_fkey`. `name` is the
    only key both stores agree on.

    Missing names are upserted as a single batch on the `name` unique
    constraint (not looped one-by-one) — safe against a concurrent DAG run
    or the attractions path creating the same name between the read and the
    write, and matching `get_or_create_destination`'s local-Postgres columns
    (region) rather than a bare name-only row."""
    unique_names = sorted({n for n in destination_names if n})
    if not unique_names:
        return {}

    existing = (
        supabase.table("destinations").select("id,name").in_("name", unique_names).execute()
    )
    name_to_id = {row["name"]: row["id"] for row in existing.data or []}

    missing_names = [n for n in unique_names if n not in name_to_id]
    if missing_names:
        upserted = (
            supabase.table("destinations")
            .upsert(
                [{"name": n, "region": get_vietnam_region(n)} for n in missing_names],
                on_conflict="name",
            )
            .execute()
        )
        for row in upserted.data or []:
            name_to_id[row["name"]] = row["id"]

    unresolved = [n for n in unique_names if n not in name_to_id]
    if unresolved:
        raise ValueError(
            f"Could not resolve or create Supabase destinations for: {unresolved}"
        )

    return name_to_id


def load_hotels_to_supabase_task(
    records_task_id: str, records_key: str, **kwargs: Any
) -> str:
    """Reads back the hotel rows `load_to_postgresql` just upserted (by natural
    key) and upserts them into Supabase, making Supabase authoritative for
    hotels per the 2026-07-27 user decision. `destination_id` is re-resolved
    against Supabase's own `destinations` table by name (see
    `_resolve_supabase_destination_ids`) rather than forwarded from local
    Postgres. Pushes the `(source_platform, source_hotel_id) ->
    {supabase_hotel_id, destination_id}` identity map Phase 5's Qdrant writer
    needs.
    """
    records = kwargs["ti"].xcom_pull(task_ids=records_task_id, key=records_key)
    if not records:
        raise ValueError("No physically-matched hotel records were produced.")

    destination_name_by_key = {
        (r["source_platform"], r["source_hotel_id"]): r.get("destination_name")
        for r in records
    }
    pairs = sorted(destination_name_by_key.keys())

    conn = psycopg2.connect(**DB_KWARGS)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT * FROM hotels WHERE (source_platform, source_hotel_id) IN %s",
            (tuple(pairs),),
        )
        local_rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    if not local_rows:
        raise ValueError(
            "No matching rows found in local Postgres hotels table after load_to_postgresql; "
            "cannot sync to Supabase."
        )

    supabase = _create_supabase_client()

    destination_names = [
        destination_name_by_key.get((row["source_platform"], row["source_hotel_id"]))
        for row in local_rows
    ]
    supabase_destination_id_by_name = _resolve_supabase_destination_ids(
        supabase, destination_names
    )

    sanitized_batch: List[Dict[str, Any]] = []
    for row in local_rows:
        sanitized = {
            k: _serialize_value(v)
            for k, v in row.items()
            if k in _HOTEL_SUPABASE_ALLOWED_KEYS
        }
        destination_name = destination_name_by_key.get(
            (row["source_platform"], row["source_hotel_id"])
        )
        sanitized["destination_id"] = supabase_destination_id_by_name.get(destination_name)
        sanitized_batch.append(sanitized)

    batch_size = 100
    upserted_rows: List[Dict[str, Any]] = []
    for i in range(0, len(sanitized_batch), batch_size):
        batch = sanitized_batch[i : i + batch_size]
        result = (
            supabase.table("hotels")
            .upsert(batch, on_conflict="source_platform,source_hotel_id")
            .execute()
        )
        upserted_rows.extend(result.data or [])

    identity_map = {
        f"{row['source_platform']}:{row['source_hotel_id']}": {
            "supabase_hotel_id": row["id"],
            "destination_id": row.get("destination_id"),
        }
        for row in upserted_rows
    }
    kwargs["ti"].xcom_push(key="hotel_supabase_identity_map", value=identity_map)
    return f"Loaded {len(upserted_rows)} hotels into Supabase"

