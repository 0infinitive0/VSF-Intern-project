#!/usr/bin/env python3
"""CLI entry for the RAGAS eval harness. Run with eval/.venv-eval/bin/python.

    eval/.venv-eval/bin/python eval/run_ragas.py --layer retrieval --limit 5 --no-llm-metrics
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.report import dataset_hash  # noqa: E402
from harness.retrieval_eval import RetrievalResult, run_retrieval_eval  # noqa: E402
from harness.cost import (  # noqa: E402
    contains_only_safe_fields,
    per_request_costs,
    price_calls,
    project_cold_cache_cost,
)
from harness.stats import grouped_percentile_summary, percentile_summary  # noqa: E402
from harness.usage_recorder import (  # noqa: E402
    assert_streaming_usage_enabled,
    cache_hits_from,
    cache_state,
    take_usage,
)

if TYPE_CHECKING:
    from harness.e2e_eval import ConversationResult

_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_BASELINE_PATH = _RESULTS_DIR / "baseline.json"


def _load_e2e():
    """Import Layer 2 lazily, on the branch that actually needs it.

    `--layer retrieval` has no business loading the e2e runner at all — the old
    top-level `from harness.e2e_eval import ...` is what turned one broken layer
    into a dead CLI across the graph cutover (see
    plans/260820-1106-eval-harness-graph-cutover-restore/phase-02-...). Kept even
    though `e2e_eval.py` imports cleanly again today: the point is a future
    refactor that breaks it again fails loudly and scoped, not by killing
    `--help`.
    """
    try:
        from harness.e2e_eval import ConversationResult, run_e2e_eval
    except ImportError as exc:
        raise SystemExit(
            f"The e2e layer is unavailable: {exc}\n"
            "Layer 2 targets the graph turn runner; see "
            "plans/260820-1106-eval-harness-graph-cutover-restore/."
        ) from exc
    return ConversationResult, run_e2e_eval


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
        "llm_average_excluded": r.record.llm_average_excluded,
    }


def _breakdown(rows: list[dict], key: str, metric: str) -> dict:
    groups: dict[str, list[float]] = {}
    for row in rows:
        val = row.get(metric)
        if val is None:
            continue
        groups.setdefault(row[key], []).append(val)
    return {k: round(sum(v) / len(v), 4) for k, v in groups.items() if v}


def _priced_usage(usage: dict, divisors: dict[str, int]) -> dict:
    """Token and cost aggregates for one layer, app-side and judge-side kept apart.

    The full per-call list ships alongside the aggregates: a cost figure nobody can
    recompute is a cost figure nobody can check, the same reason per-record
    `latency_s` stays on every row.
    """
    calls = usage["calls"]
    leaked = contains_only_safe_fields(calls)
    if leaked:
        # The per-call list is committed to the repo. A prompt or reply leaking into it
        # would publish user text under the guise of a metrics block.
        raise SystemExit(f"usage records carry unexpected field(s) {leaked} — refusing to write prompt/response text")

    by_scope = price_calls(calls)

    judge_calls = sum(1 for c in calls if c["scope"] == "judge")
    hits = cache_hits_from(usage["scoring_operations"], judge_calls)
    judge_cost = (by_scope.get("judge", {}).get("totals", {}) or {}).get("cost_usd") or 0.0

    return {
        "calls": calls,
        "by_scope": by_scope,
        "per_request": {
            scope: per_request_costs(bucket["totals"], divisors)
            for scope, bucket in by_scope.items()
        },
        "judge_cache": {
            "scoring_operations": usage["scoring_operations"],
            "calls_observed": judge_calls,
            "cache_hits": hits,
            "state": cache_state(usage["scoring_operations"], judge_calls),
            "cost_this_run_usd": round(judge_cost, 6),
            "cost_cold_cache": project_cold_cache_cost(judge_cost, judge_calls, hits),
        },
    }


def _judge_latency_family(usage: dict) -> dict:
    """Judge-call latency plus the cache state that makes it readable.

    A `DiskCacheBackend` hit answers in ~0.01s against ~2s cold and fires no callback
    at all, so it is invisible here except as a scoring operation with no matching
    call. Without the cache block below, a warm run's judge p50 measures the disk.
    """
    judge_calls = [c for c in usage["calls"] if c["scope"] == "judge" and c["latency_s"] is not None]
    ops = usage["scoring_operations"]
    return {
        "overall": percentile_summary([c["latency_s"] for c in judge_calls]),
        "cache": {
            "scoring_operations": ops,
            "calls_observed": len(judge_calls),
            "cache_hits": cache_hits_from(ops, len(judge_calls)),
            "state": cache_state(ops, len(judge_calls)),
        },
    }


def run_retrieval_layer(limit: int | None, llm_metrics: bool, include_en_mirrors: bool = False) -> dict:
    results = run_retrieval_eval(limit=limit, llm_metrics=llm_metrics, include_en_mirrors=include_en_mirrors)
    # Drained per layer, immediately after it runs: retrieval and e2e have different
    # distributions and are never pooled.
    usage = take_usage()
    rows = [_retrieval_result_to_dict(r) for r in results]

    breakdowns = {
        "non_llm_precision_by_language": _breakdown(rows, "language", "non_llm_precision"),
        "non_llm_recall_by_language": _breakdown(rows, "language", "non_llm_recall"),
        "non_llm_precision_by_search": _breakdown(rows, "search", "non_llm_precision"),
        "non_llm_recall_by_search": _breakdown(rows, "search", "non_llm_recall"),
    }
    if llm_metrics:
        # Known-finding records (negative-test probes that SHOULD score low, and
        # already-filed retriever gaps like the un-surfaced brand-name query) are
        # excluded here only - they still run every time and their own scores
        # stay on their row, but a deliberately-low or already-tracked score
        # should not keep suppressing the headline average meant to summarise
        # overall LLM-judged quality. Non-LLM precision/recall above are exact ID
        # comparisons and stay meaningful for every record, so those are not
        # filtered. ADJUDICATED 2026-08-20, user decision.
        scored_rows = [row for row in rows if not row["llm_average_excluded"]]
        breakdowns["llm_precision_by_language"] = _breakdown(scored_rows, "language", "llm_precision")
        breakdowns["llm_context_relevance_by_language"] = _breakdown(
            scored_rows, "language", "llm_context_relevance"
        )

    errors = [row["id"] for row in rows if row["error"]]
    filter_fallbacks = [row["id"] for row in rows if row["filter_fallback"]]

    return {
        "rows": rows,
        "breakdowns": breakdowns,
        # Per-record `latency_s` stays on every row above: a percentile nobody can
        # recompute from the raw data is a number nobody can audit.
        "latency": {
            "retrieval.search": {
                "overall": percentile_summary([r["latency_s"] for r in rows]),
                "by_search": grouped_percentile_summary([(r["search"], r["latency_s"]) for r in rows]),
                "by_language": grouped_percentile_summary([(r["language"], r["latency_s"]) for r in rows]),
            },
            "retrieval.judge": _judge_latency_family(usage),
        },
        # "per request" for Layer 1 is one golden retrieval query.
        "usage": _priced_usage(usage, {"query": len(rows)}),
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
                "worker": t.worker,
                "has_contexts": bool(t.contexts),
                "faithfulness": _nan_safe(t.faithfulness),
                "answer_coverage": _nan_safe(t.answer_coverage),
                "latency_s": round(t.latency_s, 3),
            }
            for t in r.turns
        ],
    }


def _turn_metric_breakdown(conversations: list[dict], metric: str) -> dict:
    """`{turn_class: {"mean": x, "n": k}}` over conversations that did NOT harness-fail
    - a conversation that never reached its expected stage shouldn't count toward a
    quality average (see plan's Phase 4 non-functional requirement).

    `n` ships with every mean because the two are unreadable apart at this suite's
    size: metrics are skipped on most turns by design (card clicks, agent questions,
    computed-figure workers), so a `template` mean can be one single observation, and
    a bare `0.9524` gives a reader no way to tell that from an average over thirty.
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
    return {
        k: {"mean": round(sum(v) / len(v), 4), "n": len(v)} for k, v in groups.items() if v
    }


def run_e2e_layer(limit: int | None, score: bool, include_en_mirrors: bool = False) -> dict:
    _, run_e2e_eval = _load_e2e()
    results = run_e2e_eval(limit=limit, score=score, include_en_mirrors=include_en_mirrors)
    usage = take_usage()
    rows = [_conversation_result_to_dict(r) for r in results]

    total_turns = sum(len(r["turns"]) for r in rows)
    excluded_no_context_turns = sum(
        1 for r in rows for t in r["turns"] if not t["has_contexts"]
    )
    harness_failures = [r["id"] for r in rows if r["harness_failure"]]
    errors = [r["id"] for r in rows if r["error"]]

    turn_latencies = [t["latency_s"] for r in rows for t in r["turns"]]

    return {
        "rows": rows,
        "breakdowns": {
            "faithfulness_by_turn_class": _turn_metric_breakdown(rows, "faithfulness"),
        },
        "latency": {
            "e2e.turn": {
                "overall": percentile_summary(turn_latencies),
                "by_turn_class": grouped_percentile_summary(
                    [(t["turn_class"], t["latency_s"]) for r in rows for t in r["turns"]]
                ),
            },
            # Its own family, not derivable from the turn percentiles: a user waits
            # through a whole conversation, and a per-turn p95 hides one that is
            # merely mediocre on every single turn.
            "e2e.conversation": {
                "overall": percentile_summary(
                    [sum(t["latency_s"] for t in r["turns"]) for r in rows if r["turns"]]
                ),
            },
            "e2e.judge": _judge_latency_family(usage),
        },
        # Layer 2 has two meaningful denominators, so both are emitted rather than
        # picking one and leaving the reader to guess which.
        "usage": _priced_usage(usage, {"turn": total_turns, "conversation": len(rows)}),
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


#: Bumped when the baseline gains or loses a top-level key. A reader can then tell a
#: pre-extension baseline from a post-extension one directly, instead of inferring it
#: from which keys happen to be missing.
#: 1 = per-record quality scores + dataset_hash (original)
#: 2 = adds `latency` and `usage`
_BASELINE_SCHEMA_VERSION = 2


def _extract_baseline_scores(output: dict) -> dict:
    """Per-record scores keyed by golden-record id, plus the dataset hash they
    were scored against - the minimum needed for a meaningful delta later."""
    baseline: dict = {
        "baseline_schema_version": _BASELINE_SCHEMA_VERSION,
        "dataset_hash": dataset_hash(),
        "retrieval": {},
        "e2e": {},
        # Frozen for reference, never as a pass/fail reference: latency moves with
        # network and provider load, and token counts move because the models are
        # non-deterministic. `_compare_baseline` labels both accordingly.
        "latency": {
            layer: output.get(layer, {}).get("latency", {})
            for layer in ("retrieval", "e2e")
            if output.get(layer, {}).get("latency")
        },
        "usage": {
            layer: {
                scope: bucket["totals"]
                for scope, bucket in (output.get(layer, {}).get("usage", {}).get("by_scope", {})).items()
            }
            for layer in ("retrieval", "e2e")
            if output.get(layer, {}).get("usage")
        },
    }
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

    _print_informational_deltas(output, baseline)


def _pct_delta(base, current) -> str:
    if base in (None, 0) or current is None:
        return "n/a"
    return f"{(current - base) / base * 100:+.1f}%"


def _print_informational_deltas(output: dict, baseline: dict) -> None:
    """Latency and cost movement — printed, explicitly not a regression signal.

    Retrieval `non_llm_precision` above is an exact ID comparison that reproduces
    byte-identically, so any delta there is signal. These two are not: latency tracks
    network and provider load, and token counts vary because the models are
    non-deterministic. Framing a 15% p95 movement the way a 0.05 precision drop is
    framed would produce noise every run, and a reader who learns to ignore one section
    of a comparison soon ignores all of it.
    """
    if not baseline.get("latency") and not baseline.get("usage"):
        print("\n--- Latency/cost comparison: baseline predates these fields (schema v"
              f"{baseline.get('baseline_schema_version', 1)}), nothing to diff ---")
        return

    print("\n--- Latency and cost deltas (INFORMATIONAL — not a regression signal) ---")
    for layer, families in (baseline.get("latency") or {}).items():
        current_families = output.get(layer, {}).get("latency", {})
        for family, base_summary in families.items():
            base_p95 = (base_summary.get("overall") or {}).get("p95")
            cur_p95 = ((current_families.get(family) or {}).get("overall") or {}).get("p95")
            print(f"  {family} p95: {base_p95} -> {cur_p95} ({_pct_delta(base_p95, cur_p95)})")

    for layer, scopes in (baseline.get("usage") or {}).items():
        current_scopes = output.get(layer, {}).get("usage", {}).get("by_scope", {})
        for scope, base_totals in scopes.items():
            cur_totals = (current_scopes.get(scope) or {}).get("totals", {})
            for field in ("cost_usd", "input_tokens", "output_tokens"):
                base_v, cur_v = base_totals.get(field), cur_totals.get(field)
                print(f"  {layer}/{scope} {field}: {base_v} -> {cur_v} ({_pct_delta(base_v, cur_v)})")


def _compact_summary(output: dict) -> dict:
    """Just llm_precision, llm_context_relevance, latency, and cost, per layer -
    the numbers asked for most often when reviewing a run, without wading through
    per-record rows. Never a replacement for the full file (whose rows are what
    makes a number auditable in the first place) - written alongside it, not
    instead of it.

    `llm_precision`/`llm_context_relevance` are retrieval-only concepts (Layer 2
    scores faithfulness instead), so an e2e-only
    run's summary omits those two keys rather than printing them as null.
    """
    summary: dict = {"run_metadata": output["run_metadata"]}
    for layer in ("retrieval", "e2e"):
        layer_output = output.get(layer)
        if not layer_output:
            continue
        breakdowns = layer_output.get("breakdowns", {})
        layer_summary = {
            "llm_precision_by_language": breakdowns.get("llm_precision_by_language"),
            "llm_context_relevance_by_language": breakdowns.get("llm_context_relevance_by_language"),
            "latency": layer_output.get("latency"),
            "cost": {
                scope: bucket.get("totals")
                for scope, bucket in (layer_output.get("usage", {}).get("by_scope", {})).items()
            },
        }
        summary[layer] = {k: v for k, v in layer_summary.items() if v}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", choices=["retrieval", "e2e", "all"], default="all")
    parser.add_argument("--limit", type=int, default=None, help="cap records per layer, for cheap iteration")
    parser.add_argument("--llm-metrics", dest="llm_metrics", action="store_true", default=True)
    parser.add_argument("--no-llm-metrics", dest="llm_metrics", action="store_false")
    parser.add_argument("--out", type=Path, default=None, help="override the output .json path")
    parser.add_argument("--save-baseline", action="store_true", help="freeze this run as eval/results/baseline.json")
    parser.add_argument("--compare-baseline", action="store_true", help="diff this run against eval/results/baseline.json")
    parser.add_argument(
        "--include-en-mirrors",
        action="store_true",
        default=False,
        help="restore the 14 EN mirror records and conv-hcm-luxury-en (default: Vietnamese only). "
             "The 5 hotel-crosslang-* BR-10 probes run either way.",
    )
    args = parser.parse_args()

    # Before anything is measured: a misconfigured endpoint would zero the cost of
    # every streaming-node turn without raising, and the run would look complete.
    assert_streaming_usage_enabled()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    output: dict = {
        "run_metadata": {
            "timestamp_utc": timestamp,
            "layer": args.layer,
            "limit": args.limit,
            "llm_metrics": args.llm_metrics,
            # Recorded because it changes which records the numbers below describe -
            # a report that omits it is not comparable with one that used the other
            # setting, and nothing else in the file would say so.
            "include_en_mirrors": args.include_en_mirrors,
        }
    }

    if args.layer in ("retrieval", "all"):
        print(f"Running retrieval layer (llm_metrics={args.llm_metrics}, limit={args.limit})...")
        output["retrieval"] = run_retrieval_layer(
            limit=args.limit, llm_metrics=args.llm_metrics, include_en_mirrors=args.include_en_mirrors
        )
        print(f"  {output['retrieval']['summary']['total']} records, "
              f"{len(output['retrieval']['summary']['errors'])} errors")

    if args.layer in ("e2e", "all"):
        print(f"Running e2e layer (score={args.llm_metrics}, limit={args.limit})...")
        output["e2e"] = run_e2e_layer(
            limit=args.limit, score=args.llm_metrics, include_en_mirrors=args.include_en_mirrors
        )
        summary = output["e2e"]["summary"]
        print(f"  {summary['total_conversations']} conversations, "
              f"{summary['reached_expected_stage_pct']}% reached expected stage, "
              f"{len(summary['errors'])} errors")

    _RESULTS_DIR.mkdir(exist_ok=True)
    out_path = args.out or (_RESULTS_DIR / f"ragas-{timestamp}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")

    summary_path = out_path.with_name(f"{out_path.stem}-summary{out_path.suffix}")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(_compact_summary(output), f, ensure_ascii=False, indent=2)
    print(f"Wrote {summary_path}")

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
