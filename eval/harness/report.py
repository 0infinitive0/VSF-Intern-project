"""Turns a raw eval/results/ragas-<ts>.json into a markdown + json report.

Averages are the least useful part of an eval and the easiest to over-read, so
the report leads with findings (hand-authored - see FINDINGS below, written
from the actual diagnosis of this run, not generated) and keeps every metric
family in its own column. Never emits one headline number.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

# `report.py` is a documented direct entry point (`eval/README.md`), so it can be run
# as a script with only its own directory on sys.path — under which `harness.*` does
# not resolve. Same bootstrap `smoke_check.py` uses, for the same reason.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.cost import UNPRICED_BY_DESIGN, load_price_table  # noqa: E402

_DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"
_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"postgres(ql)?://\S+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r'"api_key"\s*:\s*"[^"]+"', re.IGNORECASE),
]


def dataset_hash() -> str:
    """Hash of both golden dataset files' content, so a baseline comparison
    can refuse to compare across dataset versions instead of silently
    producing a meaningless diff."""
    h = hashlib.sha256()
    for name in ("golden-retrieval.jsonl", "golden-conversations.jsonl"):
        h.update((_DATASETS_DIR / name).read_bytes())
    return h.hexdigest()[:16]


def redaction_check(raw_json_text: str) -> list[str]:
    """Returns a list of pattern names that matched - should always be empty
    for committed output. Report writers must never trust review alone."""
    hits = []
    for pattern in _SECRET_PATTERNS:
        if pattern.search(raw_json_text):
            hits.append(pattern.pattern)
    return hits


def worst_retrieval_queries(retrieval_rows: list[dict], n: int = 10) -> list[dict]:
    scored = [r for r in retrieval_rows if r["non_llm_precision"] is not None or r["non_llm_recall"] is not None]

    def sort_key(r: dict) -> float:
        p = r["non_llm_precision"] or 0.0
        rc = r["non_llm_recall"] or 0.0
        return p + rc

    return sorted(scored, key=sort_key)[:n]


def worst_e2e_turns(e2e_rows: list[dict], n: int = 5) -> list[dict]:
    flat = []
    for conv in e2e_rows:
        for i, turn in enumerate(conv["turns"]):
            if turn.get("faithfulness") is not None:
                flat.append({"conversation_id": conv["id"], "turn_index": i, **turn})
    return sorted(flat, key=lambda t: t["faithfulness"])[:n]


def cross_language_pairs(retrieval_rows: list[dict]) -> list[dict]:
    """Group by pair_id and report both sides' non_llm_recall side by side -
    BR-10's actual evidence."""
    by_pair: dict[str, list[dict]] = {}
    for r in retrieval_rows:
        if r.get("pair_id"):
            by_pair.setdefault(r["pair_id"], []).append(r)
    out = []
    for pair_id, members in sorted(by_pair.items()):
        if len(members) < 2:
            continue
        out.append({
            "pair_id": pair_id,
            "members": [
                {"id": m["id"], "language": m["language"], "recall": m["non_llm_recall"]}
                for m in members
            ],
        })
    return out


#: Prefix identifying the standalone BR-10 mixed-language probes.
_CROSSLANG_PREFIX = "hotel-crosslang-"


def crosslang_probes(retrieval_rows: list[dict]) -> list[dict]:
    """BR-10's actual evidence: the standalone mixed-language probes.

    This replaces the pair-delta view for default (Vietnamese-only) runs.
    `cross_language_pairs()` groups by `pair_id` and skips any group with fewer than
    two members — with the EN mirrors filtered out every `pair_id` has exactly one
    member, so that function returns `[]` and its heading renders blank. A blank
    section reads as "cross-language retrieval is untested", when in fact these 5
    probes ran fine.

    It is also the better fit. The mirrors measured translated-query parity; BR-10 as
    the BRD states it (*hiểu truy vấn trộn VI/EN*) is about a brand name appearing in
    the query's other language, which is exactly what these probes do.
    """
    probes = [r for r in retrieval_rows if r["id"].startswith(_CROSSLANG_PREFIX)]
    out = []
    for r in sorted(probes, key=lambda r: r["id"]):
        # Direction follows the record's own `language`: the VI-labelled probes run a
        # Vietnamese sentence around an English brand name, the EN-labelled ones an
        # English sentence around a Vietnamese hotel name.
        direction = (
            "VI sentence / EN brand name" if r["language"] == "vi" else "EN sentence / VI brand name"
        )
        out.append({
            "id": r["id"],
            "direction": direction,
            "recall": r["non_llm_recall"],
            "precision": r["non_llm_precision"],
        })
    return out


