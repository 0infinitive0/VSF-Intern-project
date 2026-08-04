import os
import sys
import json
from datetime import datetime

from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.exceptions import AirflowSkipException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hotel_nearby_pipeline import (
    crawl_hotel_surroundings,
    validate_hotel_surrounding_seeds,
    resolve_hotel_surrounding_seeds
)
from google_maps_pipeline import (
    normalize_google_maps_candidates,
    validate_clean_google_maps_candidates,
)
from attraction_utils import deduplicate_attractions, stable_attraction_id


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "do_xcom_push": True,
    "retries": 1,
}

@task
def fetch_pending_hotels_task():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import requests
    from airflow.models import Variable
    
    supabase_url = os.environ.get("SUPABASE_URL") or Variable.get("SUPABASE_URL", default_var=None)
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or Variable.get("SUPABASE_SERVICE_KEY", default_var=None)
    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or variables.")
        
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    
    # Fetch all hotels (paginate if there are more than 1000)
    all_hotels = []
    limit = 1000
    offset = 0
    while True:
        url = f"{supabase_url}/rest/v1/hotels?select=*&limit={limit}&offset={offset}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        all_hotels.extend(data)
        if len(data) < limit:
            break
        offset += limit

    processed_ids = set(Variable.get("hotel_pipeline_processed_ids", default_var=[], deserialize_json=True))
    
    pending_hotels = [h for h in all_hotels if h.get("id") not in processed_ids and h.get("nearby_attractions")]
    
    # Batch limit to 30 per DAG run so it doesn't run forever and block other DAGs
    batch = pending_hotels[:30]
    print(f"Total pending hotels: {len(pending_hotels)}. Processing a batch of {len(batch)}.")
    
    return batch


@task(max_active_tis_per_dag=3)
def process_hotel_task(hotel):
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    import requests
    from airflow.models import Variable
    supabase_url = os.environ.get("SUPABASE_URL") or Variable.get("SUPABASE_URL", default_var=None)
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY") or Variable.get("SUPABASE_SERVICE_KEY", default_var=None)
    if not supabase_url or not supabase_key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment or variables.")
    
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json"
    }
    
    dest_url = f"{supabase_url}/rest/v1/destinations?select=id&limit=1"
    dest_response = requests.get(dest_url, headers=headers)
    dest_response.raise_for_status()
    dest_data = dest_response.json()
    dest_id = dest_data[0]["id"] if dest_data else "00000000-0000-0000-0000-000000000000"

    hotel_id = hotel.get('id')
    hotel_name = hotel.get('name')
    print(f"Starting hotel: {hotel_name} (ID: {hotel_id})")
    
    # Map id to hotel_id for compatibility with existing pipeline
    hotel["hotel_id"] = hotel_id
    hotel["hotel_name"] = hotel_name
    coords = hotel.get("coordinates")
    if coords and isinstance(coords, str) and "," in coords:
        try:
            parts = coords.split(",")
            hotel["hotel_latitude"] = float(parts[0].strip())
            hotel["hotel_longitude"] = float(parts[1].strip())
        except ValueError:
            hotel["hotel_latitude"] = 10.762622
            hotel["hotel_longitude"] = 106.660172
    else:
        hotel["hotel_latitude"] = hotel.get("latitude") or hotel.get("location_latitude") or 10.762622
        hotel["hotel_longitude"] = hotel.get("longitude") or hotel.get("location_longitude") or 106.660172
    
    seeds = crawl_hotel_surroundings([hotel], 8, 1)
    if not seeds:
        print(f"No seeds found for hotel {hotel_name}")
        return hotel_id

    destination = {
        "location_context": {
            "mode": "radius",
            "latitude": hotel["hotel_latitude"],
            "longitude": hotel["hotel_longitude"],
            "radius_meters": 10000000
        },
        "destination_name": "Vietnam"
    }
    
    clean_seeds = validate_hotel_surrounding_seeds(seeds, destination["location_context"])
    if not clean_seeds:
        print(f"No valid seeds for hotel {hotel_name}")
        return hotel_id

    resolved = resolve_hotel_surrounding_seeds(
        clean_seeds,
        destination["location_context"],
        5000,
        destination["destination_name"],
        3
    )
    
    validated = validate_clean_google_maps_candidates(resolved, destination["location_context"])
    
    records = normalize_google_maps_candidates(
        validated,
        dest_id,
        destination["destination_name"],
        max(len(validated), 1),
        fast_poc_mode=False
    )
    
    final_records = deduplicate_attractions(records)
    
    for r in final_records:
        r["id"] = stable_attraction_id(r)
        r["destination_id"] = dest_id

    allowed_keys = {
        "id", "destination_id", "name", "description", "category", "is_tour",
        "estimated_duration_minutes", "opening_time", "closing_time", "departure_schedule",
        "ticket_price_adult", "ticket_price_child", "rating", "review_count",
        "coordinates", "images"
    }
    
    sanitized_data = []
    for record in final_records:
        sanitized = {k: v for k, v in record.items() if k in allowed_keys}
        sanitized_data.append(sanitized)
        
    if sanitized_data:
        headers["Prefer"] = "return=minimal, resolution=merge-duplicates"
        upsert_url = f"{supabase_url}/rest/v1/attractions"
        upsert_response = requests.post(upsert_url, headers=headers, json=sanitized_data)
        upsert_response.raise_for_status()
        print(f"Successfully inserted {len(sanitized_data)} attractions for {hotel_name}!")
    else:
        print(f"No attractions to insert for {hotel_name}.")

    return hotel_id

@task
def update_state_task(successful_hotel_ids):
    # filter out Nones if any tasks failed or didn't return properly
    successful_hotel_ids = [hid for hid in successful_hotel_ids if hid]
    
    if not successful_hotel_ids:
        print("No successful hotels in this batch.")
        return
        
    processed_ids = Variable.get("hotel_pipeline_processed_ids", default_var=[], deserialize_json=True)
    
    # Extend and ensure uniqueness
    new_processed_ids = list(set(processed_ids + successful_hotel_ids))
    
    Variable.set("hotel_pipeline_processed_ids", new_processed_ids, serialize_json=True)
    print(f"Successfully added {len(successful_hotel_ids)} hotels to the processed state variable.")


with DAG(
    dag_id="hotel_nearby_attractions_pipeline_supabase",
    default_args=DEFAULT_ARGS,
    description="Batch processing DAG for fetching nearby attractions for hotels using parallel tasks.",
    schedule=None,  # Trigger manually for batches
    start_date=datetime(2026, 7, 24),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "google-maps", "hotel", "attractions", "supabase"],
) as dag:
    
    pending_hotels = fetch_pending_hotels_task()
    
    # Dynamic task mapping over the pending hotels list
    # max_active_tis_per_dag=3 enforces that only 3 process_hotel tasks run concurrently
    processed_hotel_ids = process_hotel_task.expand(hotel=pending_hotels)
    
    state_update = update_state_task(processed_hotel_ids)

    @task
    def check_next_batch_task(batch):
        # If we got a full batch, there are likely more hotels remaining
        if len(batch) >= 30:
            print("Full batch processed. Triggering the next run...")
            return True
        else:
            raise AirflowSkipException("No more full batches left. Pipeline complete!")

    check_next = check_next_batch_task(pending_hotels)
    
    trigger_next = TriggerDagRunOperator(
        task_id="trigger_next_batch",
        trigger_dag_id="hotel_nearby_attractions_pipeline_supabase",
        conf={},
    )
    
    state_update >> check_next >> trigger_next
