"""Hotel vector-quality gate (Phase 5): permissive first-pass thresholds
against `hotel_pipeline._vector_quality_metrics()`'s output, tightened after
one clean run. Kept free of any `airflow` import so it's importable and
unit-testable outside the Airflow container (`hotel_dag.py` is not — it
imports `airflow` at module level, which isn't installed in the local test
venv)."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

MAX_EMPTY_EMBEDDING_TEXT_RATIO = 0.05
MAX_PAYLOAD_BYTES = 32 * 1024
MAX_MISSING_COORDINATES_RATIO = 0.50  # warn only, does not fail the gate


class VectorQualityGateFailure(Exception):
    """Raised on a gate breach or a missing/malformed metrics XCom.
    `hotel_dag.sync_qdrant_task` re-raises this as `AirflowFailException`."""


def check_vector_quality_gate(metrics: Dict[str, Any]) -> None:
    """Fail-loud, never silent-skip: raises with the breaching metric named
    directly in the message. This can only ever protect the downstream
    Qdrant sync — load_to_postgresql and (if enabled) load_to_supabase have
    already committed by the time this runs.

    A missing/malformed XCom must fail the same way a breached threshold
    does — the DAG task already raises on empty `records`, so `total == 0`
    alongside a non-empty records list is a contradiction, not a legitimate
    "nothing to check" case. The gate existing but never firing (missing
    key, renamed field, empty XCom) would be the exact silent-skip this
    function commits not to do.
    """
    if not metrics:
        raise VectorQualityGateFailure(
            "hotel_vector_quality_metrics XCom is missing or empty "
            "(expected from the quality_check task)"
        )
    if "total" not in metrics:
        raise VectorQualityGateFailure(
            f"metrics missing required key 'total' (keys present: {sorted(metrics)})"
        )

    total = metrics["total"]
    if total == 0:
        raise VectorQualityGateFailure("metrics report total=0 hotels; nothing was measured")

    empty_ratio = metrics.get("empty_embedding_text", 0) / total
    if empty_ratio > MAX_EMPTY_EMBEDDING_TEXT_RATIO:
        raise VectorQualityGateFailure(
            f"empty_embedding_text ratio {empty_ratio:.1%} "
            f"({metrics['empty_embedding_text']}/{total}) exceeds "
            f"{MAX_EMPTY_EMBEDDING_TEXT_RATIO:.0%} threshold"
        )

    max_bytes = metrics.get("max_payload_bytes", 0)
    if max_bytes > MAX_PAYLOAD_BYTES:
        raise VectorQualityGateFailure(
            f"max_payload_bytes {max_bytes} exceeds {MAX_PAYLOAD_BYTES} byte threshold"
        )

    missing_coords_ratio = metrics.get("missing_coordinates", 0) / total
    if missing_coords_ratio > MAX_MISSING_COORDINATES_RATIO:
        logger.warning(
            "Quality gate warning (non-fatal): missing_coordinates ratio %.1f%% "
            "(%d/%d) exceeds %.0f%% threshold",
            missing_coords_ratio * 100, metrics["missing_coordinates"], total,
            MAX_MISSING_COORDINATES_RATIO * 100,
        )
