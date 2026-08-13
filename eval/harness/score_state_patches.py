"""State Patch Accuracy scorer — Phase 10.

Extends ``eval/`` without replacing it.  Runs in the existing ``eval/.venv-eval``
venv and writes results to ``eval/results/``.

## What this scores

The patch validator/acceptor layer: given a pre-built ``patch_input`` list
(the patch that ``extract_patch`` *would* have produced for this utterance),
does ``domain.travel_state.apply_patch`` accept/reject correctly?

This is deliberately **LLM-free**:
- Fast and deterministic — runnable in CI without API keys.
- Tests the right layer: the patch acceptance rules, not the LLM extraction.
- Extraction fidelity (does the LLM emit the right patch?) is measured by
  the end-to-end e2e eval; this fills the gap in the middle.

## Metrics

Per-change:
- ``precision``: fraction of produced applied changes that match expected.
- ``recall``: fraction of expected changes that were produced.

Per-utterance:
- ``exact_match``: 1 if produced changes == expected changes exactly, 0 otherwise.
- ``ambiguous_correct``: for cases with ``expected_ambiguous=true``, 1 if
  ``apply_patch`` produced a ``DateAmbiguity`` instead of applying the change.

Aggregated:
- Micro-average precision / recall / F1 over all changes.
- Utterance-level exact_match rate.

## Dataset format

See ``eval/datasets/state_patches.jsonl``:
```json
{
  "utterance": "...",
  "context": {...},
  "patch_input": [{"path": "...", "operation": "set", "value": "..."}],
  "expected": [{"path": "...", "operation": "set", "value": "..."}],
  "expected_ambiguous": false
}
```

``context`` is informational only (the scorer does not simulate a full session;
the domain-layer tests cover slot resolution).
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Bootstrap: put backend/ on sys.path so domain imports work in the eval venv
# ---------------------------------------------------------------------------
_EVAL_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _EVAL_DIR.parent / "backend"
_DATASETS_DIR = _EVAL_DIR / "datasets"
_RESULTS_DIR = _EVAL_DIR / "results"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from dotenv import load_dotenv  # type: ignore[import-untyped]

    load_dotenv(_BACKEND_DIR / ".env")
except ImportError:
    pass  # optional in pure-unit runs

from src.domain.travel_state import TravelState, apply_patch  # noqa: E402


# ---------------------------------------------------------------------------
# Normalization — diacritic-insensitive, case-insensitive
# (mirrors _normalize_for_match in hotel_selection.py)
# ---------------------------------------------------------------------------


def _normalize(value: Any) -> Any:
    """Normalize a scalar value for comparison.

    Strings: NFKD decomposition, strip combining marks, casefold, strip.
    Numbers: returned as-is (int/float comparison is exact).
    Lists: recursively normalized.
    None: returned as-is.
    """
    if isinstance(value, str):
        decomposed = unicodedata.normalize("NFKD", value.replace("Đ", "D").replace("đ", "d"))
        return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _values_match(produced: Any, expected: Any) -> bool:
    """Return True if *produced* equals *expected* after normalization."""
    if produced is None and expected is None:
        return True
    return _normalize(produced) == _normalize(expected)


# ---------------------------------------------------------------------------
# Change matching
# ---------------------------------------------------------------------------


def _change_to_key(change: dict[str, Any]) -> tuple[str, str]:
    return (change.get("path", ""), change.get("operation", ""))


def _match_changes(
    produced: list[dict[str, Any]],
    expected: list[dict[str, Any]],
) -> tuple[int, int, int]:
    """Return (true_positives, produced_count, expected_count).

    A produced change is a TP if there is an expected change with the same
    (path, operation) AND a matching value (normalized).  Each expected change
    may be matched at most once.
    """
    tp = 0
    matched_indices: set[int] = set()

    for p_change in produced:
        p_key = _change_to_key(p_change)
        p_val = p_change.get("value")
        for i, e_change in enumerate(expected):
            if i in matched_indices:
                continue
            if _change_to_key(e_change) == p_key and _values_match(p_val, e_change.get("value")):
                tp += 1
                matched_indices.add(i)
                break

    return tp, len(produced), len(expected)


# ---------------------------------------------------------------------------
# Per-case scoring
# ---------------------------------------------------------------------------


def _score_case(case: dict[str, Any]) -> dict[str, Any]:
    """Score one dataset case.  Returns a result dict."""
    utterance: str = case.get("utterance", "")
    patch_input: list[dict[str, Any]] = list(case.get("patch_input") or [])
    expected: list[dict[str, Any]] = list(case.get("expected") or [])
    expected_ambiguous: bool = bool(case.get("expected_ambiguous", False))
    symptom: str | None = case.get("symptom")

    # Run apply_patch on a fresh empty state
    state = TravelState()
    result = apply_patch(state, patch_input)

    produced_applied = [
        {"path": ch.path, "operation": ch.operation, "value": ch.value}
        for ch in result.applied
    ]
    produced_rejected = [
        {"path": r.path, "operation": r.operation, "value": r.value, "reason": r.reason}
        for r in result.rejected
    ]
    has_ambiguous = len(result.ambiguous) > 0

    # Ambiguous-expected cases: correct iff apply_patch flagged an ambiguity
    if expected_ambiguous:
        ambiguous_correct = 1 if has_ambiguous else 0
        return {
            "utterance": utterance,
            "symptom": symptom,
            "expected_ambiguous": True,
            "ambiguous_correct": ambiguous_correct,
            "tp": 0,
            "produced": 0,
            "expected_count": 0,
            "exact_match": ambiguous_correct,
            "produced_applied": produced_applied,
            "produced_rejected": produced_rejected,
            "has_ambiguous": has_ambiguous,
        }

    tp, produced_count, expected_count = _match_changes(produced_applied, expected)
    exact_match = 1 if (produced_count == expected_count == tp and tp == expected_count) else 0

    return {
        "utterance": utterance,
        "symptom": symptom,
        "expected_ambiguous": False,
        "ambiguous_correct": None,
        "tp": tp,
        "produced": produced_count,
        "expected_count": expected_count,
        "exact_match": exact_match,
        "produced_applied": produced_applied,
        "produced_rejected": produced_rejected,
        "has_ambiguous": has_ambiguous,
    }


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_tp = sum(r["tp"] for r in results)
    total_produced = sum(r["produced"] for r in results)
    total_expected = sum(r["expected_count"] for r in results)

    precision = total_tp / total_produced if total_produced else 1.0
    recall = total_tp / total_expected if total_expected else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    non_ambiguous = [r for r in results if not r["expected_ambiguous"]]
    exact_match_rate = (
        sum(r["exact_match"] for r in non_ambiguous) / len(non_ambiguous)
        if non_ambiguous
        else 1.0
    )

    ambiguous_cases = [r for r in results if r["expected_ambiguous"]]
    ambiguous_accuracy = (
        sum(r["ambiguous_correct"] for r in ambiguous_cases) / len(ambiguous_cases)
        if ambiguous_cases
        else None
    )

    symptom_cases = [r for r in results if r.get("symptom")]
    symptom_exact_match = (
        sum(r["exact_match"] for r in symptom_cases) / len(symptom_cases)
        if symptom_cases
        else None
    )

    return {
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "exact_match_rate": round(exact_match_rate, 4),
        "ambiguous_accuracy": round(ambiguous_accuracy, 4) if ambiguous_accuracy is not None else None,
        "symptom_exact_match": round(symptom_exact_match, 4) if symptom_exact_match is not None else None,
        "total_cases": len(results),
        "total_changes_expected": total_expected,
        "total_changes_produced": total_produced,
        "total_tp": total_tp,
    }


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def _write_report(results: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "state_patches.jsonl",
        "summary": summary,
        "cases": results,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))


def _print_summary(summary: dict[str, Any]) -> None:
    print("\n=== State Patch Accuracy ===")
    print(f"  Micro precision : {summary['micro_precision']:.4f}")
    print(f"  Micro recall    : {summary['micro_recall']:.4f}")
    print(f"  Micro F1        : {summary['micro_f1']:.4f}")
    print(f"  Exact match rate: {summary['exact_match_rate']:.4f}")
    if summary.get("ambiguous_accuracy") is not None:
        print(f"  Ambiguous accuracy: {summary['ambiguous_accuracy']:.4f}")
    if summary.get("symptom_exact_match") is not None:
        print(f"  Symptom exact match: {summary['symptom_exact_match']:.4f}  (regression guard)")
    print(f"  Cases: {summary['total_cases']} | "
          f"Expected changes: {summary['total_changes_expected']} | "
          f"TPs: {summary['total_tp']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_scorer(
    dataset_path: Path | None = None,
    output_path: Path | None = None,
    *,
    write_baseline: bool = False,
) -> dict[str, Any]:
    """Run the scorer and return the summary dict.

    Parameters
    ----------
    dataset_path:
        Path to the JSONL dataset.  Defaults to ``eval/datasets/state_patches.jsonl``.
    output_path:
        Path to write the timestamped JSON report.  If ``None``, a timestamped
        filename in ``eval/results/`` is used.
    write_baseline:
        If True, also write ``eval/results/state-patches-baseline.json``.
    """
    dataset_path = dataset_path or (_DATASETS_DIR / "state_patches.jsonl")
    cases = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results = [_score_case(case) for case in cases]
    summary = _aggregate(results)

    _print_summary(summary)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    if output_path is None:
        output_path = _RESULTS_DIR / f"state-patches-{ts}.json"
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    _write_report(results, summary, output_path)
    print(f"\nReport written → {output_path}")

    if write_baseline:
        baseline_path = _RESULTS_DIR / "state-patches-baseline.json"
        _write_report(results, summary, baseline_path)
        print(f"Baseline written → {baseline_path}")

    return summary


def _compare_to_baseline(summary: dict[str, Any]) -> None:
    """Print a diff against the committed baseline if one exists."""
    baseline_path = _RESULTS_DIR / "state-patches-baseline.json"
    if not baseline_path.exists():
        print("\nNo baseline found at eval/results/state-patches-baseline.json — skipping comparison.")
        return
    baseline = json.loads(baseline_path.read_text())
    b_summary = baseline.get("summary") or {}
    print("\n=== Baseline comparison ===")
    for key in ("micro_precision", "micro_recall", "micro_f1", "exact_match_rate", "symptom_exact_match"):
        current = summary.get(key)
        base = b_summary.get(key)
        if current is None or base is None:
            continue
        delta = current - base
        sign = "+" if delta >= 0 else ""
        print(f"  {key}: {base:.4f} → {current:.4f}  ({sign}{delta:.4f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score State Patch Accuracy")
    parser.add_argument("--dataset", type=Path, default=None, help="Path to JSONL dataset")
    parser.add_argument("--output", type=Path, default=None, help="Path to write report JSON")
    parser.add_argument("--baseline", action="store_true", help="Also write as baseline")
    args = parser.parse_args()

    summary = run_scorer(
        dataset_path=args.dataset,
        output_path=args.output,
        write_baseline=args.baseline,
    )
    _compare_to_baseline(summary)
