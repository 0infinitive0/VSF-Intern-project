from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
import psycopg2

def clear_database(**kwargs):
    print("Clearing all data from destinations and attractions tables...")
    
    db_conn_kwargs = {
        "host": "postgres",
        "database": "vsf_database",
        "user": "airflow",
        "password": "airflow",
        "port": "5432"
    }
    
    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        
        # CASCADE ensures any dependent tables (like events or hotels) are also cleared
        cursor.execute("TRUNCATE destinations, attractions CASCADE;")
        conn.commit()
        
        print("Database successfully cleared! All history has been wiped.")
    except Exception as e:
        print(f"Error clearing database: {e}")
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            cursor.close()
            conn.close()

with DAG(
    dag_id="clear_database_history",
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=["maintenance"],
    description="Wipes all crawled data from the database to start fresh."
) as dag:
    
    clear_task = PythonOperator(
        task_id="truncate_tables",
        python_callable=clear_database,
    )
