import os
import sys
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import (
    load_records_task,
    optional_location_coords_param_kwargs,
    prepare_destination_task,
)
from osm_pipeline import collect_osm_attractions


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def collect_osm_task(**kwargs):
    destination = kwargs["ti"].xcom_pull(
        task_ids="prepare_destination",
        key="destination",
    )
    if not destination:
        raise ValueError("Destination setup was not found in XCom.")
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = collect_osm_attractions(
        destination["destination_name"],
        destination["location_context"],
        destination["destination_id"],
        item_limit,
    )
    kwargs["ti"].xcom_push(key="osm_records", value=records)
    return f"Collected {len(records)} OSM + Wikimedia attractions"


def load_osm_task(**kwargs):
    return load_records_task("collect_osm_wikimedia", "osm_records", **kwargs)


with DAG(
    dag_id="osm_wikimedia_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Crawl diverse Vietnam attractions and food places from OSM, enriched by Wikimedia",
    schedule=timedelta(days=7),
    start_date=datetime(2026, 7, 21),
    catchup=False,
    tags=["vsf", "osm", "wikimedia", "attractions", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "item_limit": Param(20, type="integer", minimum=1, maximum=500),
    },
) as dag:
    prepare_destination = PythonOperator(
        task_id="prepare_destination",
        python_callable=prepare_destination_task,
    )
    collect_osm_wikimedia = PythonOperator(
        task_id="collect_osm_wikimedia",
        python_callable=collect_osm_task,
    )
    load_to_postgres = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_osm_task,
    )

    prepare_destination >> collect_osm_wikimedia >> load_to_postgres
