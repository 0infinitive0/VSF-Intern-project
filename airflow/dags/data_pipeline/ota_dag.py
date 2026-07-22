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
from ota_pipeline import collect_ota_attractions


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def collect_ota_task(**kwargs):
    destination = kwargs["ti"].xcom_pull(
        task_ids="prepare_destination",
        key="destination",
    )
    if not destination:
        raise ValueError("Destination setup was not found in XCom.")
    params = kwargs.get("params") or {}
    records = collect_ota_attractions(
        destination_name=destination["destination_name"],
        location_context=destination["location_context"],
        destination_id=destination["destination_id"],
        item_limit=int(params.get("item_limit") or 20),
        source=str(params.get("source") or "both"),
        allow_web_scraping=bool(params.get("allow_ota_web_scraping", False)),
    )
    kwargs["ti"].xcom_push(key="ota_records", value=records)
    return f"Collected {len(records)} Booking.com + Agoda attractions"


def load_ota_task(**kwargs):
    return load_records_task("collect_booking_agoda", "ota_records", **kwargs)


with DAG(
    dag_id="booking_agoda_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Opt-in public-page scraper for Booking.com and Agoda Vietnam activities",
    schedule=None,
    start_date=datetime(2026, 7, 21),
    catchup=False,
    tags=["vsf", "booking", "agoda", "scraper", "attractions", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "item_limit": Param(20, type="integer", minimum=1, maximum=100),
        "source": Param("both", type="string", enum=["booking", "agoda", "both"]),
        "allow_ota_web_scraping": Param(False, type="boolean"),
    },
) as dag:
    prepare_destination = PythonOperator(
        task_id="prepare_destination",
        python_callable=prepare_destination_task,
    )
    collect_booking_agoda = PythonOperator(
        task_id="collect_booking_agoda",
        python_callable=collect_ota_task,
    )
    load_to_postgres = PythonOperator(
        task_id="load_to_postgres",
        python_callable=load_ota_task,
    )

    prepare_destination >> collect_booking_agoda >> load_to_postgres
