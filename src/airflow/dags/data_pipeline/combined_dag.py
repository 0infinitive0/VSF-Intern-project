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
from osm_pipeline import (
    extract_osm_candidates,
    normalize_osm_candidates,
    validate_clean_osm_candidates,
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
    "do_xcom_push": False,
    "retries": 0,
}


def extract_osm_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = extract_osm_candidates(destination["location_context"], max(limit * 2, limit))
    kwargs["ti"].xcom_push(key="raw_osm_records", value=records)
    return f"Extracted {len(records)} raw OSM candidates"


def validate_clean_osm_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = validate_clean_osm_candidates(
        kwargs["ti"].xcom_pull(task_ids="extract_osm", key="raw_osm_records") or [],
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_osm_records", value=records)
    return f"Validated and cleaned {len(records)} OSM candidates"


def normalize_osm_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    records = normalize_osm_candidates(
        kwargs["ti"].xcom_pull(
            task_ids="validate_clean_osm",
            key="clean_osm_records",
        ) or [],
        destination["destination_name"],
        destination["location_context"],
        destination["destination_id"],
        max(limit * 2, limit),
    )
    kwargs["ti"].xcom_push(key="normalized_osm_records", value=records)
    return f"Normalized {len(records)} OSM + Wikimedia records"


def extract_ota_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    params = kwargs.get("params") or {}
    limit = int(params.get("item_limit") or 20)
    records = extract_ota_candidates(
        destination["destination_name"],
        max(limit * 2, limit),
        source=str(params.get("source") or "both"),
        allow_web_scraping=bool(params.get("allow_ota_web_scraping", False)),
    )
    kwargs["ti"].xcom_push(key="raw_ota_records", value=records)
    return f"Extracted {len(records)} Booking.com + Agoda candidates"


def validate_clean_ota_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = validate_clean_ota_candidates(
        kwargs["ti"].xcom_pull(task_ids="extract_ota", key="raw_ota_records") or [],
        destination["destination_name"],
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_ota_records", value=records)
    return f"Validated and cleaned {len(records)} OTA candidates"


def normalize_ota_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    records = normalize_ota_candidates(
        kwargs["ti"].xcom_pull(
            task_ids="validate_clean_ota",
            key="clean_ota_records",
        ) or [],
        destination["destination_id"],
    )
    kwargs["ti"].xcom_push(key="normalized_ota_records", value=records)
    return f"Normalized {len(records)} OTA records"


def load_task(**kwargs):
    return load_records_task("deduplicate", "selected_records", **kwargs)


with DAG(
    dag_id="combined_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Seven-stage combined OSM, Wikimedia, Booking.com, and Agoda pipeline",
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
    data_source = PythonOperator(task_id="data_source", python_callable=prepare_destination_task)
    extract_osm = PythonOperator(task_id="extract_osm", python_callable=extract_osm_task)
    validate_clean_osm = PythonOperator(
        task_id="validate_clean_osm",
        python_callable=validate_clean_osm_task,
    )
    normalize_osm = PythonOperator(task_id="normalize_osm", python_callable=normalize_osm_task)
    extract_ota = PythonOperator(task_id="extract_ota", python_callable=extract_ota_task)
    validate_clean_ota = PythonOperator(
        task_id="validate_clean_ota",
        python_callable=validate_clean_ota_task,
    )
    normalize_ota = PythonOperator(task_id="normalize_ota", python_callable=normalize_ota_task)
    deduplicate = PythonOperator(
        task_id="deduplicate",
        python_callable=deduplicate_and_select_task,
        op_kwargs={
            "input_task_ids": ["normalize_osm", "normalize_ota"],
            "input_keys": ["normalized_osm_records", "normalized_ota_records"],
            "output_key": "selected_records",
        },
    )
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    quality_check = PythonOperator(
        task_id="quality_check",
        python_callable=quality_check_task,
        op_kwargs={"records_task_id": "deduplicate", "records_key": "selected_records"},
    )

    data_source >> [extract_osm, extract_ota]
    extract_osm >> validate_clean_osm >> normalize_osm
    extract_ota >> validate_clean_ota >> normalize_ota
    [normalize_osm, normalize_ota] >> deduplicate >> load_to_postgresql >> quality_check
