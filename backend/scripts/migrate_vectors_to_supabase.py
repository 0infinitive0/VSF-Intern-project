import os
import sys
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from supabase import create_client

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
qdrant = QdrantClient("http://localhost:6333")

def copy_vectors_to_supabase(collection_name: str, table_name: str, id_field: str):
    print(f"\n--- Migrating '{collection_name}' -> Supabase table '{table_name}' ---", flush=True)
    
    if not qdrant.collection_exists(collection_name):
        print(f"Collection '{collection_name}' does not exist in local Qdrant. Skipping.", flush=True)
        return

    # Fetch all points and their vectors from Qdrant
    records, _ = qdrant.scroll(
        collection_name=collection_name,
        limit=10000,
        with_payload=True,
        with_vectors=True
    )
    
    print(f"Found {len(records)} vectors in Qdrant. Updating Supabase...", flush=True)
    
    success_count = 0
    for record in records:
        metadata = record.payload.get("metadata", {}) if record.payload else {}
        record_id = metadata.get(id_field)
        if record_id and record.vector:
            try:
                # Update Supabase table directly
                res = supabase.table(table_name).update(
                    {"embedding": record.vector}
                ).eq("id", str(record_id)).execute()
                
                success_count += 1
                if success_count % 20 == 0:
                    print(f"  Copied {success_count} / {len(records)}...", flush=True)
            except Exception as e:
                print(f"Error updating ID {record_id}: {e}", flush=True)
                if "Could not find the 'embedding' column" in str(e) or "column" in str(e).lower() and "does not exist" in str(e).lower():
                    print(f"\n[CRITICAL ERROR] The 'embedding' column does not exist in table '{table_name}' in Supabase!", flush=True)
                    print(f"Please run this in your Supabase SQL Editor first:\n", flush=True)
                    print(f"  ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS embedding vector(1024);\n", flush=True)
                    return
                
    print(f"[OK] Successfully copied {success_count} vectors to table '{table_name}'!", flush=True)

if __name__ == "__main__":
    copy_vectors_to_supabase("hotels_vector", "hotels", "hotel_id")
    copy_vectors_to_supabase("rooms_vector", "rooms", "room_id")
    copy_vectors_to_supabase("attractions_vector", "attractions", "attraction_id")
