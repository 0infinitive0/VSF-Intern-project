import os
import shutil
import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def clear_metadata_and_logs(**kwargs):
    current_dag_id = kwargs['dag_run'].dag_id
    
    print("1. Clearing Airflow Metadata via direct Postgres connection...")
    
    db_conn_kwargs = {
        "host": "postgres",
        "database": "airflow",  # Airflow internal DB
        "user": "airflow",
        "password": "airflow",
        "port": "5432"
    }
    
    conn = None
    try:
        conn = psycopg2.connect(**db_conn_kwargs)
        cursor = conn.cursor()
        
        # Delete history EXCEPT for the currently running cleanup DAG
        tables = ["task_instance", "dag_run", "log", "xcom"]
        for table in tables:
            cursor.execute(f"DELETE FROM {table} WHERE dag_id != %s;", (current_dag_id,))
            
        conn.commit()
        print("Metadata cleared!")
    except Exception as e:
        print(f"Failed to clear metadata DB: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            cursor.close()
            conn.close()

    print("2. Clearing Physical Log Files on Disk...")
    log_dir = "/opt/airflow/logs"
    if os.path.exists(log_dir):
        for item in os.listdir(log_dir):
            # Skip the scheduler logs and the cleanup DAG's own logs
            if item in ["scheduler", f"dag_id={current_dag_id}"]:
                continue
                
            item_path = os.path.join(log_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                print(f"Deleted: {item}")
            except Exception as e:
                print(f"Failed to delete {item_path}: {e}")
    print("Physical logs cleared!")

with DAG(
    dag_id="clear_airflow_history",
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=["maintenance"],
    description="Wipes all task history, DAG runs, and physical logs from Airflow to declutter the UI."
) as dag:
    
    cleanup_task = PythonOperator(
        task_id="clear_all_history",
        python_callable=clear_metadata_and_logs,
    )
