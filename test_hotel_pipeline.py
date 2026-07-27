import sys
import os
import json

sys.path.insert(0, os.path.abspath('src/airflow/dags/data_pipeline'))
from hotel_nearby_pipeline import (
    crawl_hotel_surroundings,
    validate_hotel_surrounding_seeds,
    resolve_hotel_surrounding_seeds
)
from dotenv import load_dotenv

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
    supabase = create_client(supabase_url, supabase_key)
    
    print("Fetching 1 hotel from Supabase...")
    response = supabase.table("hotels").select("*").limit(5).execute()
    hotels = response.data
    
    test_hotel = None
    for h in hotels:
        if h.get("nearby_attractions"):
            test_hotel = [h]
            break
            
    if not test_hotel:
        print("No hotels with nearby_attractions found.")
        return
        
    print(f"Testing with hotel: {test_hotel[0].get('name')} (ID: {test_hotel[0].get('id')})")
    # map id to hotel_id for compatibility
    test_hotel[0]["hotel_id"] = test_hotel[0]["id"]
    test_hotel[0]["hotel_name"] = test_hotel[0]["name"]
    test_hotel[0]["hotel_latitude"] = test_hotel[0].get("latitude") or test_hotel[0].get("location_latitude") or 10.762622
    test_hotel[0]["hotel_longitude"] = test_hotel[0].get("longitude") or test_hotel[0].get("location_longitude") or 106.660172
    
    print("Extracting nearby attractions (seeds)...")
    seeds = crawl_hotel_surroundings(test_hotel, 8, 1)
    print(f"Extracted {len(seeds)} seeds:")
    for s in seeds:
        print(f"  - {s['name']} (Lat: {s.get('seed_latitude')}, Lng: {s.get('seed_longitude')})")
        
    print("Validating seeds (mocking destination)...")
    destination = {
        "location_context": {
            "mode": "radius",
            "latitude": test_hotel[0]["hotel_latitude"],
            "longitude": test_hotel[0]["hotel_longitude"],
            "radius_meters": 10000000
        },
        "destination_name": "Vietnam"
    }
    
    clean_seeds = validate_hotel_surrounding_seeds(seeds, destination["location_context"])
    print(f"{len(clean_seeds)} seeds passed geographic validation.")
    
    print("Normalizing seeds (Google Maps scraping with caching)...")
    resolved = resolve_hotel_surrounding_seeds(
        clean_seeds,
        destination["location_context"],
        5000,
        destination["destination_name"],
        3
    )
    print("Fetching a valid destination_id from Supabase...")
    dest_response = supabase.table("destinations").select("id").limit(1).execute()
    dest_id = dest_response.data[0]["id"] if dest_response.data else "00000000-0000-0000-0000-000000000000"

    from google_maps_pipeline import normalize_google_maps_candidates, validate_clean_google_maps_candidates
    
    print("Validating cleaned Google Maps candidates...")
    validated = validate_clean_google_maps_candidates(resolved, destination["location_context"])
    
    print("Normalizing and enriching Google Maps candidates (Playwright scraping for details)...")
    records = normalize_google_maps_candidates(
        validated,
        dest_id,
        destination["destination_name"],
        max(len(validated), 1),
        fast_poc_mode=False  # Make sure we get full details!
    )
    
    from attraction_utils import deduplicate_attractions, select_diverse_attractions, stable_attraction_id
    
    print("Deduplicating...")
    final_records = deduplicate_attractions(records)
    print(f"Deduplicated to {len(final_records)} attractions.")
    
    for r in final_records:
        r["id"] = stable_attraction_id(r)
        r["destination_id"] = dest_id
        # We leave coordinates as "lat,lng" to exactly match the google_maps_poc_attractions_pipeline output format.

    print("Inserting to Supabase...")
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
        res = supabase.table("attractions").upsert(sanitized_data).execute()
        print(f"Successfully inserted {len(sanitized_data)} attractions into Supabase!")
        print(json.dumps(res.data, indent=2, ensure_ascii=False))
    else:
        print("No attractions to insert.")

if __name__ == "__main__":
    main()
