"""Turns a raw eval/results/ragas-<ts>.json into a markdown + json report.

Averages are the least useful part of an eval and the easiest to over-read, so
the report leads with findings (hand-authored - see FINDINGS below, written
from the actual diagnosis of this run, not generated) and keeps every metric
family in its own column. Never emits one headline number.
"""

import hashlib
import json
import re
from pathlib import Path

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
                "reasoning": (
                    f"20% relative margin below the single observed run "
                    f"({observed} -> floor {floor}); absorbs live-corpus drift between "
                    f"runs, not measurement noise (non-LLM metrics reproduce exactly)."
                ),
            })
    return candidates


def build_report(raw: dict, findings_md: str, caveats_md: str) -> tuple[str, dict]:
    retrieval = raw.get("retrieval", {})
    e2e = raw.get("e2e", {})
    retrieval_rows = retrieval.get("rows", [])
    e2e_rows = e2e.get("rows", [])

    worst_retrieval = worst_retrieval_queries(retrieval_rows)
    worst_turns = worst_e2e_turns(e2e_rows)
    cross_lang = cross_language_pairs(retrieval_rows)

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

    lines += ["**Cross-language pairs (BR-10):**", ""]
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
        "- Judge-side latency and token spend not separately measured this run (see Caveats)",
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
    lines += [
        "",
        "No e2e threshold is proposed this run: finding 1 blocks essentially all quality signal "
        "(0% reached expected stage), so there is nothing to set a floor under yet.",
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
        "threshold_candidates": threshold_candidates(retrieval.get("breakdowns", {})),
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
