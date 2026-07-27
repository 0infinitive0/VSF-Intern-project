import os
import sys
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
LOCAL_DB_URL = "postgresql://airflow:airflow@localhost:5432/vsf_database"

# Get Supabase connection string from environment
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")

if not SUPABASE_DB_URL:
    print("Error: Please set the SUPABASE_DB_URL environment variable in your .env file.")
    print("Example (.env file):")
    print("  SUPABASE_DB_URL=\"postgresql://postgres.[project]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres\"")
    print("\nOr install python-dotenv: pip install python-dotenv")
    sys.exit(1)

def sync_attractions():
    print("Connecting to local database...")
    local_conn = psycopg2.connect(LOCAL_DB_URL)
    local_cur = local_conn.cursor(cursor_factory=RealDictCursor)

    print("Fetching attractions from local database...")
    local_cur.execute("SELECT * FROM attractions;")
    rows = local_cur.fetchall()
    
    if not rows:
        print("No attractions found in the local database.")
        return

    # Extract column names dynamically
    columns = list(rows[0].keys())
    
    # Prepare data as a list of tuples
    values = []
    for row in rows:
        values.append(tuple(row[col] for col in columns))

    print(f"Found {len(rows)} attractions. Connecting to Supabase...")
    supa_conn = psycopg2.connect(SUPABASE_DB_URL)
    supa_cur = supa_conn.cursor()

    # Construct the UPSERT query
    col_names = ", ".join(columns)
    
    # Update all columns except 'id' on conflict
    update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != 'id'])

    insert_query = f"""
        INSERT INTO attractions ({col_names})
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
        {update_set};
    """

    print("Syncing data to Supabase... (this will update existing rows and insert new ones)")
    try:
        execute_values(supa_cur, insert_query, values, page_size=500)
        supa_conn.commit()
        print("Successfully synced all attractions to Supabase!")
    except Exception as e:
        supa_conn.rollback()
        print("Error syncing to Supabase:", e)
    finally:
        local_cur.close()
        local_conn.close()
        supa_cur.close()
        supa_conn.close()

if __name__ == "__main__":
    sync_attractions()
