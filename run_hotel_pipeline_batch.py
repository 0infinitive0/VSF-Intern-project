import sys
import os
import json
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath('src/airflow/dags/data_pipeline'))
from hotel_nearby_pipeline import (
    crawl_hotel_surroundings,
    validate_hotel_surrounding_seeds,
    resolve_hotel_surrounding_seeds
)
from google_maps_pipeline import normalize_google_maps_candidates, validate_clean_google_maps_candidates
from attraction_utils import deduplicate_attractions, stable_attraction_id
from dotenv import load_dotenv

STATE_FILE = "pipeline_state.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"processed_hotel_ids": []}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def process_hotel(hotel, supabase, dest_id):
    hotel_id = hotel.get('id')
    hotel_name = hotel.get('name')
    print(f"[Worker] Starting hotel: {hotel_name} (ID: {hotel_id})")
    
    try:
        # map id to hotel_id for compatibility
        hotel["hotel_id"] = hotel_id
        hotel["hotel_name"] = hotel_name
        hotel["hotel_latitude"] = hotel.get("latitude") or hotel.get("location_latitude") or 10.762622
        hotel["hotel_longitude"] = hotel.get("longitude") or hotel.get("location_longitude") or 106.660172
        
        seeds = crawl_hotel_surroundings([hotel], 8, 1)
        if not seeds:
            print(f"[Worker] No seeds found for hotel {hotel_name}")
            return hotel_id, True

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
            print(f"[Worker] No valid seeds for hotel {hotel_name}")
            return hotel_id, True

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
            supabase.table("attractions").upsert(sanitized_data).execute()
            print(f"[Worker] Successfully inserted {len(sanitized_data)} attractions for {hotel_name}!")
        else:
            print(f"[Worker] No attractions to insert for {hotel_name}.")

        return hotel_id, True
    except Exception as e:
        print(f"[Worker] Error processing hotel {hotel_name}: {e}")
        traceback.print_exc()
        return hotel_id, False

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    load_dotenv()
    
    try:
        from supabase import create_client
    except ImportError:
        print("Please install supabase-py")
        return
        
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in .env")
        return
        
    supabase = create_client(supabase_url, supabase_key)
    
    print("Fetching all hotels from Supabase...")
    # Fetch all hotels (paginate if there are more than 1000)
    all_hotels = []
    limit = 1000
    offset = 0
    while True:
        response = supabase.table("hotels").select("*").range(offset, offset + limit - 1).execute()
        data = response.data
        if not data:
            break
        all_hotels.extend(data)
        if len(data) < limit:
            break
        offset += limit
        
    print(f"Total hotels found: {len(all_hotels)}")
    
    state = load_state()
    processed_ids = set(state.get("processed_hotel_ids", []))
    
    # Filter hotels that have nearby_attractions and haven't been processed yet
    pending_hotels = [h for h in all_hotels if h.get("id") not in processed_ids and h.get("nearby_attractions")]
    print(f"Hotels remaining to process: {len(pending_hotels)}")
    
    if not pending_hotels:
        print("All hotels have been processed.")
        return
        
    print("Fetching a valid destination_id from Supabase...")
    dest_response = supabase.table("destinations").select("id").limit(1).execute()
    dest_id = dest_response.data[0]["id"] if dest_response.data else "00000000-0000-0000-0000-000000000000"

    print("Starting batch processing with 3 parallel workers...")
    print("Press Ctrl+C to safely pause after the current batch finishes.")
    
    # We use max_workers=3 as requested by user
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_hotel = {executor.submit(process_hotel, h, supabase, dest_id): h for h in pending_hotels}
            
            for future in as_completed(future_to_hotel):
                hotel = future_to_hotel[future]
                try:
                    hotel_id, success = future.result()
                    if success:
                        state["processed_hotel_ids"].append(hotel_id)
                        save_state(state)
                except Exception as exc:
                    print(f"Hotel {hotel.get('name')} generated an exception: {exc}")
    except KeyboardInterrupt:
        print("\n[!] Gracefully shutting down. Progress has been saved to pipeline_state.json.")
        print("You can resume by running the script again.")
        sys.exit(0)
        
    print("Pipeline completed successfully.")

if __name__ == "__main__":
    main()
