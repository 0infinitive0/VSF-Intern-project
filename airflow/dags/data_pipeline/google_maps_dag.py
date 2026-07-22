import os
import sys
from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import (
    load_records_task,
    optional_location_coords_param_kwargs,
    prepare_destination_task,
)
from google_maps_pipeline import collect_google_maps_attractions


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def collect_google_maps_task(**kwargs):
    destination = kwargs["ti"].xcom_pull(
        task_ids="prepare_destination",
        key="destination",
    )
    if not destination:
        raise ValueError("Destination setup was not found in XCom.")
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = collect_google_maps_attractions(
        destination["destination_name"],
        destination["location_context"],
        destination["destination_id"],
        item_limit,
    )
    kwargs["ti"].xcom_push(key="google_maps_records", value=records)
    return f"Collected {len(records)} Google Maps POC attractions"


def load_google_maps_task(**kwargs):
    return load_records_task(
        "collect_google_maps",
        "google_maps_records",
        **kwargs,
    )


with DAG(
    dag_id="google_maps_poc_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="POC browser scraper for public Google Maps result cards; no Maps API",
    schedule=None,
    start_date=datetime(2026, 7, 22),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "google-maps", "poc", "scraper", "attractions", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "item_limit": Param(20, type="integer", minimum=1, maximum=100),
    },
) as dag:
    prepare_destination = PythonOperator(
        task_id="prepare_destination",
        python_callable=prepare_destination_task,
    )
    collect_google_maps = PythonOperator(
        task_id="collect_google_maps",
        python_callable=collect_google_maps_task,
    )
    load_to_postgres = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_google_maps_task,
    )

    prepare_destination >> collect_google_maps >> load_to_postgres
