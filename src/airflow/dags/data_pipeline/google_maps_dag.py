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
from google_maps_pipeline import (
    normalize_google_maps_candidates,
    scrape_google_maps_candidates,
    validate_clean_google_maps_candidates,
)
from pipeline_stages import deduplicate_and_select_task, quality_check_task


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "do_xcom_push": False,
    "retries": 0,
}


def extract_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = scrape_google_maps_candidates(
        destination["destination_name"],
        destination["location_context"],
        candidate_limit=max(item_limit * 4, item_limit),
    )
    kwargs["ti"].xcom_push(key="raw_google_maps_records", value=records)
    return f"Extracted {len(records)} public Google Maps candidates"


def validate_clean_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = validate_clean_google_maps_candidates(
        kwargs["ti"].xcom_pull(
            task_ids="extract",
            key="raw_google_maps_records",
        ) or [],
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_google_maps_records", value=records)
    return f"Validated and cleaned {len(records)} Google Maps candidates"


def normalize_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    cleaned_records = kwargs["ti"].xcom_pull(
        task_ids="validate_clean",
        key="clean_google_maps_records",
    ) or []
    print(
        "[google-maps-poc] Normalize: "
        f"received {len(cleaned_records)} cleaned candidates; target={item_limit}."
    )
    records = normalize_google_maps_candidates(
        cleaned_records,
        destination["destination_id"],
        destination["destination_name"],
        item_limit,
    )
    print(
        "[google-maps-poc] Normalize: "
        f"completed {len(records)} normalized records."
    )
    kwargs["ti"].xcom_push(key="normalized_google_maps_records", value=records)
    return f"Normalized and enriched {len(records)} Google Maps records"


def load_task(**kwargs):
    return load_records_task("deduplicate", "selected_records", **kwargs)


with DAG(
    dag_id="google_maps_poc_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Seven-stage public Google Maps POC attraction pipeline; no Maps API",
    schedule=None,
    start_date=datetime(2026, 7, 22),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "google-maps", "poc", "scraper", "attractions", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "item_limit": Param(20, type="integer", minimum=1, maximum=300),
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
            "input_keys": ["normalized_google_maps_records"],
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
