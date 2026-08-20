"""Percentile aggregation, shared by every latency family in the report.

One helper rather than inline arithmetic per section: percentiles computed in three
places drift in their interpolation method, and two tables that disagree by a
half-observation look like a measurement difference rather than a rounding choice.

`statistics.quantiles(..., method="inclusive")` is the stdlib's own implementation and
the method name travels in the emitted dict, so a reader never has to guess which
convention produced a number.
"""

from __future__ import annotations

import statistics

_METHOD = "inclusive"


def percentile_summary(values: list[float]) -> dict:
    """`{n, p50, p95, p99, min, max, mean, sum, method, degenerate}` over `values`.

    `degenerate` is the honesty flag. With fewer than two observations there is no
    spread to describe, so every percentile is just the one value that was measured -
    reported as such rather than dressed up as a distribution. It is also `True` for
    an empty input, where every field is `None`.

    Small `n` stays legible rather than being hidden: `n` rides along with the
    percentiles so a `p99` over 30 samples (where it is the maximum by construction)
    cannot be read as a tail estimate it cannot support.
    """
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "p50": None, "p95": None, "p99": None,
            "min": None, "max": None, "mean": None, "sum": None,
            "method": _METHOD,
            "degenerate": True,
        }

    ordered = sorted(values)
    if n == 1:
        only = round(ordered[0], 4)
        return {
            "n": 1,
            "p50": only, "p95": only, "p99": only,
            "min": only, "max": only, "mean": only, "sum": only,
            "method": _METHOD,
            "degenerate": True,
        }

    # 100 buckets -> 99 cut points, so the i-th percentile is at index i-1.
    cuts = statistics.quantiles(ordered, n=100, method=_METHOD)
    return {
        "n": n,
        "p50": round(cuts[49], 4),
        "p95": round(cuts[94], 4),
        "p99": round(cuts[98], 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(ordered), 4),
        "sum": round(sum(ordered), 4),
        "method": _METHOD,
        "degenerate": False,
    }


def grouped_percentile_summary(pairs: list[tuple[str, float]]) -> dict:
    """`percentile_summary` per group, from `(group, value)` pairs."""
    groups: dict[str, list[float]] = {}
    for group, value in pairs:
        groups.setdefault(group, []).append(value)
    return {group: percentile_summary(values) for group, values in sorted(groups.items())}
