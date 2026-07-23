"""Seven-stage hotel-surroundings attraction pipeline for Booking and Agoda hotel rows."""

import os
import sys
import logging
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
from attraction_utils import deduplicate_attractions
from google_maps_pipeline import normalize_google_maps_candidates, validate_clean_google_maps_candidates
from hotel_nearby_pipeline import (
    crawl_hotel_surroundings,
    fetch_hotel_sources,
    fetch_existing_attraction_name_keys,
    filter_existing_attraction_names,
    resolve_hotel_surrounding_seeds,
    validate_hotel_surrounding_seeds,
)
from pipeline_stages import quality_check_task


DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "do_xcom_push": False,
    "retries": 0,
}

LOGGER = logging.getLogger(__name__)


def data_source_task(**kwargs):
    params = kwargs.get("params") or {}
    LOGGER.info(
        "[hotel-nearby] stage=data_source event=start destination=%s",
        str(params.get("destination_name") or "").strip(),
    )
    destination = prepare_destination_task(**kwargs)
    LOGGER.info(
        "[hotel-nearby] stage=data_source event=complete context_mode=%s",
        destination["location_context"].get("mode"),
    )
    return destination


def extract_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    params = kwargs.get("params") or {}
    LOGGER.info(
        "[hotel-nearby] stage=extract event=start hotel_scope=%s",
        "one" if str(params.get("hotel_id") or "").strip() else "all",
    )
    hotels = fetch_hotel_sources(
        destination["destination_id"],
        str(params.get("hotel_id") or "").strip(),
    )
    LOGGER.info("[hotel-nearby] stage=extract event=progress hotels=%d", len(hotels))
    worker_count = int(params.get("parallel_hotel_workers") or 2)
    LOGGER.info(
        "[hotel-nearby] stage=extract event=progress parallel_hotel_workers=%d",
        worker_count,
    )
    records = crawl_hotel_surroundings(
        hotels,
        int(params.get("nearby_limit_per_hotel") or 8),
        worker_count,
    )
    kwargs["ti"].xcom_push(key="raw_hotel_surrounding_records", value=records)
    LOGGER.info(
        "[hotel-nearby] stage=extract event=complete hotels=%d surroundings=%d",
        len(hotels),
        len(records),
    )
    return f"Extracted {len(records)} surroundings from {len(hotels)} Booking/Agoda hotels"


def validate_clean_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    raw_records = kwargs["ti"].xcom_pull(
        task_ids="extract",
        key="raw_hotel_surrounding_records",
    ) or []
    LOGGER.info(
        "[hotel-nearby] stage=validate_clean event=start raw_surroundings=%d",
        len(raw_records),
    )
    records = validate_hotel_surrounding_seeds(
        raw_records,
        destination["location_context"],
    )
    kwargs["ti"].xcom_push(key="clean_hotel_surrounding_records", value=records)
    LOGGER.info(
        "[hotel-nearby] stage=validate_clean event=complete accepted=%d rejected=%d",
        len(records),
        len(raw_records) - len(records),
    )
    return f"Validated {len(records)} hotel-surrounding place names"


def normalize_task(**kwargs):
    destination = destination_from_xcom("data_source", **kwargs)
    params = kwargs.get("params") or {}
    seeds = kwargs["ti"].xcom_pull(
        task_ids="validate_clean",
        key="clean_hotel_surrounding_records",
    ) or []
    worker_count = int(params.get("parallel_hotel_workers") or 2)
    existing_name_keys = fetch_existing_attraction_name_keys(destination["destination_id"])
    unseen_seeds = filter_existing_attraction_names(seeds, existing_name_keys)
    LOGGER.info(
        "[hotel-nearby] stage=normalize event=start seeds=%d existing_name_skips=%d hotel_radius_meters=%d parallel_hotel_workers=%d",
        len(unseen_seeds),
        len(seeds) - len(unseen_seeds),
        int(params.get("hotel_radius_meters") or 5_000),
        worker_count,
    )
    resolved = resolve_hotel_surrounding_seeds(
        unseen_seeds,
        destination["location_context"],
        int(params.get("hotel_radius_meters") or 5_000),
        destination["destination_name"],
        worker_count,
    )
    LOGGER.info(
        "[hotel-nearby] stage=normalize event=progress maps_resolved=%d",
        len(resolved),
    )
    validated = validate_clean_google_maps_candidates(
        resolved,
        destination["location_context"],
    )
    LOGGER.info(
        "[hotel-nearby] stage=normalize event=progress maps_validated=%d",
        len(validated),
    )
    unseen_candidates = filter_existing_attraction_names(validated, existing_name_keys)
    LOGGER.info(
        "[hotel-nearby] stage=normalize event=progress canonical_name_skips=%d",
        len(validated) - len(unseen_candidates),
    )
    records = normalize_google_maps_candidates(
        unseen_candidates,
        destination["destination_id"],
        destination["destination_name"],
        max(len(unseen_candidates), 1),
    )
    LOGGER.info(
        "[hotel-nearby] stage=normalize event=complete canonical_attractions=%d",
        len(records),
    )
    kwargs["ti"].xcom_push(key="normalized_hotel_nearby_records", value=records)
    return f"Normalized and enriched {len(records)} hotel-nearby attractions"


