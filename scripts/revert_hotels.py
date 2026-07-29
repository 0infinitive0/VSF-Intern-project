import os
import psycopg2
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

def main():
    print("Connecting to local database...")
    try:
        conn = psycopg2.connect('postgresql://airflow:airflow@localhost:5432/vsf_database')
        cur = conn.cursor()
    except Exception as e:
        print(f"Error connecting to local DB: {e}")
        return

    print("Fetching hotels from local database...")
    cur.execute("SELECT id FROM hotels;")
    local_ids = [str(row[0]) for row in cur.fetchall()]
    
    print(f"Found {len(local_ids)} hotel IDs locally. Connecting to Supabase...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    
    print("Deleting hotels from Supabase in batches of 100...")
    batch_size = 100
    for i in range(0, len(local_ids), batch_size):
        batch = local_ids[i:i + batch_size]
        try:
            # We can use the 'in_' filter to delete multiple IDs at once
            supabase.table("hotels").delete().in_("id", batch).execute()
            print(f"Deleted batch {i//batch_size + 1}/{len(local_ids)//batch_size + (1 if len(local_ids)%batch_size else 0)}")
        except Exception as e:
            print(f"Error deleting batch: {e}")

    print("Successfully deleted all local hotels from Supabase!")

if __name__ == "__main__":
    main()
