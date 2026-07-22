import os
import sys
from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from attraction_utils import deduplicate_attractions, select_diverse_attractions
from dag_common import (
    load_records_task,
    optional_location_coords_param_kwargs,
    prepare_destination_task,
)
from osm_pipeline import collect_osm_attractions
from ota_pipeline import collect_ota_attractions


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def collect_osm_task(**kwargs):
    destination = kwargs["ti"].xcom_pull("prepare_destination", key="destination")
    params = kwargs.get("params") or {}
    limit = int(params.get("item_limit") or 20)
    records = collect_osm_attractions(
        destination["destination_name"],
        destination["location_context"],
        destination["destination_id"],
        max(limit * 2, limit),
    )
    kwargs["ti"].xcom_push(key="osm_records", value=records)
    return f"Collected {len(records)} OSM + Wikimedia candidates"


def collect_ota_task(**kwargs):
    destination = kwargs["ti"].xcom_pull("prepare_destination", key="destination")
    params = kwargs.get("params") or {}
    limit = int(params.get("item_limit") or 20)
    records = collect_ota_attractions(
        destination_name=destination["destination_name"],
        location_context=destination["location_context"],
        destination_id=destination["destination_id"],
        item_limit=max(limit * 2, limit),
        source=str(params.get("source") or "both"),
        allow_web_scraping=bool(params.get("allow_ota_web_scraping", False)),
    )
    kwargs["ti"].xcom_push(key="ota_records", value=records)
    return f"Collected {len(records)} Booking.com + Agoda candidates"


def combine_task(**kwargs):
    ti = kwargs["ti"]
    params = kwargs.get("params") or {}
    osm_records = ti.xcom_pull("collect_osm_wikimedia", key="osm_records") or []
    ota_records = ti.xcom_pull("collect_booking_agoda", key="ota_records") or []
    combined = deduplicate_attractions(osm_records + ota_records)
    selected = select_diverse_attractions(combined, int(params.get("item_limit") or 20))
    ti.xcom_push(key="combined_records", value=selected)
    return f"Selected {len(selected)} unique, diverse attractions from {len(combined)} candidates"


def load_combined_task(**kwargs):
    return load_records_task("combine_and_select", "combined_records", **kwargs)


with DAG(
    dag_id="combined_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Combine OSM + Wikimedia with Booking.com + Agoda, then deduplicate and diversify",
    schedule=None,
    start_date=datetime(2026, 7, 21),
    catchup=False,
    tags=["vsf", "combined", "osm", "wikimedia", "booking", "agoda", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "item_limit": Param(30, type="integer", minimum=1, maximum=100),
        "source": Param("both", type="string", enum=["booking", "agoda", "both"]),
        "allow_ota_web_scraping": Param(False, type="boolean"),
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
    collect_booking_agoda = PythonOperator(
        task_id="collect_booking_agoda",
        python_callable=collect_ota_task,
    )
    combine_and_select = PythonOperator(
        task_id="combine_and_select",
        python_callable=combine_task,
    )
    load_to_postgres = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_combined_task,
    )

    prepare_destination >> [collect_osm_wikimedia, collect_booking_agoda]
    [collect_osm_wikimedia, collect_booking_agoda] >> combine_and_select >> load_to_postgres
