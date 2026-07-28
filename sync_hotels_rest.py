import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, time
from decimal import Decimal
from uuid import UUID

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

LOCAL_DB_URL = "postgresql://airflow:airflow@localhost:5432/vsf_database"

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: Please set SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file.")
    print("You can find these in your Supabase Dashboard under Project Settings -> API.")
    print("Make sure to use the 'service_role' secret key, NOT the anon public key!")
    sys.exit(1)

def serialize_row(row):
    """Convert Postgres-specific types into standard JSON serializable formats"""
    for key, value in row.items():
        if isinstance(value, (datetime, date, time)):
            row[key] = value.isoformat()
        elif isinstance(value, Decimal):
            row[key] = float(value)
        elif isinstance(value, UUID):
            row[key] = str(value)
    return row

def sync_hotels_rest():
    print("Connecting to local database...")
    local_conn = psycopg2.connect(LOCAL_DB_URL)
    local_cur = local_conn.cursor(cursor_factory=RealDictCursor)

    print("Fetching hotels from local database...")
    local_cur.execute("SELECT * FROM hotels;")
    rows = local_cur.fetchall()
    
    if not rows:
        print("No hotels found in the local database.")
        return

    # Convert the RealDictRow objects to standard Python dicts and serialize custom types
    supabase_columns = set(['id', 'destination_id', 'source_platform', 'source_hotel_id', 'source_url', 'name', 'accommodation_type', 'description', 'star_rating', 'address', 'city', 'area_name', 'country', 'location_highlight', 'coordinates', 'amenities', 'amenity_groups', 'highlights', 'awards', 'warnings', 'review_score', 'review_count', 'review_text', 'category_scores', 'score_distribution', 'check_in_time', 'check_in_until', 'check_out_time', 'reception_open_until', 'image_url', 'images', 'image_count', 'nearby_attractions', 'nearby_essentials', 'lowest_price', 'currency', 'price_check_in_date', 'price_check_out_date', 'rooms_available', 'offer_count', 'scraped_at', 'created_at', 'updated_at'])

    # Canonical source_platform vocabulary (matches hotel_pipeline.py's
    # extract_source() and the "agoda"/"booking" values already in this table).
    _CANONICAL_SOURCE_PLATFORMS = {"agoda", "booking"}

    data_to_upsert = []
    for row in rows:
        row_dict = dict(row)

        # `hotels.source_url`/`source_platform`/`source_hotel_id` are already
        # singular columns on this table (scripts/database_schema.sql) and are
        # present as-is from `SELECT *` — no plural array to unwrap. The old
        # code here unconditionally overwrote every row's source_platform with
        # the literal 'booking.com' and source_hotel_id with 'unknown', since
        # it looked for nonexistent 'source_platforms'/'source_ids' columns.
        platform = (row_dict.get("source_platform") or "").strip().lower()
        if platform not in _CANONICAL_SOURCE_PLATFORMS:
            raise ValueError(
                f"hotels.id={row_dict.get('id')}: unknown source_platform {row_dict.get('source_platform')!r}"
            )
        row_dict["source_platform"] = platform

        # Filter out any columns that don't exist in Supabase
        filtered_dict = {k: v for k, v in row_dict.items() if k in supabase_columns}
        data_to_upsert.append(serialize_row(filtered_dict))

    print(f"Found {len(data_to_upsert)} hotels. Connecting to Supabase REST API...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    print("Syncing data to Supabase in batches... (this will update existing rows and insert new ones)")
    
    # Upsert in batches of 100 to avoid HTTP payload size limits
    batch_size = 100
    try:
        for i in range(0, len(data_to_upsert), batch_size):
            batch = data_to_upsert[i:i+batch_size]
            supabase.table("hotels").upsert(batch).execute()
            print(f"Synced batch {i//batch_size + 1}/{(len(data_to_upsert) - 1)//batch_size + 1}")
            
        print("Successfully synced all hotels to Supabase via REST API!")
    except Exception as e:
        print("Error syncing to Supabase via REST API:", e)
    finally:
        local_cur.close()
        local_conn.close()

if __name__ == "__main__":
    sync_hotels_rest()
