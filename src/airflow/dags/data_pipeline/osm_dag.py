import os
import sys
from datetime import datetime, timedelta

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
from osm_pipeline import (
    extract_osm_candidates,
    normalize_osm_candidates,
    validate_clean_osm_candidates,
)
from pipeline_stages import deduplicate_and_select_task, quality_check_task


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def extract_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = extract_osm_candidates(destination["location_context"], item_limit)
    kwargs["ti"].xcom_push(key="raw_osm_records", value=records)
    return f"Extracted {len(records)} raw OSM candidates"


def validate_clean_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    raw_records = kwargs["ti"].xcom_pull(
        task_ids="extract",
        key="raw_osm_records",
    ) or []
    records = validate_clean_osm_candidates(
        raw_records,
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_osm_records", value=records)
    return f"Validated and cleaned {len(records)} OSM candidates"


def normalize_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = normalize_osm_candidates(
        kwargs["ti"].xcom_pull(
            task_ids="validate_clean",
            key="clean_osm_records",
        ) or [],
        destination["destination_name"],
        destination["location_context"],
        destination["destination_id"],
        item_limit,
    )
    kwargs["ti"].xcom_push(key="normalized_osm_records", value=records)
    return f"Normalized {len(records)} OSM + Wikimedia records"


def load_task(**kwargs):
    return load_records_task("deduplicate", "selected_records", **kwargs)


with DAG(
    dag_id="osm_wikimedia_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Seven-stage OSM + Wikimedia attraction pipeline",
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
    data_source = PythonOperator(task_id="data_source", python_callable=prepare_destination_task)
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate_clean = PythonOperator(task_id="validate_clean", python_callable=validate_clean_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    deduplicate = PythonOperator(
        task_id="deduplicate",
        python_callable=deduplicate_and_select_task,
        op_kwargs={
            "input_task_ids": ["normalize"],
            "input_keys": ["normalized_osm_records"],
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
