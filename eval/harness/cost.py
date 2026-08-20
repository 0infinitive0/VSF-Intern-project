"""Prices the calls `usage_recorder` captured, per model and per scope.

Two rules shape everything here.

**A missing rate is an error, never `$0`.** A zero in a cost report reads as "free",
and a model that was actually called and silently priced at nothing is the one wrong
answer this module exists to prevent. `UnpricedModelError` names the model and the
number of calls it made.

**App-side and judge-side are never summed.** They answer different questions — "what
does a user turn cost" versus "what does an eval pass cost" — and one merged figure
answers neither. Scope comes from the recording context, not from the model name, so
the two staying separate does not depend on them happening to use different models.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PRICES_PATH = Path(__file__).resolve().parent.parent / "pricing" / "model-prices.json"

#: What the report prints where a dollar figure would go for an embedding model.
#: Not `0.0`, not omitted — both would read as a measurement rather than a decision.
UNPRICED_BY_DESIGN = "UNPRICED (neuron-billed)"


class UnpricedModelError(RuntimeError):
    """A chat model was called that has no rate in the price table."""


def load_price_table(path: Path | None = None) -> dict:
    return json.loads((path or _PRICES_PATH).read_text(encoding="utf-8"))


def _rate_index(table: dict) -> dict[str, dict]:
    """Every exact key a model may be reported under -> its rate entry.

    Built from canonical names plus their explicit `aliases`. Exact matching only:
    the callback reports a dated snapshot id, and prefix-matching `gpt-5` would price
    `gpt-5-mini` at `gpt-5` rates.
    """
    index: dict[str, dict] = {}
    for name, entry in table.get("models", {}).items():
        index[name] = entry
        for alias in entry.get("aliases", []):
            index[alias] = entry
    for name, entry in table.get("embeddings", {}).items():
        index[name] = entry
        for alias in entry.get("aliases", []):
            index[alias] = entry
    return index


def _tokens(call: dict) -> tuple[int, int, int, int]:
    """`(input, cached_input, output, reasoning)` for one call.

    `cached_input` and `reasoning` live in the `*_token_details` sub-dicts, which is
    why the recorder keeps `usage_metadata` whole instead of flattening it. Cached
    input is a *subset* of input tokens, so it is subtracted out before the full rate
    is applied rather than charged twice.
    """
    usage = call.get("usage_metadata") or {}
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    cached = (usage.get("input_token_details") or {}).get("cache_read") or 0
    reasoning = (usage.get("output_token_details") or {}).get("reasoning") or 0
    return input_tokens, cached, output_tokens, reasoning


def _blank_totals() -> dict[str, Any]:
    return {
        "calls": 0,
        "failed_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cost_usd": 0.0,
        "unpriced_by_design": False,
    }


def price_calls(calls: list[dict], table: dict | None = None) -> dict:
    """Aggregate `calls` into per-scope, per-model token and cost totals.

    Raises `UnpricedModelError` naming every chat model that has no rate. Embedding
    models flagged `unpriced_by_design` are exempt: their omission is a decision, not
    an oversight, and the flag is what keeps those two cases distinguishable.
    """
    table = table if table is not None else load_price_table()
    rates = _rate_index(table)

    by_scope: dict[str, dict] = {}
    missing: dict[str, int] = {}

    for call in calls:
        scope = call.get("scope") or "unknown"
        model = call.get("model") or "unknown"
        entry = rates.get(model)

        bucket = by_scope.setdefault(scope, {"models": {}, "totals": _blank_totals()})
        model_totals = bucket["models"].setdefault(model, _blank_totals())

        if call.get("error"):
            # A failed call still burned wall clock and often input tokens. Counted,
            # but never priced: what it was charged is not knowable from here.
            model_totals["failed_calls"] += 1
            bucket["totals"]["failed_calls"] += 1
            continue

        input_tokens, cached, output_tokens, reasoning = _tokens(call)
        for target in (model_totals, bucket["totals"]):
            target["calls"] += 1
            target["input_tokens"] += input_tokens
            target["cached_input_tokens"] += cached
            target["output_tokens"] += output_tokens
            target["reasoning_tokens"] += reasoning

        if entry is None:
            missing[model] = missing.get(model, 0) + 1
            continue

        if entry.get("unpriced_by_design"):
            model_totals["unpriced_by_design"] = True
            model_totals["cost_usd"] = None
            continue

        # Cached input is a subset of input_tokens, billed at its own lower rate.
        uncached = max(0, input_tokens - cached)
        cost = (
            uncached * entry["input"]
            + cached * entry.get("cached_input", entry["input"])
            + output_tokens * entry["output"]
        ) / 1_000_000
        model_totals["cost_usd"] = round((model_totals["cost_usd"] or 0.0) + cost, 6)
        bucket["totals"]["cost_usd"] = round(bucket["totals"]["cost_usd"] + cost, 6)

    if missing:
        detail = ", ".join(f"{model} ({n} call(s))" for model, n in sorted(missing.items()))
        raise UnpricedModelError(
            f"No rate in {_PRICES_PATH.name} for: {detail}. Add the model (with its dated "
            "snapshot id as an alias) and re-run. Refusing to report an unpriced model as $0 — "
            "a zero in a cost report reads as free."
        )

    return by_scope


def per_request_costs(scope_totals: dict, divisors: dict[str, int]) -> list[dict]:
    """`cost / n` for each named divisor, carrying the divisor with the figure.

    The denominator travels with the number because "cost per request" means something
    different per layer — one retrieval query, one user turn, one whole conversation —
    and a bare per-request figure is unreadable without it.
    """
    cost = scope_totals.get("cost_usd") or 0.0
    out = []
    for label, n in divisors.items():
        out.append(
            {
                "per": label,
                "divisor": n,
                "cost_usd": round(cost / n, 6) if n else None,
            }
        )
    return out


def project_cold_cache_cost(cost_this_run: float, observed_calls: int, cache_hits: int) -> dict:
    """What this run would have cost with an empty judge cache.

    **This is an extrapolation, and it is labelled as one.** A `DiskCacheBackend` hit
    fires no callback (measured, Phase 1), so its tokens were never observed and cannot
    be priced directly — the plan's original "price every call as if it had missed"
    assumed hits were visible calls, and they are not.

    Method: the mean cost of the calls that *did* reach the model, applied to the hits.
    Reasonable because judge calls on one layer are near-identical in shape, and stated
    so nobody reads it as a measurement.

    With a cold cache there are no hits, so the projection equals the measured cost and
    carries `estimated: false`.
    """
    if cache_hits == 0:
        return {"cost_usd": round(cost_this_run, 6), "estimated": False, "method": "no cache hits — measured"}
    if observed_calls == 0:
        return {
            "cost_usd": None,
            "estimated": True,
            "method": "every scoring operation was a cache hit — no observed call to extrapolate from",
        }
    mean = cost_this_run / observed_calls
    return {
        "cost_usd": round(cost_this_run + mean * cache_hits, 6),
        "estimated": True,
        "method": (
            f"measured cost of {observed_calls} observed call(s) plus the mean of those "
            f"({mean:.6f} USD) applied to {cache_hits} cache hit(s), whose tokens fire no "
            "callback and were never observed"
        ),
    }


def contains_only_safe_fields(calls: list[dict]) -> list[str]:
    """Returns the keys that would leak prompt or response text into a committed file.

    The per-call list is what makes a cost figure auditable, so it ships in the raw
    JSON — which means it must carry numbers, model names and scopes, and nothing a
    user typed.
    """
    allowed = {"scope", "model", "latency_s", "usage_metadata", "error"}
    offenders: set[str] = set()
    for call in calls:
        offenders.update(set(call) - allowed)
    return sorted(offenders)
