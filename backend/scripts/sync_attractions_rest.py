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

def sync_attractions_rest():
    print("Connecting to local database...")
    local_conn = psycopg2.connect(LOCAL_DB_URL)
    local_cur = local_conn.cursor(cursor_factory=RealDictCursor)

    print("Fetching attractions from local database...")
    local_cur.execute("SELECT * FROM attractions;")
    rows = local_cur.fetchall()
    
    if not rows:
        print("No attractions found in the local database.")
        return

    # Convert the RealDictRow objects to standard Python dicts and serialize custom types
    data_to_upsert = [serialize_row(dict(row)) for row in rows]

    print(f"Found {len(data_to_upsert)} attractions. Connecting to Supabase REST API...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    print("Syncing data to Supabase in batches... (this will update existing rows and insert new ones)")
    
    # Upsert in batches of 100 to avoid HTTP payload size limits
    batch_size = 100
    try:
        for i in range(0, len(data_to_upsert), batch_size):
            batch = data_to_upsert[i:i+batch_size]
            supabase.table("attractions").upsert(batch).execute()
            print(f"Synced batch {i//batch_size + 1}/{(len(data_to_upsert) - 1)//batch_size + 1}")
            
        print("Successfully synced all attractions to Supabase via REST API!")
    except Exception as e:
        print("Error syncing to Supabase via REST API:", e)
    finally:
        local_cur.close()
        local_conn.close()

if __name__ == "__main__":
    sync_attractions_rest()