def threshold_candidates(retrieval_breakdowns: dict) -> list[dict]:
    """Propose CI-viable floors from the observed non-LLM retrieval numbers only -
    LLM-judged metrics are review-time signals (cost money, vary between runs), never
    CI gates. These are PROPOSALS: roadmap phase 6/8's Open Question 4 (KPI thresholds)
    stays open: this plan observes and proposes, it does not decide.

    Margin rationale: non-LLM metrics were verified byte-identical across repeated runs
    against an unchanged corpus (measured variance = 0.0 - see baseline comparison), so
    the margin below isn't absorbing measurement noise. It's absorbing live-corpus drift
    between runs (already observed once during authoring, see eval/datasets/README.md)
    and the fact this is a single run, not a distribution. 20% relative margin below the
    observed value.
    """
    candidates = []
    for metric_key, label in [
        ("non_llm_recall_by_language", "recall"),
        ("non_llm_precision_by_language", "precision"),
    ]:
        for lang, observed in retrieval_breakdowns.get(metric_key, {}).items():
            floor = round(observed * 0.8, 4)
            candidates.append({
                "metric": f"non_llm_{label}_{lang}",
                "observed": observed,
                "measured_variance": 0.0,
                "proposed_floor": floor,
                "enforced": False,
                "reasoning": (
                    f"20% relative margin below the single observed run "
                    f"({observed} -> floor {floor}); absorbs live-corpus drift between "
                    f"runs, not measurement noise (non-LLM metrics reproduce exactly)."
                ),
            })
    return candidates


#: How loose the first latency ceiling is. 2x, not a tuned number: with one run there
#: is no measured spread to derive a margin from, and a tight ceiling picked off a
#: single observation would fail on ordinary provider variance.
_LATENCY_CEILING_MULTIPLIER = 2.0
_COST_CEILING_MULTIPLIER = 2.0


def latency_cost_candidates(raw: dict) -> list[dict]:
    """Proposed P95 latency and per-request cost ceilings. Proposals, never gates.

    Same posture `threshold_candidates` already takes for retrieval floors: observe,
    propose, state the margin's reasoning, decide nothing. Every entry carries
    `enforced: false` so the field exists the day someone turns gating on, and nobody
    has to guess whether these were ever live.

    **A judge-side cost ceiling is deliberately not proposed.** That is the eval's own
    budget; encoding it as a product constraint would be a category error.
    """
    candidates: list[dict] = []

    for layer in ("retrieval", "e2e"):
        for family, summary in (raw.get(layer, {}).get("latency", {}) or {}).items():
            overall = summary.get("overall") or {}
            observed = overall.get("p95")
            n = overall.get("n", 0)
            if observed is None or not n:
                continue
            ceiling = round(observed * _LATENCY_CEILING_MULTIPLIER, 3)
            note = (
                f"single run, no variance measured; n={n}"
                + (" and every percentile is one observation" if overall.get("degenerate") else "")
            )
            candidates.append({
                "metric": f"latency_p95_{family}",
                "observed": observed,
                "proposed_ceiling": ceiling,
                "enforced": False,
                "reasoning": (
                    f"{_LATENCY_CEILING_MULTIPLIER}x the observed p95 ({observed}s -> ceiling "
                    f"{ceiling}s). Deliberately loose: {note}, so there is no spread to derive a "
                    "tighter margin from. Tighten once several runs exist."
                ),
            })

    for layer in ("retrieval", "e2e"):
        usage = raw.get(layer, {}).get("usage") or {}
        for entry in usage.get("per_request", {}).get("app", []):
            observed = entry.get("cost_usd")
            if observed is None:
                continue
            ceiling = round(observed * _COST_CEILING_MULTIPLIER, 6)
            candidates.append({
                "metric": f"cost_usd_per_{entry['per']}_{layer}_app",
                "observed": observed,
                "proposed_ceiling": ceiling,
                "enforced": False,
                "reasoning": (
                    f"{_COST_CEILING_MULTIPLIER}x the observed app-side cost per {entry['per']} "
                    f"(n={entry['divisor']}). App-side only: a judge-side ceiling would encode the "
                    "eval's own budget as a product constraint. Token counts vary run to run "
                    "because the models are non-deterministic, so this is a budget alarm, not a "
                    "correctness gate."
                ),
            })

    return candidates


