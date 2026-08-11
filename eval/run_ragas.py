#!/usr/bin/env python3
"""CLI entry for the RAGAS eval harness. Run with eval/.venv-eval/bin/python.

    eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --limit 5 --no-llm-metrics
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.e2e_eval import ConversationResult, run_e2e_eval  # noqa: E402
from harness.report import dataset_hash  # noqa: E402
from harness.retrieval_eval import RetrievalResult, run_retrieval_eval  # noqa: E402

_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_BASELINE_PATH = _RESULTS_DIR / "baseline.json"


def _nan_safe(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def _retrieval_result_to_dict(r: RetrievalResult) -> dict:
    return {
        "id": r.record.id,
        "search": r.record.search,
        "language": r.record.language,
        "pair_id": r.record.pair_id,
        "query": r.record.query,
        "expected_ids": r.record.expected_ids,
        "acceptable_ids": r.record.acceptable_ids,
        "retrieved_ids": r.retrieved_ids,
        "non_llm_precision": _nan_safe(r.non_llm_precision),
        "non_llm_recall": _nan_safe(r.non_llm_recall),
        "llm_precision": _nan_safe(r.llm_precision),
        "llm_context_relevance": _nan_safe(r.llm_context_relevance),
        "extracted_filters": r.extracted_filters,
        "resolved_destination_id": r.resolved_destination_id,
        "filter_fallback": r.filter_fallback,
        "latency_s": round(r.latency_s, 3),
        "error": r.error,
    }


def _breakdown(rows: list[dict], key: str, metric: str) -> dict:
    groups: dict[str, list[float]] = {}
    for row in rows:
        val = row.get(metric)
        if val is None:
            continue
        groups.setdefault(row[key], []).append(val)
    return {k: round(sum(v) / len(v), 4) for k, v in groups.items() if v}


def run_retrieval_layer(limit: int | None, llm_metrics: bool) -> dict:
    results = run_retrieval_eval(limit=limit, llm_metrics=llm_metrics)
    rows = [_retrieval_result_to_dict(r) for r in results]

    breakdowns = {
        "non_llm_precision_by_language": _breakdown(rows, "language", "non_llm_precision"),
        "non_llm_recall_by_language": _breakdown(rows, "language", "non_llm_recall"),
        "non_llm_precision_by_search": _breakdown(rows, "search", "non_llm_precision"),
        "non_llm_recall_by_search": _breakdown(rows, "search", "non_llm_recall"),
    }
    if llm_metrics:
        breakdowns["llm_precision_by_language"] = _breakdown(rows, "language", "llm_precision")
        breakdowns["llm_context_relevance_by_language"] = _breakdown(rows, "language", "llm_context_relevance")

    errors = [row["id"] for row in rows if row["error"]]
    filter_fallbacks = [row["id"] for row in rows if row["filter_fallback"]]

    return {
        "rows": rows,
        "breakdowns": breakdowns,
        "summary": {
            "total": len(rows),
            "errors": errors,
            "filter_fallbacks": filter_fallbacks,
        },
    }


def _conversation_result_to_dict(r: ConversationResult) -> dict:
    return {
        "id": r.record.id,
        "language": r.record.language,
        "expected_stage": r.record.expected_stage,
        "reached_stage": r.reached_stage,
        "harness_failure": r.harness_failure,
        "error": r.error,
        "transcript_path": r.transcript_path,
        "turns": [
            {
                "turn_class": t.turn_class,
                "tool": t.tool,
                "has_contexts": bool(t.contexts),
                "faithfulness": _nan_safe(t.faithfulness),
                "response_relevancy": _nan_safe(t.response_relevancy),
                "latency_s": round(t.latency_s, 3),
            }
            for t in r.turns
        ],
    }


def _turn_metric_breakdown(conversations: list[dict], metric: str) -> dict:
    """Average a per-turn metric grouped by turn_class (template/generated/mixed),
    only across conversations that did NOT harness-fail - a conversation that never
    reached its expected stage shouldn't count toward a quality average (see plan's
    Phase 4 non-functional requirement).
    """
    groups: dict[str, list[float]] = {}
    for conv in conversations:
        if conv["harness_failure"]:
            continue
        for turn in conv["turns"]:
            val = turn.get(metric)
            if val is None:
                continue
            groups.setdefault(turn["turn_class"], []).append(val)
    return {k: round(sum(v) / len(v), 4) for k, v in groups.items() if v}


def run_e2e_layer(limit: int | None, score: bool) -> dict:
    results = run_e2e_eval(limit=limit, score=score)
    rows = [_conversation_result_to_dict(r) for r in results]

    total_turns = sum(len(r["turns"]) for r in rows)
    excluded_no_context_turns = sum(
        1 for r in rows for t in r["turns"] if not t["has_contexts"]
    )
    harness_failures = [r["id"] for r in rows if r["harness_failure"]]
    errors = [r["id"] for r in rows if r["error"]]

    return {
        "rows": rows,
        "breakdowns": {
            "faithfulness_by_turn_class": _turn_metric_breakdown(rows, "faithfulness"),
            "response_relevancy_by_turn_class": _turn_metric_breakdown(rows, "response_relevancy"),
        },
        "summary": {
            "total_conversations": len(rows),
            "total_turns": total_turns,
            "excluded_no_context_turns": excluded_no_context_turns,
            "harness_failures": harness_failures,
            "reached_expected_stage_pct": round(
                100 * (len(rows) - len(harness_failures)) / len(rows), 1
            ) if rows else None,
            "errors": errors,
        },
    }


def _extract_baseline_scores(output: dict) -> dict:
    """Per-record scores keyed by golden-record id, plus the dataset hash they
    were scored against - the minimum needed for a meaningful delta later."""
    baseline: dict = {"dataset_hash": dataset_hash(), "retrieval": {}, "e2e": {}}
    for row in output.get("retrieval", {}).get("rows", []):
        baseline["retrieval"][row["id"]] = {
            "non_llm_precision": row["non_llm_precision"],
            "non_llm_recall": row["non_llm_recall"],
            "llm_precision": row["llm_precision"],
            "llm_context_relevance": row["llm_context_relevance"],
        }
    for row in output.get("e2e", {}).get("rows", []):
        baseline["e2e"][row["id"]] = {
            "reached_stage": row["reached_stage"],
            "harness_failure": row["harness_failure"],
        }
    return baseline


def _compare_baseline(output: dict, baseline_path: Path) -> None:
    with open(baseline_path, encoding="utf-8") as f:
        baseline = json.load(f)

    current_hash = dataset_hash()
    if baseline["dataset_hash"] != current_hash:
        raise SystemExit(
            f"REFUSING TO COMPARE: baseline was scored against dataset_hash="
            f"{baseline['dataset_hash']}, current dataset_hash={current_hash}. "
            "The golden datasets changed since the baseline was frozen - a diff across "
            "different dataset versions would be meaningless. Refresh the baseline first."
        )

    print("\n--- Baseline comparison (non_llm_precision delta) ---")
    current_by_id = {row["id"]: row for row in output.get("retrieval", {}).get("rows", [])}
    max_delta = 0.0
    for record_id, base_scores in baseline["retrieval"].items():
        current = current_by_id.get(record_id)
        if current is None:
            print(f"  {record_id}: MISSING from current run")
            continue
        base_p = base_scores["non_llm_precision"] or 0.0
        cur_p = current["non_llm_precision"] or 0.0
        delta = cur_p - base_p
        max_delta = max(max_delta, abs(delta))
        if abs(delta) > 1e-9:
            print(f"  {record_id}: {base_p} -> {cur_p} (delta {delta:+.4f})")
    print(f"Max |delta| across all retrieval records: {max_delta:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=["retrieval", "e2e", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="cap records per layer, for cheap iteration")
    parser.add_argument("--llm-metrics", dest="llm_metrics", action="store_true", default=True)
    parser.add_argument("--no-llm-metrics", dest="llm_metrics", action="store_false")
    parser.add_argument("--out", type=Path, default=None, help="override the output .json path")
    parser.add_argument("--save-baseline", action="store_true", help="freeze this run as eval/results/baseline.json")
    parser.add_argument("--compare-baseline", action="store_true", help="diff this run against eval/results/baseline.json")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    output: dict = {
        "run_metadata": {
            "timestamp_utc": timestamp,
            "layer": args.layer,
            "limit": args.limit,
            "llm_metrics": args.llm_metrics,
        }
    }

    if args.layer in ("retrieval", "all"):
        print(f"Running retrieval layer (llm_metrics={args.llm_metrics}, limit={args.limit})...")
        output["retrieval"] = run_retrieval_layer(limit=args.limit, llm_metrics=args.llm_metrics)
        print(f"  {output['retrieval']['summary']['total']} records, "
              f"{len(output['retrieval']['summary']['errors'])} errors")

    if args.layer in ("e2e", "all"):
        print(f"Running e2e layer (score={args.llm_metrics}, limit={args.limit})...")
        output["e2e"] = run_e2e_layer(limit=args.limit, score=args.llm_metrics)
        summary = output["e2e"]["summary"]
        print(f"  {summary['total_conversations']} conversations, "
              f"{summary['reached_expected_stage_pct']}% reached expected stage, "
              f"{len(summary['errors'])} errors")

    _RESULTS_DIR.mkdir(exist_ok=True)
    out_path = args.out or (_RESULTS_DIR / f"ragas-{timestamp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")

    if args.compare_baseline:
        if not _BASELINE_PATH.exists():
            raise SystemExit(f"No baseline at {_BASELINE_PATH} - run with --save-baseline first.")
        _compare_baseline(output, _BASELINE_PATH)

    if args.save_baseline:
        baseline = _extract_baseline_scores(output)
        with open(_BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(baseline, f, ensure_ascii=False, indent=2)
        print(f"Wrote {_BASELINE_PATH} (dataset_hash={baseline['dataset_hash']})")


if __name__ == "__main__":
    main()
