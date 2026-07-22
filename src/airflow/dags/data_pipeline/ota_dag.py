import os
import sys
from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import (
    destination_from_xcom,
    load_records_task,
    optional_location_coords_param_kwargs,
    prepare_destination_task,
)
from ota_pipeline import (
    extract_ota_candidates,
    normalize_ota_candidates,
    validate_clean_ota_candidates,
)
from pipeline_stages import deduplicate_and_select_task, quality_check_task


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


def extract_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    params = kwargs.get("params") or {}
    records = extract_ota_candidates(
        destination_name=destination["destination_name"],
        item_limit=int(params.get("item_limit") or 20),
        source=str(params.get("source") or "both"),
        allow_web_scraping=bool(params.get("allow_ota_web_scraping", False)),
    )
    kwargs["ti"].xcom_push(key="raw_ota_records", value=records)
    return f"Extracted {len(records)} Booking.com + Agoda candidates"


def validate_clean_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = validate_clean_ota_candidates(
        kwargs["ti"].xcom_pull(task_ids="extract", key="raw_ota_records") or [],
        destination["destination_name"],
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_ota_records", value=records)
    return f"Validated and cleaned {len(records)} OTA candidates"


def normalize_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = normalize_ota_candidates(
        kwargs["ti"].xcom_pull(
            task_ids="validate_clean",
            key="clean_ota_records",
        ) or [],
        destination["destination_id"],
    )
    kwargs["ti"].xcom_push(key="normalized_ota_records", value=records)
    return f"Normalized {len(records)} OTA records"


def load_task(**kwargs):
    return load_records_task("deduplicate", "selected_records", **kwargs)


with DAG(
    dag_id="booking_agoda_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Seven-stage opt-in Booking.com and Agoda attraction pipeline",
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
    data_source = PythonOperator(task_id="data_source", python_callable=prepare_destination_task)
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate_clean = PythonOperator(task_id="validate_clean", python_callable=validate_clean_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    deduplicate = PythonOperator(
        task_id="deduplicate",
        python_callable=deduplicate_and_select_task,
        op_kwargs={
            "input_task_ids": ["normalize"],
            "input_keys": ["normalized_ota_records"],
            "output_key": "selected_records",
        },
    )
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    quality_check = PythonOperator(
        task_id="quality_check",
        python_callable=quality_check_task,
        op_kwargs={"records_task_id": "deduplicate", "records_key": "selected_records"},
    )

    data_source >> extract >> validate_clean >> normalize >> deduplicate >> load_to_postgresql >> quality_check