_LATENCY_FAMILY_LABELS = {
    "retrieval.search": "Retrieval search calls (agent-side, one golden query each)",
    "retrieval.judge": "Judge scoring calls during retrieval",
    "e2e.turn": "End-to-end agent turns (agent-side only)",
    "e2e.conversation": "Whole conversations (sum of their turns)",
    "e2e.judge": "Judge scoring calls during e2e",
}


def _summary_row(label: str, s: dict) -> str:
    if not s or s.get("n", 0) == 0:
        return f"| {label} | 0 | — | — | — | — | — |"
    flag = " ⚠︎" if s.get("degenerate") else ""
    return (
        f"| {label} | {s['n']}{flag} | {s['p50']} | {s['p95']} | {s['p99']} | "
        f"{s['mean']} | {s['max']} |"
    )


def latency_section(raw: dict) -> list[str]:
    """One table per family, `n` always beside the percentiles.

    Families are never pooled: a retrieval search, a judge call and a whole
    conversation have different distributions, and one percentile over all three
    describes none of them.

    Reads through `.get()` throughout — a raw file written before this section existed
    has no `latency` key at all, and the report must still build from it.
    """
    families: dict[str, dict] = {}
    for layer in ("retrieval", "e2e"):
        families.update(raw.get(layer, {}).get("latency", {}) or {})

    if not families:
        return [
            "## Latency",
            "",
            "Not measured this run — this raw file predates latency instrumentation.",
            "",
        ]

    lines = [
        "## Latency",
        "",
        "Seconds. `n` sits beside every percentile on purpose: at these sample sizes "
        "`p99` is the maximum by construction and `p95` sits on the second-worst "
        "observation, so neither is a tail estimate. ⚠︎ marks a family with fewer than "
        "two observations, where every percentile is just the one value measured.",
        "",
        f"Interpolation: `statistics.quantiles(method=\"{next(iter(families.values())).get('overall', {}).get('method', 'inclusive')}\")`.",
        "",
    ]

    for key, label in _LATENCY_FAMILY_LABELS.items():
        family = families.get(key)
        if not family:
            continue
        lines += [f"**{label}** (`{key}`)", ""]

        cache = family.get("cache")
        if cache:
            lines += [
                f"Judge cache: **{cache['state']}** — {cache['scoring_operations']} scoring "
                f"operation(s) requested, {cache['calls_observed']} reached the model, "
                f"{cache['cache_hits']} served from disk. A cache hit fires no callback and "
                "costs ~0.01s, so a warm run's numbers below describe the cache, not the judge.",
                "",
            ]

        lines += ["| group | n | p50 | p95 | p99 | mean | max |", "|---|---|---|---|---|---|---|"]
        lines.append(_summary_row("overall", family.get("overall", {})))
        for group_key, groups in family.items():
            if not group_key.startswith("by_") or not isinstance(groups, dict):
                continue
            for group_name, summary in groups.items():
                lines.append(_summary_row(f"{group_key[3:]}={group_name}", summary))
        lines.append("")

    return lines


