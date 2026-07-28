import os
from typing import Any, Dict

from destination_geo import resolve_location_context
from osm_pipeline import get_or_create_destination, load_attractions_to_db


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


def load_records_to_supabase_task(records_task_id: str, records_key: str, **kwargs: Any) -> str:
    records = kwargs["ti"].xcom_pull(task_ids=records_task_id, key=records_key)
    if not records:
        raise ValueError("No geographically valid attraction records were produced.")
    
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
        
    supabase: Client = create_client(supabase_url, supabase_key)
    
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

