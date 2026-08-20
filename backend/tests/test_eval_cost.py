"""Cost computation for the eval report.

Runs in the backend suite (see `test_score_state_patches.py`); `cost.py` imports only
`json` and `pathlib`.

The behaviours pinned here are the ones whose failure mode is a *plausible wrong
number* rather than a crash: a model priced at zero because nobody noticed it was
missing, cached input billed twice, or an embedding model tripping a guard meant for
chat models. Each of those produces a report that looks finished and is wrong.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


@pytest.fixture(scope="module")
def cost():
    spec = importlib.util.spec_from_file_location("eval_cost", _EVAL_DIR / "harness" / "cost.py")
    assert spec and spec.loader, f"could not load cost.py from {_EVAL_DIR}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def table(cost):
    return cost.load_price_table()


def _call(model: str, *, scope: str = "app", input_tokens: int = 0, cached: int = 0,
          output_tokens: int = 0, reasoning: int = 0, error: str | None = None) -> dict:
    return {
        "scope": scope,
        "model": model,
        "latency_s": 1.0,
        "error": error,
        "usage_metadata": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_token_details": {"cache_read": cached},
            "output_token_details": {"reasoning": reasoning},
        },
    }


def test_cached_input_is_billed_at_its_own_rate_not_twice(cost, table):
    """`cache_read` is a SUBSET of `input_tokens`. Pricing the full input at the
    standard rate and then adding the cached portion again would overstate input cost
    on every cached call."""
    priced = cost.price_calls([_call("gpt-5.1-2025-11-13", input_tokens=1000, cached=400, output_tokens=100)], table)

    entry = table["models"]["gpt-5.1"]
    expected = (600 * entry["input"] + 400 * entry["cached_input"] + 100 * entry["output"]) / 1_000_000
    assert priced["app"]["models"]["gpt-5.1-2025-11-13"]["cost_usd"] == round(expected, 6)


def test_an_unpriced_chat_model_fails_loudly_with_its_name(cost, table):
    """The single worst outcome this module exists to prevent: a real model silently
    priced at $0, which reads as "free" rather than "unmeasured"."""
    stripped = json.loads(json.dumps(table))
    del stripped["models"]["gpt-5.1"]

    with pytest.raises(cost.UnpricedModelError) as exc:
        cost.price_calls([_call("gpt-5.1-2025-11-13", input_tokens=10, output_tokens=1)], stripped)

    assert "gpt-5.1-2025-11-13" in str(exc.value)
    assert "1 call(s)" in str(exc.value)


def test_embeddings_are_exempt_from_the_unpriced_guard(cost, table):
    """Cloudflare bills per neuron, so the omission is a decision, not an oversight —
    `unpriced_by_design` is what keeps those two cases distinguishable."""
    priced = cost.price_calls([_call("@cf/baai/bge-m3", input_tokens=5)], table)
    entry = priced["app"]["models"]["@cf/baai/bge-m3"]

    assert entry["unpriced_by_design"] is True
    assert entry["cost_usd"] is None


def test_dated_snapshot_ids_resolve_through_aliases(cost, table):
    """The callback reports `gpt-4o-mini-2024-07-18`, not `gpt-4o-mini`. Aliases are
    explicit because prefix-matching `gpt-5` would price `gpt-5-mini` at `gpt-5` rates."""
    priced = cost.price_calls(
        [_call("gpt-4o-mini-2024-07-18", scope="judge", input_tokens=1000, output_tokens=1000)], table
    )

    assert priced["judge"]["models"]["gpt-4o-mini-2024-07-18"]["cost_usd"] is not None


def test_app_and_judge_scopes_are_never_merged(cost, table):
    priced = cost.price_calls(
        [
            _call("gpt-5-mini-2025-08-07", scope="app", input_tokens=100, output_tokens=10),
            _call("gpt-4o-mini-2024-07-18", scope="judge", input_tokens=100, output_tokens=10),
        ],
        table,
    )

    assert set(priced) == {"app", "judge"}
    assert priced["app"]["totals"]["cost_usd"] != priced["judge"]["totals"]["cost_usd"]


def test_failed_calls_are_counted_but_never_priced(cost, table):
    """A failed call burned wall clock and often input tokens, but what it was charged
    is not knowable from here. Dropping it would make a run of failures look cheap."""
    priced = cost.price_calls([_call("gpt-5.1-2025-11-13", error="RateLimitError: boom")], table)
    entry = priced["app"]["models"]["gpt-5.1-2025-11-13"]

    assert entry["failed_calls"] == 1
    assert entry["calls"] == 0
    assert entry["cost_usd"] == 0.0


def test_cold_cache_projection_is_measured_when_there_are_no_hits(cost):
    projection = cost.project_cold_cache_cost(0.005, observed_calls=4, cache_hits=0)

    assert projection["estimated"] is False
    assert projection["cost_usd"] == 0.005


def test_cold_cache_projection_is_labelled_estimated_when_hits_exist(cost):
    """A cache hit fires no callback, so its tokens were never observed — the
    cold-cache figure is an extrapolation and must not be presented as a measurement."""
    projection = cost.project_cold_cache_cost(0.004, observed_calls=4, cache_hits=4)

    assert projection["estimated"] is True
    assert projection["cost_usd"] == 0.008


def test_usage_records_carry_no_prompt_or_response_text(cost):
    """The per-call list is committed to the repo as the cost audit trail. It must
    hold numbers, model names and scopes — never anything a user typed."""
    assert cost.contains_only_safe_fields([_call("gpt-5.1-2025-11-13")]) == []
    assert cost.contains_only_safe_fields([{**_call("gpt-5.1-2025-11-13"), "prompt": "hi"}]) == ["prompt"]


def test_the_committed_price_table_has_real_provenance(cost, table):
    """`as_of` + `source` are what let a reader date-check the rates; a table without
    them produces confidently wrong figures with no way to notice."""
    assert table["source"].startswith("http")
    assert table["as_of"]
    for name, entry in table["models"].items():
        for field in ("input", "cached_input", "output"):
            assert isinstance(entry[field], (int, float)), f"{name}.{field} is not a number"