_SCOPE_LABELS = {
    "app": "App-side — the product's own spend (what a user's request costs)",
    "judge": "Judge-side — the eval's own spend (what an eval pass costs)",
}


def _usd(value) -> str:
    if value is None:
        return UNPRICED_BY_DESIGN
    return f"${value:.6f}"


def cost_section(raw: dict) -> list[str]:
    """Token and cost totals, app-side and judge-side under separate headings.

    Never a merged total. The two answer different questions — "what does a user turn
    cost" versus "what does an eval pass cost" — and one combined figure answers
    neither, while looking like it answers both.
    """
    layers = [(name, raw.get(name, {}).get("usage")) for name in ("retrieval", "e2e")]
    layers = [(name, usage) for name, usage in layers if usage]
    if not layers:
        return [
            "## Token spend and cost",
            "",
            "Not measured this run — this raw file predates token instrumentation.",
            "",
        ]

    table = load_price_table()
    lines = [
        "## Token spend and cost",
        "",
        f"Prices: `{table['source']}`, read {table['as_of']}, {table['currency']} "
        f"{table['unit'].replace('_', ' ')}. Rates are printed below so a reader can date-check "
        "them; token counts are measured independently, so a stale rate never corrupts them.",
        "",
        "| model | input | cached input | output |",
        "|---|---|---|---|",
    ]
    for name, entry in table["models"].items():
        lines.append(f"| {name} | {entry['input']} | {entry['cached_input']} | {entry['output']} |")
    for name in table.get("embeddings", {}):
        lines.append(f"| {name} | — | — | {UNPRICED_BY_DESIGN} |")
    lines.append("")

    for layer_name, usage in layers:
        lines += [f"### Layer: {layer_name}", ""]
        for scope, bucket in sorted(usage.get("by_scope", {}).items()):
            lines += [
                f"**{_SCOPE_LABELS.get(scope, scope)}**",
                "",
                "| model | calls | input | cached in | output | reasoning | cost |",
                "|---|---|---|---|---|---|---|",
            ]
            for model, m in sorted(bucket["models"].items()):
                lines.append(
                    f"| {model} | {m['calls']} | {m['input_tokens']} | {m['cached_input_tokens']} | "
                    f"{m['output_tokens']} | {m['reasoning_tokens']} | {_usd(m['cost_usd'])} |"
                )
            t = bucket["totals"]
            lines.append(
                f"| **total** | {t['calls']} | {t['input_tokens']} | {t['cached_input_tokens']} | "
                f"{t['output_tokens']} | {t['reasoning_tokens']} | {_usd(t['cost_usd'])} |"
            )
            lines.append("")

            per_request = usage.get("per_request", {}).get(scope, [])
            if per_request:
                # The divisor rides along with every figure: "per request" means a
                # different thing per layer, and a bare number is unreadable.
                lines.append(
                    "Per request: "
                    + ", ".join(
                        f"{_usd(p['cost_usd'])} per {p['per']} (n={p['divisor']})" for p in per_request
                    )
                )
                lines.append("")

        embedding_models = set(table.get("embeddings", {}))
        seen_embeddings = {
            model
            for bucket in usage.get("by_scope", {}).values()
            for model in bucket["models"]
            if model in embedding_models
        }
        lines += [
            "**Embeddings**",
            "",
            (
                f"Models: {', '.join(sorted(seen_embeddings))}. Cost: {UNPRICED_BY_DESIGN}, and "
                "excluded from every dollar total above."
                if seen_embeddings
                else "No embedding call was captured. Measured 2026-08-18: the Cloudflare "
                "embedding path emits no LLM callback at all, and its response carries no "
                "`usage` field (keys: `data`, `model`, `object`) — so there is no token count "
                "to report, only the fact that embedding calls happen. Cost is "
                f"{UNPRICED_BY_DESIGN}: Cloudflare Workers AI bills per neuron, so a "
                "token-derived dollar figure would measure nothing."
            ),
            "",
        ]

        cache = usage.get("judge_cache", {})
        if cache and cache.get("scoring_operations"):
            cold = cache.get("cost_cold_cache", {})
            # Not `_usd()`: a None here means "not derivable", which is a different
            # statement from an embedding model's deliberate non-pricing.
            cold_usd = (
                f"${cold['cost_usd']:.6f}" if cold.get("cost_usd") is not None else "not derivable"
            )
            lines += [
                f"Judge cache **{cache['state']}**: {cache['cache_hits']} of "
                f"{cache['scoring_operations']} scoring operation(s) served from disk. "
                f"Cost this run {_usd(cache['cost_this_run_usd'])}; with a cold cache "
                f"{cold_usd} — {cold.get('method')}.",
                "",
            ]

    return lines


