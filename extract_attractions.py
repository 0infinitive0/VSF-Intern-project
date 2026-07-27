import os
import sys
import json
import uuid

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from supabase import create_client, Client
except ImportError:
    print("Error: Missing supabase library. Please run: pip install supabase")
    sys.exit(1)

# Supabase credentials from .env
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file.")
    sys.exit(1)

# Table configurations
SOURCE_TABLE = "hotels"
TARGET_TABLE = "attractions"
COLUMN_TO_EXTRACT = "nearby_attractions"

def extract_attractions():
    print(f"Connecting to Supabase at {SUPABASE_URL}...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    print(f"Fetching data from {SOURCE_TABLE}...")
    
    all_hotels = []
    limit = 1000
    offset = 0
    
    while True:
        try:
            # We need destination_id to link the attraction to the correct destination
            response = supabase.table(SOURCE_TABLE).select(f"id, destination_id, {COLUMN_TO_EXTRACT}").range(offset, offset + limit - 1).execute()
            data = response.data
            
            if not data:
                break
                
            all_hotels.extend(data)
            
            if len(data) < limit:
                break
                
            offset += limit
        except Exception as e:
            print(f"Error querying {SOURCE_TABLE}: {e}")
            sys.exit(1)

    print(f"Fetched {len(all_hotels)} hotels. Extracting attractions...")
    
    # Use a dictionary to deduplicate attractions by (name, destination_id)
    unique_attractions = {}
    
    for hotel in all_hotels:
        destination_id = hotel.get("destination_id")
        attractions_data = hotel.get(COLUMN_TO_EXTRACT)
        
        if not attractions_data or not destination_id:
            continue
            
        if isinstance(attractions_data, str):
            try:
                attractions_data = json.loads(attractions_data)
            except json.JSONDecodeError:
                continue
                
        if isinstance(attractions_data, list):
            for attr in attractions_data:
                name = None
                coordinates = None
                description = None
                
                if isinstance(attr, dict):
                    # Format: {"name": "Bảo tàng lịch sử Việt Nam", "coordinates": "...", "distance_text": "8 km"}
                    name = attr.get("name")
                    coordinates = attr.get("coordinates")
                    if "distance_text" in attr:
                        description = f"Khoảng cách tham khảo: {attr.get('distance_text')}"
                        
                elif isinstance(attr, str):
                    # Format: "Đền thờ Lê Văn Duyệt - Cách nơi ở 900 m"
                    parts = attr.split(" - ")
                    name = parts[0].strip()
                    if len(parts) > 1:
                        description = parts[1].strip()
                        
                if name:
                    # Create a unique key
                    key = (name.lower(), destination_id)
                    if key not in unique_attractions:
                        # Map to the target schema as per data_dictionary.md
                        unique_attractions[key] = {
                            "id": str(uuid.uuid4()), # Generate UUID for the PK
                            "destination_id": destination_id,
                            "name": name,
                            "category": "Điểm tham quan", # Default category
                            "is_tour": False,
                            "description": description,
                            "coordinates": coordinates
                        }
                    else:
                        # If we already have it, but now we found coordinates, update it
                        if coordinates and not unique_attractions[key].get("coordinates"):
                            unique_attractions[key]["coordinates"] = coordinates
                            
    extracted_list = list(unique_attractions.values())
    print(f"Successfully extracted {len(extracted_list)} unique attractions.")
    
    if not extracted_list:
        print("No attractions to insert. Exiting.")
        return

    print(f"Syncing attractions to '{TARGET_TABLE}' table in batches of 100...")
    batch_size = 100
    
    try:
        for i in range(0, len(extracted_list), batch_size):
            batch = extracted_list[i:i+batch_size]
            supabase.table(TARGET_TABLE).upsert(batch).execute()
            print(f"Inserted batch {i//batch_size + 1}/{(len(extracted_list) - 1)//batch_size + 1}")
            
        print("Successfully extracted and synced all attractions to Supabase!")
    except Exception as e:
        print(f"Error inserting attractions into '{TARGET_TABLE}': {e}")

if __name__ == "__main__":
    extract_attractions()
