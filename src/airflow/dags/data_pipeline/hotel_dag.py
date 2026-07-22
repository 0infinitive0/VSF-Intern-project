"""Seven-stage hotel ingest from exported Booking.com and Agoda datasets.

Two deliberate differences from the attraction DAGs:

* `data_source` discovers dataset files instead of geocoding one destination.
  The destinations come from the datasets themselves, so they are resolved in
  `normalize`, once the city of every record is known.
* Stages exchange JSONL file paths through XCom rather than the records.
  A full export carries roughly 1000 hotels with 45 images each, which the
  XCom metadata backend should not be asked to store.
"""

import os
import sys
from datetime import datetime

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Param

from airflow import DAG

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dag_common import DB_KWARGS  # noqa: E402
from hotel_pipeline import (  # noqa: E402
    deduplicate_hotels,
    destination_keys_from_candidates,
    discover_dataset_files,
    extract_hotel_candidates,
    get_or_create_destinations,
    load_hotels_to_db,
    normalize_hotel_candidates,
    read_jsonl,
    summarize_hotel_quality,
    validate_clean_hotel_candidates,
    write_jsonl,
)

DEFAULT_ARGS = {
    "owner": "data_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}

# Datasets and stage output live in the repository's own `data/` directory, four
# levels above this file (dags/data_pipeline -> dags -> airflow -> src -> root).
# Resolving from __file__ keeps the defaults correct whether the DAG runs from a
# checkout or from a container that mounts the repo somewhere else.
REPO_DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "data")
)

DEFAULT_DATASET_DIR = os.getenv("VSF_HOTEL_DATASET_DIR", os.path.join(REPO_DATA_DIR, "raw"))
DEFAULT_WORK_DIR = os.getenv("VSF_HOTEL_WORK_DIR", os.path.join(REPO_DATA_DIR, "interim"))


def _work_path(file_name: str, **kwargs) -> str:
    """Run-scoped path for a stage artefact."""
    run_id = str(kwargs["run_id"]).replace(":", "-").replace("+", "-")
    return os.path.join(DEFAULT_WORK_DIR, run_id, file_name)


def data_source_task(**kwargs) -> str:
    params = kwargs.get("params") or {}
    dataset_dir = str(params.get("dataset_dir") or DEFAULT_DATASET_DIR)
    files = discover_dataset_files(dataset_dir, str(params.get("source") or "both"))
    kwargs["ti"].xcom_push(key="dataset_files", value=files)
    return f"Discovered {len(files)} dataset files in {dataset_dir}"


def extract_task(**kwargs) -> str:
    files = kwargs["ti"].xcom_pull(task_ids="data_source", key="dataset_files") or []
    candidates = extract_hotel_candidates(files)
    path = _work_path("candidates.jsonl", **kwargs)
    count = write_jsonl(path, candidates)
    kwargs["ti"].xcom_push(key="candidates_path", value=path)
    kwargs["ti"].xcom_push(key="extracted_count", value=count)
    return f"Extracted {count} hotel candidates from {len(files)} files"


def validate_clean_task(**kwargs) -> str:
    candidates = read_jsonl(kwargs["ti"].xcom_pull(task_ids="extract", key="candidates_path"))
    kept, rejects = validate_clean_hotel_candidates(candidates)

    clean_path = _work_path("clean.jsonl", **kwargs)
    reject_path = _work_path("rejects.jsonl", **kwargs)
    write_jsonl(clean_path, kept)
    write_jsonl(reject_path, rejects)
    kwargs["ti"].xcom_push(key="clean_path", value=clean_path)
    kwargs["ti"].xcom_push(key="reject_path", value=reject_path)
    kwargs["ti"].xcom_push(key="reject_count", value=len(rejects))

    hotel_rejects = sum(reject["level"] == "hotel" for reject in rejects)
    denominator = len(kept) + hotel_rejects
    reject_rate = (hotel_rejects / denominator * 100) if denominator else 0.0
    max_rate = float((kwargs.get("params") or {}).get("max_reject_rate_percent") or 5)
    if reject_rate > max_rate:
        raise ValueError(
            f"Hotel reject rate {reject_rate:.1f}% exceeds the {max_rate}% ceiling. "
            f"See {reject_path} before loading."
        )
    return f"Kept {len(kept)} hotels, rejected {len(rejects)} items ({reject_rate:.1f}% of hotels)"