def build_report(raw: dict, findings_md: str, caveats_md: str) -> tuple[str, dict]:
    retrieval = raw.get("retrieval", {})
    e2e = raw.get("e2e", {})
    retrieval_rows = retrieval.get("rows", [])
    e2e_rows = e2e.get("rows", [])

    worst_retrieval = worst_retrieval_queries(retrieval_rows)
    worst_turns = worst_e2e_turns(e2e_rows)
    cross_lang = cross_language_pairs(retrieval_rows)
    probes = crosslang_probes(retrieval_rows)
    vi_only = not raw.get("run_metadata", {}).get("include_en_mirrors", False)

    lines = [
        f"# RAGAS evaluation — {raw['run_metadata']['timestamp_utc']}",
        "",
        "## What this run says",
        "",
        findings_md.strip(),
        "",
        "## Retrieval (Layer 1)",
        "",
        f"{retrieval.get('summary', {}).get('total', 0)} queries executed, "
        f"{len(retrieval.get('summary', {}).get('errors', []))} errors.",
        "",
        (
            "**Scope: Vietnamese only.** The 14 English mirror records are excluded by "
            "default, so a `by_language` breakdown holding only `vi` is the intended "
            "result, not missing data. The 5 mixed-language BR-10 probes still run — two "
            "of them are labelled `en` because they put a Vietnamese hotel name in an "
            "English sentence. `--include-en-mirrors` restores the full set."
            if vi_only
            else "**Scope: full set** — English mirrors included (`--include-en-mirrors`)."
        ),
        "",
        "**Non-LLM (deterministic) by language:**",
        "```",
        json.dumps(retrieval.get("breakdowns", {}).get("non_llm_precision_by_language", {}), indent=2),
        "```",
        "",
        "**Non-LLM by search type:**",
        "```",
        json.dumps(retrieval.get("breakdowns", {}).get("non_llm_precision_by_search", {}), indent=2),
        "```",
        "",
    ]

    if "llm_precision_by_language" in retrieval.get("breakdowns", {}):
        lines += [
            "**LLM-judged by language:**",
            "```",
            json.dumps(retrieval["breakdowns"].get("llm_precision_by_language", {}), indent=2),
            json.dumps(retrieval["breakdowns"].get("llm_context_relevance_by_language", {}), indent=2),
            "```",
            "",
        ]

    lines += ["**Mixed-language probes (BR-10):**", ""]
    if probes:
        lines += ["| id | direction | recall | precision |", "|---|---|---|---|"]
        for p in probes:
            lines.append(f"| {p['id']} | {p['direction']} | {p['recall']} | {p['precision']} |")
    else:
        lines.append("No `hotel-crosslang-*` probes in this run.")
    lines.append("")

    if cross_lang:
        # Only populated on an `--include-en-mirrors` run, where each pair_id has both
        # halves. A default VI-only run has no pairs, which is expected, not missing data.
        lines += ["**Translated-query pairs (EN mirrors, `--include-en-mirrors` runs only):**", ""]
        for pair in cross_lang:
            lines.append(f"- `{pair['pair_id']}`: " + ", ".join(
                f"{m['language']}={m['recall']}" for m in pair["members"]
            ))
        lines.append("")

    lines += ["**Worst 10 queries (non-LLM precision + recall):**", ""]
    lines.append("| id | precision | recall | cause |")
    lines.append("|---|---|---|---|")
    for r in worst_retrieval:
        lines.append(f"| {r['id']} | {r['non_llm_precision']} | {r['non_llm_recall']} | see eval/datasets/README.md adjudication log |")
    lines.append("")

    lines += [
        "## End-to-end (Layer 2)",
        "",
        f"{e2e.get('summary', {}).get('total_conversations', 0)} conversations, "
        f"{e2e.get('summary', {}).get('reached_expected_stage_pct')}% reached expected stage, "
        f"{e2e.get('summary', {}).get('excluded_no_context_turns', 0)} turns excluded (no contexts).",
        "",
        "**Faithfulness / relevancy by turn class:**",
        "```",
        json.dumps(e2e.get("breakdowns", {}), indent=2),
        "```",
        "",
        f"**Harness failures (did not reach expected_stage):** {', '.join(e2e.get('summary', {}).get('harness_failures', [])) or 'none'}",
        "",
        "**Worst 5 turns by faithfulness:**",
        "",
    ]
    if worst_turns:
        lines += ["| conversation | turn | class | faithfulness |", "|---|---|---|---|"]
        for t in worst_turns:
            lines.append(f"| {t['conversation_id']} | {t['turn_index']} | {t['turn_class']} | {t['faithfulness']} |")
    else:
        lines.append("No turns had a faithfulness score this run (see Caveats — end-to-end quality metrics are not meaningful this run).")
    lines.append("")

    retrieval_latency_s = round(sum(r["latency_s"] for r in retrieval_rows), 1)
    e2e_latency_s = round(sum(t["latency_s"] for c in e2e_rows for t in c["turns"]), 1)

    lines += latency_section(raw)
    lines += cost_section(raw)

    lines += [
        "## Run metadata",
        "",
        "- Judge model: `gpt-4o-mini`, temperature=0",
        f"- Dataset hash: `{dataset_hash()}`",
        f"- Layer: {raw['run_metadata']['layer']}, limit: {raw['run_metadata']['limit']}",
        f"- LLM metrics: {raw['run_metadata']['llm_metrics']}",
        f"- Retrieval-side latency (search calls only, excludes judge scoring): {retrieval_latency_s}s over {len(retrieval_rows)} queries",
        f"- E2E turn latency (agent calls only, excludes judge scoring): {e2e_latency_s}s over "
        f"{sum(len(c['turns']) for c in e2e_rows)} turns across {len(e2e_rows)} conversations",
        "- Sums are kept for continuity with earlier reports; the distributions behind them "
        "are in the Latency section above",
        f"- Scope: {'Vietnamese only (14 EN mirrors + conv-hcm-luxury-en excluded)' if vi_only else 'full set, EN mirrors included'}",
    ]
    price_table = load_price_table()
    lines += [
        f"- Price table: v{price_table['version']}, as_of {price_table['as_of']}, "
        f"source `{price_table['source']}`",
    ]
    for layer in ("retrieval", "e2e"):
        cache = (raw.get(layer, {}).get("usage") or {}).get("judge_cache")
        if cache:
            lines.append(
                f"- Judge cache ({layer}): {cache['state']} — {cache['cache_hits']}/"
                f"{cache['scoring_operations']} scoring operation(s) served from disk"
            )
    lines += [
        "- Corpus (verified live 2026-08-10): 5 destinations (Nha Trang, Hà Nội, Đà Nẵng, Huế, "
        "Hồ Chí Minh); ~1,103 hotels / ~1,013 attractions total in the offline fixture "
        "(`eval/fixtures/vector_bench/`), live row counts may have drifted slightly since",
        "",
        "## Threshold candidates (proposals, not gates)",
        "",
        "Roadmap Open Question 4 (KPI thresholds) stays open — these are derived proposals for "
        "the non-LLM retrieval metrics only (the only ones cheap and stable enough to be "
        "CI-viable); LLM-judged metrics stay review-time signals.",
        "",
        "| metric | observed | variance | proposed floor | reasoning |",
        "|---|---|---|---|---|",
    ]
    for c in threshold_candidates(retrieval.get("breakdowns", {})):
        lines.append(f"| {c['metric']} | {c['observed']} | {c['measured_variance']} | {c['proposed_floor']} | {c['reasoning']} |")

    perf_candidates = latency_cost_candidates(raw)
    if perf_candidates:
        lines += [
            "",
            "**Latency and cost ceilings (proposals):**",
            "",
            "| metric | observed | proposed ceiling | reasoning |",
            "|---|---|---|---|",
        ]
        for c in perf_candidates:
            lines.append(f"| {c['metric']} | {c['observed']} | {c['proposed_ceiling']} | {c['reasoning']} |")

    lines += [
        "",
        "Every candidate above carries `enforced: false` in the JSON. Nothing here gates a run.",
        "",
        "## Caveats",
        "",
        caveats_md.strip(),
        "",
    ]

    report_json = {
        "run_metadata": raw["run_metadata"],
        "dataset_hash": dataset_hash(),
        "retrieval_summary": retrieval.get("summary"),
        "retrieval_breakdowns": retrieval.get("breakdowns"),
        "worst_retrieval_queries": [r["id"] for r in worst_retrieval],
        "e2e_summary": e2e.get("summary"),
        "e2e_breakdowns": e2e.get("breakdowns"),
        "worst_e2e_turns": [(t["conversation_id"], t["turn_index"]) for t in worst_turns],
        "cross_language_pairs": cross_lang,
        "crosslang_probes": probes,
        "threshold_candidates": threshold_candidates(retrieval.get("breakdowns", {})),
        "latency_cost_candidates": latency_cost_candidates(raw),
        "latency": {
            **(raw.get("retrieval", {}).get("latency", {}) or {}),
            **(raw.get("e2e", {}).get("latency", {}) or {}),
        },
        # Aggregates only. The per-call list stays in the raw file, where it serves as
        # the audit trail; duplicating it here would double the committed bytes for
        # data nobody reads at report level.
        "usage": {
            layer: {k: v for k, v in (raw.get(layer, {}).get("usage") or {}).items() if k != "calls"}
            for layer in ("retrieval", "e2e")
            if raw.get(layer, {}).get("usage")
        },
        "price_table": {
            "version": load_price_table()["version"],
            "as_of": load_price_table()["as_of"],
            "source": load_price_table()["source"],
        },
    }

    return "\n".join(lines), report_json


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="raw ragas-<ts>.json to summarize")
    parser.add_argument("--findings", type=Path, default=None, help="hand-authored findings markdown")
    parser.add_argument("--caveats", type=Path, default=None, help="hand-authored caveats markdown")
    args = parser.parse_args()

    raw_text = args.input.read_text(encoding="utf-8")
    redaction_hits = redaction_check(raw_text)
    if redaction_hits:
        raise SystemExit(f"REDACTION CHECK FAILED: found patterns {redaction_hits} in {args.input}")

    raw = json.loads(raw_text)
    findings_md = args.findings.read_text(encoding="utf-8") if args.findings else "(no findings provided)"
    caveats_md = args.caveats.read_text(encoding="utf-8") if args.caveats else "(no caveats provided)"

    report_md, report_json = build_report(raw, findings_md, caveats_md)

    ts = raw["run_metadata"]["timestamp_utc"]
    md_path = _RESULTS_DIR / f"ragas-{ts}.md"
    json_path = _RESULTS_DIR / f"ragas-{ts}-report.json"
    md_path.write_text(report_md, encoding="utf-8")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)

    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    print("Redaction check: PASS")


if __name__ == "__main__":
    main()
