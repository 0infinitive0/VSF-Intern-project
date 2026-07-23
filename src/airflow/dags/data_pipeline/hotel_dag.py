"""Airflow DAG for loading Booking and Agoda hotel JSON dumps into PostgreSQL."""

import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import DB_KWARGS
from hotel_pipeline import (
    DedupeStats,
    LoadStats,
    ValidationStats,
    dedupe_hotels,
    extract_hotels,
    load_hotels_to_db,
    normalize_hotels,
    quality_check_hotels,
    validate_hotels,
)


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "do_xcom_push": False,
    "retries": 0,
}

DEFAULT_DATA_DIR = Path(os.getenv("VSF_HOTEL_DATA_DIR", "/opt/airflow/data"))
DEFAULT_REPORTS_DIR = Path(os.getenv("VSF_HOTEL_REPORTS_DIR", "/opt/airflow/logs/reports"))


def _path_param(params, key: str, default_path: Path) -> str:
    return str(params.get(key) or default_path)


def extract_task(**kwargs):
    params = kwargs.get("params") or {}
    records = extract_hotels(
        _path_param(params, "agoda_path", DEFAULT_DATA_DIR / "agoda.json"),
        _path_param(params, "booking_path", DEFAULT_DATA_DIR / "booking.json"),
    )
    kwargs["ti"].xcom_push(key="raw_hotel_records", value=records)
    return f"Extracted {len(records)} raw hotel records"


def validate_task(**kwargs):
    raw_records = kwargs["ti"].xcom_pull(task_ids="extract", key="raw_hotel_records") or []
    records, stats = validate_hotels(raw_records)
    kwargs["ti"].xcom_push(key="validated_hotel_records", value=records)
    kwargs["ti"].xcom_push(key="hotel_validation_stats", value=asdict(stats))
    return f"Validated {stats.valid} hotel records ({stats.rejected} rejected)"


def normalize_task(**kwargs):
    records = normalize_hotels(
        kwargs["ti"].xcom_pull(task_ids="validate", key="validated_hotel_records") or []
    )
    kwargs["ti"].xcom_push(key="normalized_hotel_records", value=records)
    return f"Normalized {len(records)} hotel records"


def dedupe_task(**kwargs):
    records, stats = dedupe_hotels(
        kwargs["ti"].xcom_pull(task_ids="normalize", key="normalized_hotel_records") or []
    )
    kwargs["ti"].xcom_push(key="deduped_hotel_records", value=records)
    kwargs["ti"].xcom_push(key="hotel_dedupe_stats", value=asdict(stats))
    return f"Deduped {len(records)} hotel records ({stats.hotels_removed} duplicate hotels removed)"


def load_task(**kwargs):
    records = kwargs["ti"].xcom_pull(task_ids="dedupe", key="deduped_hotel_records") or []
    if not records:
        raise ValueError("No valid hotel records were produced.")
    stats = load_hotels_to_db(records, DB_KWARGS)
    kwargs["ti"].xcom_push(key="hotel_load_stats", value=asdict(stats))
    return (
        f"Loaded {stats.hotels_upserted} hotels, "
        f"{stats.rooms_upserted} rooms, {stats.prices_upserted} prices into PostgreSQL"
    )


def quality_task(**kwargs):
    params = kwargs.get("params") or {}
    validation_stats = kwargs["ti"].xcom_pull(task_ids="validate", key="hotel_validation_stats") or {}
    dedupe_stats = kwargs["ti"].xcom_pull(task_ids="dedupe", key="hotel_dedupe_stats") or {}
    load_stats = kwargs["ti"].xcom_pull(task_ids="load_to_postgresql", key="hotel_load_stats") or {}
    report_path = quality_check_hotels(
        ValidationStats(**validation_stats),
        DedupeStats(**dedupe_stats),
        LoadStats(**load_stats),
        kwargs["ti"].xcom_pull(task_ids="dedupe", key="deduped_hotel_records") or [],
        _path_param(params, "reports_dir", DEFAULT_REPORTS_DIR),
    )
    kwargs["ti"].xcom_push(key="hotel_quality_report_path", value=report_path)
    return f"Hotel quality report written to {report_path}"


with DAG(
    dag_id="booking_agoda_hotel_loader_pipeline",
    default_args=DEFAULT_ARGS,
    description="Load Booking and Agoda hotel JSON dumps into flat PostgreSQL hotel tables",
    schedule=None,
    start_date=datetime(2026, 7, 23),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "booking", "agoda", "hotels", "etl"],
    params={
        "agoda_path": Param(str(DEFAULT_DATA_DIR / "agoda.json"), type="string", minLength=1),
        "booking_path": Param(str(DEFAULT_DATA_DIR / "booking.json"), type="string", minLength=1),
        "reports_dir": Param(str(DEFAULT_REPORTS_DIR), type="string", minLength=1),
    },
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate = PythonOperator(task_id="validate", python_callable=validate_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    dedupe = PythonOperator(task_id="dedupe", python_callable=dedupe_task)
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    quality_check = PythonOperator(task_id="quality_check", python_callable=quality_task)

    extract >> validate >> normalize >> dedupe >> load_to_postgresql >> quality_check
