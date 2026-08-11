"""Phase 3: run the golden retrieval set through the real production retrieval
functions (search_hotels_with_rooms / search_attractions, use_llm_filter=True
- the full pipeline, not a shortcut) and score with non-LLM (exact, free) and
LLM-judged (semantic, paid) metrics, reported separately.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from ragas import SingleTurnSample
from ragas.metrics import (
    ContextRelevance,
    IDBasedContextPrecision,
    IDBasedContextRecall,
    LLMContextPrecisionWithReference,
)

from harness.context_format import as_context
from harness.dataset_loader import RetrievalRecord, load_golden_retrieval
from harness.judge import build_judge

from src.services.supabase_search import (
    _get_destination_id_by_name,
    extract_search_filters,
    search_attractions,
    search_hotels_with_rooms,
)


@dataclass
class RetrievalResult:
    record: RetrievalRecord
    retrieved_ids: list[str]
    retrieved_places: list[dict]
    extracted_filters: dict
    resolved_destination_id: str | None
    filter_fallback: bool
    latency_s: float
    non_llm_precision: float | None = None
    non_llm_recall: float | None = None
    llm_precision: float | None = None
    llm_context_relevance: float | None = None
    error: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _run_one(record: RetrievalRecord) -> RetrievalResult:
    search_type = "hotel" if record.search == "hotels" else "attraction"
    extracted = extract_search_filters(record.query, search_type=search_type)
    fallback = set(extracted) == {"clean_query"}
    resolved_dest = _get_destination_id_by_name(extracted.get("destination_name") or "")

    t0 = time.perf_counter()
    try:
        if record.search == "hotels":
            places = search_hotels_with_rooms(query=record.query, match_count=10, use_llm_filter=True)
            id_key = "id"
        else:
            places = search_attractions(query=record.query, match_count=10, use_llm_filter=True)
            id_key = "id"
        error = None
    except Exception as exc:  # the harness must survive one bad query, not abort the run
        places = []
        id_key = "id"
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - t0

    retrieved_ids = [str(p.get(id_key) or p.get("hotel_id") or p.get("attraction_id")) for p in places]

    return RetrievalResult(
        record=record,
        retrieved_ids=retrieved_ids,
        retrieved_places=places,
        extracted_filters=extracted,
        resolved_destination_id=resolved_dest,
        filter_fallback=fallback,
        latency_s=elapsed,
        error=error,
    )


def score_non_llm(result: RetrievalResult) -> None:
    """Precision and recall answer different questions, so they use different
    reference sets: acceptable_ids give a pass on precision (a defensible-but-
    not-required hit shouldn't count as a false positive) but don't count
    toward recall (only a must-have expected_id counts as "found").
    """
    precision = IDBasedContextPrecision()
    recall = IDBasedContextRecall()

    precision_sample = SingleTurnSample(
        retrieved_context_ids=result.retrieved_ids,
        reference_context_ids=result.record.expected_ids + result.record.acceptable_ids,
    )
    recall_sample = SingleTurnSample(
        retrieved_context_ids=result.retrieved_ids,
        reference_context_ids=result.record.expected_ids,
    )
    result.non_llm_precision = precision.single_turn_score(precision_sample)
    result.non_llm_recall = recall.single_turn_score(recall_sample)


def score_llm(result: RetrievalResult, judge) -> None:
    sample = SingleTurnSample(
        user_input=result.record.query,
        retrieved_contexts=[as_context(p) for p in result.retrieved_places],
        reference=result.record.rationale,
    )
    precision_metric = LLMContextPrecisionWithReference(llm=judge)
    relevance_metric = ContextRelevance(llm=judge)
    result.llm_precision = precision_metric.single_turn_score(sample)
    result.llm_context_relevance = relevance_metric.single_turn_score(sample)


def run_retrieval_eval(
    limit: int | None = None,
    llm_metrics: bool = True,
) -> list[RetrievalResult]:
    records = load_golden_retrieval()
    if limit:
        records = records[:limit]

    judge = build_judge() if llm_metrics else None

    results: list[RetrievalResult] = []
    for record in records:
        result = _run_one(record)
        score_non_llm(result)
        if llm_metrics and result.error is None:
            score_llm(result, judge)
        results.append(result)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--llm-metrics", dest="llm_metrics", action="store_true", default=True)
    parser.add_argument("--no-llm-metrics", dest="llm_metrics", action="store_false")
    args = parser.parse_args()

    results = run_retrieval_eval(limit=args.limit, llm_metrics=args.llm_metrics)
    for r in results:
        status = "ERROR" if r.error else "ok"
        print(
            f"[{status}] {r.record.id:45s} "
            f"precision={r.non_llm_precision} recall={r.non_llm_recall} "
            f"llm_precision={r.llm_precision} relevance={r.llm_context_relevance} "
            f"({r.latency_s:.2f}s)"
        )
