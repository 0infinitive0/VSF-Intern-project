"""Shared Airflow stages for canonical attraction records."""

from collections import Counter
from typing import Any, Dict, Iterable, List, Sequence

from attraction_utils import deduplicate_attractions, select_diverse_attractions


CANONICAL_REQUIRED_FIELDS = (
    "id",
    "destination_id",
    "name",
    "category",
    "source",
    "source_id",
    "coordinates",
    "latitude",
    "longitude",
)


def deduplicate_and_select(
    records: Iterable[Dict[str, Any]],
    item_limit: int,
) -> List[Dict[str, Any]]:
    """Apply the shared duplicate rules and category-balanced item limit."""
    return select_diverse_attractions(deduplicate_attractions(records), item_limit)


def _has_canonical_schema(record: Dict[str, Any]) -> bool:
    return all(
        record.get(field) not in (None, "")
        for field in CANONICAL_REQUIRED_FIELDS
    )


def _coverage_percent(matches: int, total: int) -> float:
    return round((matches / total) * 100, 1) if total else 0.0


def summarize_quality(
    records: Iterable[Dict[str, Any]],
    extracted_count: int = 0,
) -> Dict[str, Any]:
    """Return deterministic completeness and schema metrics for loaded records."""
    selected = list(records)
    total = len(selected)
    return {
        "extracted_records": extracted_count or total,
        "selected_records": total,
        "schema_valid_records": sum(_has_canonical_schema(record) for record in selected),
        "description_coverage_percent": _coverage_percent(
            sum(bool(record.get("description")) for record in selected),
            total,
        ),
        "image_coverage_percent": _coverage_percent(
            sum(bool(record.get("images")) for record in selected),
            total,
        ),
        "category_counts": dict(sorted(Counter(
            str(record.get("category") or "Other activities")
            for record in selected
        ).items())),
        "source_counts": dict(sorted(Counter(
            str(record.get("source") or "unknown")
            for record in selected
        ).items())),
    }


def deduplicate_and_select_task(
    input_task_ids: Sequence[str],
    input_keys: Sequence[str],
    output_key: str,
    **kwargs: Any,
) -> str:
    """Airflow task wrapper for the common deduplicate stage."""
    if len(input_task_ids) != len(input_keys):
        raise ValueError("input_task_ids and input_keys must have the same length.")
    ti = kwargs["ti"]
    candidates: List[Dict[str, Any]] = []
    for task_id, key in zip(input_task_ids, input_keys):
        candidates.extend(ti.xcom_pull(task_ids=task_id, key=key) or [])
    item_limit = int((kwargs.get("params") or {}).get("item_limit") or 20)
    selected = deduplicate_and_select(candidates, item_limit)
    ti.xcom_push(key=output_key, value=selected)
    ti.xcom_push(
        key=f"{output_key}_input_count",
        value=len(candidates),
    )
    return f"Selected {len(selected)} unique, diverse records from {len(candidates)} candidates"


def quality_check_task(
    records_task_id: str,
    records_key: str,
    **kwargs: Any,
) -> str:
    """Airflow task wrapper for the final data-quality block."""
    ti = kwargs["ti"]
    records = ti.xcom_pull(task_ids=records_task_id, key=records_key) or []
    extracted_count = ti.xcom_pull(
        task_ids=records_task_id,
        key=f"{records_key}_input_count",
    ) or len(records)
    report = summarize_quality(records, int(extracted_count))
    ti.xcom_push(key="quality_report", value=report)
    return (
        f"Quality check: {report['schema_valid_records']}/{report['selected_records']} "
        f"schema-valid, {report['description_coverage_percent']}% descriptions, "
        f"{report['image_coverage_percent']}% images"
    )
