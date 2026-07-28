"""Airflow DAG for loading Booking and Agoda hotel JSON dumps into PostgreSQL."""

import logging
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param

logger = logging.getLogger(__name__)


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import DB_KWARGS, load_hotels_to_supabase_task
from hotel_pipeline import (
    DedupeStats,
    LoadStats,
    PhysicalMatchStats,
    ValidationStats,
    assign_physical_hotel_groups,
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


def physical_match_task(**kwargs):
    records, stats = assign_physical_hotel_groups(
        kwargs["ti"].xcom_pull(task_ids="dedupe", key="deduped_hotel_records") or []
    )
    kwargs["ti"].xcom_push(key="physical_matched_hotel_records", value=records)
    kwargs["ti"].xcom_push(key="hotel_physical_match_stats", value=asdict(stats))
    return f"Cross-OTA grouping: {stats.groups_created} groups ({stats.groups_pending_review} pending review)"


def load_task(**kwargs):
    records = kwargs["ti"].xcom_pull(task_ids="physical_match", key="physical_matched_hotel_records") or []
    if not records:
        raise ValueError("No valid hotel records were produced.")
    stats = load_hotels_to_db(records, DB_KWARGS)
    kwargs["ti"].xcom_push(key="hotel_load_stats", value=asdict(stats))
    return (
        f"Loaded {stats.hotels_upserted} hotels, "
        f"{stats.rooms_upserted} rooms, {stats.prices_upserted} prices into PostgreSQL"
    )


def load_to_supabase_task(**kwargs):
    params = kwargs.get("params") or {}
    if not params.get("sync_to_supabase", False):
        return "Skipped: sync_to_supabase param is off (data stays local to Postgres)"
    return load_hotels_to_supabase_task(
        records_task_id="physical_match",
        records_key="physical_matched_hotel_records",
        **kwargs,
    )


def quality_task(**kwargs):
    params = kwargs.get("params") or {}
    validation_stats = kwargs["ti"].xcom_pull(task_ids="validate", key="hotel_validation_stats") or {}
    dedupe_stats = kwargs["ti"].xcom_pull(task_ids="dedupe", key="hotel_dedupe_stats") or {}
    physical_match_stats = (
        kwargs["ti"].xcom_pull(task_ids="physical_match", key="hotel_physical_match_stats") or {}
    )
    load_stats = kwargs["ti"].xcom_pull(task_ids="load_to_postgresql", key="hotel_load_stats") or {}
    # This gate can only ever protect the downstream Qdrant sync — load_to_postgresql
    # already committed to Postgres, and load_to_supabase already committed to
    # Supabase, both before this task runs.
    report_path, metrics = quality_check_hotels(
        ValidationStats(**validation_stats),
        DedupeStats(**dedupe_stats),
        PhysicalMatchStats(**physical_match_stats),
        LoadStats(**load_stats),
        kwargs["ti"].xcom_pull(task_ids="physical_match", key="physical_matched_hotel_records") or [],
        _path_param(params, "reports_dir", DEFAULT_REPORTS_DIR),
    )
    kwargs["ti"].xcom_push(key="hotel_quality_report_path", value=report_path)
    kwargs["ti"].xcom_push(key="hotel_vector_quality_metrics", value=metrics)
    return f"Hotel quality report written to {report_path}"


def sync_qdrant_task(**kwargs):
    from hotel_quality_gate import VectorQualityGateFailure, check_vector_quality_gate

    metrics = kwargs["ti"].xcom_pull(task_ids="quality_check", key="hotel_vector_quality_metrics") or {}
    try:
        check_vector_quality_gate(metrics)
    except VectorQualityGateFailure as exc:
        raise AirflowFailException(f"Quality gate: {exc}") from exc

    records = kwargs["ti"].xcom_pull(task_ids="physical_match", key="physical_matched_hotel_records") or []
    if not records:
        raise ValueError("No physically-matched hotel records were produced.")

    identity_map = (
        kwargs["ti"].xcom_pull(task_ids="load_to_supabase", key="hotel_supabase_identity_map") or {}
    )

    # Lazy imports: dag-processor (which parses this file) has neither the
    # `src` mount nor these dependencies — only scheduler/worker do. Keeping
    # `src.services.*` imports inside task callables, not module top-level,
    # is what keeps DAG parsing working there (see Phase 4's report).
    from qdrant_client import QdrantClient

    from src.config import get_settings
    from src.services.qdrant_writer import upsert_hotels

    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=60)

    started = time.monotonic()
    stats = upsert_hotels(client, records, identity_map)
    duration_seconds = round(time.monotonic() - started, 1)

    kwargs["ti"].xcom_push(key="hotel_qdrant_upsert_stats", value=asdict(stats))
    kwargs["ti"].xcom_push(key="hotel_qdrant_sync_duration_seconds", value=duration_seconds)
    return (
        f"Synced {stats.hotels_upserted} hotels to Qdrant in {duration_seconds}s "
        f"({stats.identity_resolved} with resolved Supabase identity)"
    )


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
        # Off by default: hotels stay local to Postgres. Set true to also push
        # to Supabase (make it authoritative for hotels, per the 2026-07-27
        # plan decision) once that path is ready to use.
        "sync_to_supabase": Param(False, type="boolean"),
    },
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate = PythonOperator(task_id="validate", python_callable=validate_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    dedupe = PythonOperator(task_id="dedupe", python_callable=dedupe_task)
    physical_match = PythonOperator(task_id="physical_match", python_callable=physical_match_task)
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    load_to_supabase = PythonOperator(task_id="load_to_supabase", python_callable=load_to_supabase_task)
    quality_check = PythonOperator(task_id="quality_check", python_callable=quality_task)
    sync_qdrant = PythonOperator(task_id="sync_qdrant", python_callable=sync_qdrant_task)

    (
        extract
        >> validate
        >> normalize
        >> dedupe
        >> physical_match
        >> load_to_postgresql
        >> load_to_supabase
        >> quality_check
        >> sync_qdrant
    )
