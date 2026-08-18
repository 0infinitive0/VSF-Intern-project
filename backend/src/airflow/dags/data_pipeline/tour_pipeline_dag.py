"""Tour/Activity data pipeline DAG.

Wires tour_pipeline.py's Extract -> Validate -> Normalize -> Dedupe -> Load ->
QualityCheck functions into Airflow tasks, same shape as the (currently
unregistered — see .airflowignore) hotel pipeline. Manually triggered only:
tour prices/availability change constantly, so this is never a good
"scheduled, unattended" crawl the way the OSM/Wikipedia attraction DAG is.

Data source is a live Apify actor run (Booking.com tours/activities), not a
local file upload — see fetch_tours_from_apify in tour_pipeline.py. Actor ID
and baseline run_input live in Airflow Variables and rarely change; a
"Trigger DAG w/ config" run can override either per run via `dag_run.conf`
without touching the Variables:

    tour_booking_actor_id       Variable, required        e.g. "your-username/booking-tours-scraper"
    tour_booking_actor_input    Variable, JSON, optional   baseline run_input (default "{}")
    apify_default                Connection, required       password field = Apify API token

conf overrides (all optional):
    booking_actor_id      string, overrides the Variable for this run only
    booking_actor_input   dict, merged on top of the Variable's baseline

The `tours` table is a directly-managed Postgres table (same database as
`hotels`/`destinations`, via dag_common.DB_KWARGS) — not the newer
Supabase-REST load path some attraction DAGs use, since tours are OTA
listing data in the same shape/lifecycle as hotels, not a crawled attraction
candidate pool.
"""

import json
import os
import sys
from datetime import datetime

from airflow import DAG
from airflow.hooks.base import BaseHook
from airflow.models import Variable
from airflow.providers.standard.operators.python import PythonOperator


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import DB_KWARGS
from tour_pipeline import (
    DedupeStats,
    LoadStats,
    ValidationStats,
    dedupe_tours,
    fetch_tours_from_apify,
    load_tours_to_db,
    normalize_tours,
    quality_check_tours,
    validate_tours,
)


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "do_xcom_push": False,
    "retries": 0,
}

REPORTS_DIR = os.getenv("VSF_REPORTS_DIR", "/opt/airflow/reports")


def extract_task(**kwargs):
    conf = (kwargs["dag_run"].conf or {}) if kwargs.get("dag_run") else {}
    actor_id = conf.get("booking_actor_id") or Variable.get("tour_booking_actor_id")
    run_input = {
        **json.loads(Variable.get("tour_booking_actor_input", default_var="{}")),
        **conf.get("booking_actor_input", {}),
    }
    token = BaseHook.get_connection("apify_default").password

    raw = fetch_tours_from_apify(actor_id, "booking", token, run_input)
    kwargs["ti"].xcom_push(key="raw_tours", value=raw)
    return f"Extracted {len(raw)} raw tour records from Apify"


def validate_task(**kwargs):
    raw = kwargs["ti"].xcom_pull(task_ids="extract", key="raw_tours") or []
    validated, stats = validate_tours(raw)
    kwargs["ti"].xcom_push(key="validated_tours", value=validated)
    kwargs["ti"].xcom_push(key="validation_stats", value=vars(stats))
    return f"Validated {stats.valid}/{stats.total} tour records ({stats.rejected} rejected)"


def normalize_task(**kwargs):
    validated = kwargs["ti"].xcom_pull(task_ids="validate", key="validated_tours") or []
    normalized = normalize_tours(validated)
    kwargs["ti"].xcom_push(key="normalized_tours", value=normalized)
    return f"Normalized {len(normalized)} tour records"


def deduplicate_task(**kwargs):
    normalized = kwargs["ti"].xcom_pull(task_ids="normalize", key="normalized_tours") or []
    deduped, stats = dedupe_tours(normalized)
    kwargs["ti"].xcom_push(key="deduped_tours", value=deduped)
    kwargs["ti"].xcom_push(key="dedupe_stats", value=vars(stats))
    return f"Deduplicated to {len(deduped)} tours ({stats.tours_removed} duplicates removed)"


def load_task(**kwargs):
    deduped = kwargs["ti"].xcom_pull(task_ids="deduplicate", key="deduped_tours") or []
    stats = load_tours_to_db(deduped, DB_KWARGS)
    kwargs["ti"].xcom_push(key="load_stats", value=vars(stats))
    return f"Loaded {stats.tours_upserted} tours into PostgreSQL"


def quality_check_task(**kwargs):
    ti = kwargs["ti"]
    deduped = ti.xcom_pull(task_ids="deduplicate", key="deduped_tours") or []
    validation_stats = ValidationStats(**(ti.xcom_pull(task_ids="validate", key="validation_stats") or {}))
    dedupe_stats = DedupeStats(**(ti.xcom_pull(task_ids="deduplicate", key="dedupe_stats") or {}))
    load_stats = LoadStats(**(ti.xcom_pull(task_ids="load", key="load_stats") or {}))

    report_path = quality_check_tours(validation_stats, dedupe_stats, load_stats, deduped, REPORTS_DIR)
    return f"Quality report written to {report_path}"


with DAG(
    dag_id="tour_pipeline",
    default_args=DEFAULT_ARGS,
    description="Extract/Validate/Normalize/Dedupe/Load/QualityCheck for Booking tour & activity data",
    schedule=None,
    start_date=datetime(2026, 8, 17),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "tours", "booking", "apify", "etl"],
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate = PythonOperator(task_id="validate", python_callable=validate_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    deduplicate = PythonOperator(task_id="deduplicate", python_callable=deduplicate_task)
    load = PythonOperator(task_id="load", python_callable=load_task)
    quality_check = PythonOperator(task_id="quality_check", python_callable=quality_check_task)

    extract >> validate >> normalize >> deduplicate >> load >> quality_check