def normalize_task(**kwargs) -> str:
    candidates = read_jsonl(kwargs["ti"].xcom_pull(task_ids="validate_clean", key="clean_path"))
    destination_ids = get_or_create_destinations(destination_keys_from_candidates(candidates), DB_KWARGS)
    records = normalize_hotel_candidates(candidates, destination_ids)

    path = _work_path("normalized.jsonl", **kwargs)
    write_jsonl(path, records)
    kwargs["ti"].xcom_push(key="normalized_path", value=path)
    kwargs["ti"].xcom_push(key="destination_ids", value=destination_ids)
    return f"Normalized {len(records)} hotels across {len(destination_ids)} destinations"


def deduplicate_task(**kwargs) -> str:
    records = read_jsonl(kwargs["ti"].xcom_pull(task_ids="normalize", key="normalized_path"))
    merged, review_pairs = deduplicate_hotels(records)

    merged_path = _work_path("merged.jsonl", **kwargs)
    review_path = _work_path("merge_review.jsonl", **kwargs)
    write_jsonl(merged_path, merged)
    write_jsonl(review_path, review_pairs)
    kwargs["ti"].xcom_push(key="merged_path", value=merged_path)
    kwargs["ti"].xcom_push(key="review_path", value=review_path)
    kwargs["ti"].xcom_push(key="review_pair_count", value=len(review_pairs))
    return (
        f"Merged {len(records)} records into {len(merged)} hotels; "
        f"{len(review_pairs)} pairs need manual review"
    )


def load_task(**kwargs) -> str:
    records = read_jsonl(kwargs["ti"].xcom_pull(task_ids="deduplicate", key="merged_path"))
    counts = load_hotels_to_db(records, DB_KWARGS)
    kwargs["ti"].xcom_push(key="load_counts", value=counts)
    return (
        f"Loaded {counts['hotels']} hotels, {counts['rooms']} rooms, "
        f"{counts['room_prices']} prices into PostgreSQL"
    )


def quality_check_task(**kwargs) -> str:
    ti = kwargs["ti"]
    records = read_jsonl(ti.xcom_pull(task_ids="deduplicate", key="merged_path"))
    report = summarize_hotel_quality(
        records,
        extracted_count=int(ti.xcom_pull(task_ids="extract", key="extracted_count") or 0),
        reject_count=int(ti.xcom_pull(task_ids="validate_clean", key="reject_count") or 0),
        review_pair_count=int(ti.xcom_pull(task_ids="deduplicate", key="review_pair_count") or 0),
    )
    ti.xcom_push(key="quality_report", value=report)
    return (
        f"Quality check: {report['loaded_hotels']} hotels, "
        f"{report['coordinate_coverage_percent']}% coordinates, "
        f"{report['star_rating_coverage_percent']}% star ratings, "
        f"{report['cross_source_hotels']} cross-source merges"
    )


with DAG(
    dag_id="booking_agoda_hotels_pipeline",
    default_args=DEFAULT_ARGS,
    description="Seven-stage ingest of exported Booking.com and Agoda hotel datasets",
    schedule=None,
    start_date=datetime(2026, 7, 22),
    catchup=False,
    tags=["vsf", "booking", "agoda", "hotels", "etl"],
    params={
        "dataset_dir": Param(DEFAULT_DATASET_DIR, type="string", minLength=1),
        "source": Param("both", type="string", enum=["booking", "agoda", "both"]),
        "max_reject_rate_percent": Param(5, type="number", minimum=0, maximum=100),
    },
) as dag:
    data_source = PythonOperator(task_id="data_source", python_callable=data_source_task)
    extract = PythonOperator(task_id="extract", python_callable=extract_task)
    validate_clean = PythonOperator(task_id="validate_clean", python_callable=validate_clean_task)
    normalize = PythonOperator(task_id="normalize", python_callable=normalize_task)
    deduplicate = PythonOperator(task_id="deduplicate", python_callable=deduplicate_task)
    load_to_postgresql = PythonOperator(task_id="load_to_postgresql", python_callable=load_task)
    quality_check = PythonOperator(task_id="quality_check", python_callable=quality_check_task)

    data_source >> extract >> validate_clean >> normalize >> deduplicate >> load_to_postgresql >> quality_check