def load_task(**kwargs):
    records = kwargs["ti"].xcom_pull(
        task_ids="deduplicate",
        key="selected_records",
    ) or []
    LOGGER.info("[hotel-nearby] stage=load event=start records=%d", len(records))
    if not records:
        LOGGER.info("[hotel-nearby] stage=load event=skipped reason=no_valid_records")
        return "No valid hotel-nearby attractions to load; skipping PostgreSQL load."
    result = load_records_task("deduplicate", "selected_records", **kwargs)
    LOGGER.info("[hotel-nearby] stage=load event=complete records=%d", len(records))
    return result


def deduplicate_all_task(**kwargs):
    """Keep every unique valid attraction; this pipeline intentionally has no item cap."""
    ti = kwargs["ti"]
    candidates = ti.xcom_pull(
        task_ids="normalize",
        key="normalized_hotel_nearby_records",
    ) or []
    LOGGER.info(
        "[hotel-nearby] stage=deduplicate event=start candidates=%d",
        len(candidates),
    )
    selected = deduplicate_attractions(candidates)
    ti.xcom_push(key="selected_records", value=selected)
    ti.xcom_push(key="selected_records_input_count", value=len(candidates))
    LOGGER.info(
        "[hotel-nearby] stage=deduplicate event=complete selected=%d removed=%d",
        len(selected),
        len(candidates) - len(selected),
    )
    return f"Selected all {len(selected)} unique hotel-nearby attractions"


def quality_stage_task(**kwargs):
    records = kwargs["ti"].xcom_pull(
        task_ids="deduplicate",
        key="selected_records",
    ) or []
    LOGGER.info("[hotel-nearby] stage=quality_check event=start records=%d", len(records))
    result = quality_check_task(
        records_task_id="deduplicate",
        records_key="selected_records",
        **kwargs,
    )
    report = kwargs["ti"].xcom_pull(key="quality_report") or {}
    LOGGER.info(
        "[hotel-nearby] stage=quality_check event=complete schema_valid=%d descriptions_pct=%s images_pct=%s",
        int(report.get("schema_valid_records") or 0),
        report.get("description_coverage_percent", 0.0),
        report.get("image_coverage_percent", 0.0),
    )
    return result


with DAG(
    dag_id="hotel_nearby_attractions_pipeline",
    default_args=DEFAULT_ARGS,
    description="Booking/Agoda hotel surroundings resolved by public Google Maps; no official APIs",
    schedule=None,
    start_date=datetime(2026, 7, 22),
    catchup=False,
    max_active_runs=1,
    tags=["vsf", "hotels", "booking", "agoda", "google-maps", "poc", "attractions", "etl"],
    params={
        "destination_name": Param("Nha Trang", type="string", minLength=1),
        "location_coords": Param(**optional_location_coords_param_kwargs()),
        "radius_meters": Param(20_000, type="integer", minimum=500, maximum=100_000),
        "hotel_id": Param(
            None,
            type=["null", "string"],
            description="Optional hotels.id UUID. Leave blank to process all eligible hotels.",
        ),
        "nearby_limit_per_hotel": Param(8, type="integer", minimum=1, maximum=30),
        "hotel_radius_meters": Param(5_000, type="integer", minimum=100, maximum=20_000),
        "parallel_hotel_workers": Param(
            2,
            type="integer",
            minimum=1,
            maximum=4,
            description="Concurrent hotel batches for OTA and Google Maps scraping.",
        ),
    },
) as dag:
    data_source = PythonOperator(task_id="data_source", python_callable=data_source_task)
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate_clean = PythonOperator(task_id="validate_clean", python_callable=validate_clean_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    deduplicate = PythonOperator(
        task_id="deduplicate",
        python_callable=deduplicate_all_task,
    )
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    quality_check = PythonOperator(
        task_id="quality_check",
        python_callable=quality_stage_task,
    )

    data_source >> extract >> validate_clean >> normalize >> deduplicate >> load_to_postgresql >> quality_check
