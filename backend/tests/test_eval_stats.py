"""Percentile aggregation for the eval report's latency tables.

Runs in the backend suite rather than the eval venv (see `test_score_state_patches.py`):
`stats.py` imports nothing but `statistics`.

These tests pin the interpolation method by asserting exact numbers. A comment saying
"inclusive" does not stop a later edit from switching to `method="exclusive"` or to
hand-rolled index arithmetic; a failing assertion does. The difference is roughly half
an observation at p95, which is invisible in review and looks like a real latency
change in a report diff.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


@pytest.fixture(scope="module")
def stats():
    spec = importlib.util.spec_from_file_location("eval_stats", _EVAL_DIR / "harness" / "stats.py")
    assert spec and spec.loader, f"could not load stats.py from {_EVAL_DIR}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_percentiles_over_a_known_sequence(stats):
    """1..100 under `statistics.quantiles(n=100, method="inclusive")`."""
    summary = stats.percentile_summary([float(v) for v in range(1, 101)])

    assert summary["n"] == 100
    assert summary["p50"] == 50.5
    assert summary["p95"] == 95.05
    assert summary["p99"] == 99.01
    assert summary["min"] == 1.0
    assert summary["max"] == 100.0
    assert summary["mean"] == 50.5
    assert summary["sum"] == 5050.0
    assert summary["method"] == "inclusive"
    assert summary["degenerate"] is False


def test_single_observation_is_degenerate_not_a_distribution(stats):
    """One sample has no spread. Report the value, flag it, invent nothing."""
    summary = stats.percentile_summary([3.25])

    assert summary["n"] == 1
    assert summary["degenerate"] is True
    assert summary["p50"] == summary["p95"] == summary["p99"] == 3.25
    assert summary["min"] == summary["max"] == 3.25


def test_empty_input_reports_nothing_rather_than_zero(stats):
    """`0.0` would read as "instant"; `None` reads as "not measured"."""
    summary = stats.percentile_summary([])

    assert summary["n"] == 0
    assert summary["degenerate"] is True
    assert summary["p50"] is None
    assert summary["max"] is None
    assert summary["sum"] is None


def test_two_observations_are_not_degenerate(stats):
    summary = stats.percentile_summary([1.0, 2.0])

    assert summary["n"] == 2
    assert summary["degenerate"] is False
    assert summary["p50"] == 1.5


def test_grouped_summary_keeps_groups_separate(stats):
    grouped = stats.grouped_percentile_summary(
        [("hotels", 1.0), ("hotels", 3.0), ("attractions", 10.0)]
    )

    assert set(grouped) == {"attractions", "hotels"}
    assert grouped["hotels"]["n"] == 2
    assert grouped["hotels"]["p50"] == 2.0
    assert grouped["attractions"]["n"] == 1
    assert grouped["attractions"]["degenerate"] is True
