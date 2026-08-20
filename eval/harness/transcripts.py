"""Persists full per-conversation transcripts to eval/results/transcripts/ so
a wrong-looking score can be checked against exactly what the agent saw and
said, not just the aggregate number.
"""

from pathlib import Path

from harness.turn_metrics import FAITHFULNESS_WORKERS

_TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "results" / "transcripts"


def write_transcript(conversation_id: str, turns: list[dict], *, error: str | None = None) -> Path:
    """turns: list of dicts with keys user_input, response, judged_response,
    worker, turn_class, hotel_pick, asked_question, contexts (list[str]),
    faithfulness (may be None), answer_coverage (may be None).

    `error`, when the conversation died partway: the turns that did run are written
    anyway, behind a banner naming the exception, so a truncated transcript cannot be
    mistaken for a complete one.
    """
    _TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _TRANSCRIPTS_DIR / f"{conversation_id}.md"

    lines = [f"# Transcript: {conversation_id}", ""]
    if error:
        lines += [
            f"> **Conversation failed after {len(turns)} turn(s).** `{error}`",
            "> The turns below are the ones that ran before it stopped.",
            "",
        ]
    for i, turn in enumerate(turns, start=1):
        lines.append(f"## Turn {i} ({turn.get('turn_class', 'unknown')}, worker={turn.get('worker')})")
        lines.append("")
        lines.append(f"**User:** {turn['user_input']}")
        lines.append("")
        lines.append(f"**Agent:** {turn['response']}")
        lines.append("")
        # Only worth printing when the cards added something the chat text did not:
        # otherwise it repeats the line directly above it.
        judged = turn.get("judged_response")
        if judged and judged != turn["response"]:
            lines.append("**Scored answer (chat text + hotel cards sent with it):**")
            lines.append("")
            lines.append("```")
            lines.append(judged)
            lines.append("```")
            lines.append("")
        faithfulness = turn.get("faithfulness")
        # "no contexts" is only accurate when contexts are genuinely empty (a
        # pure intake question) - a hotel-pick turn can carry real contexts
        # while still being excluded (its confirmation text makes no factual
        # claims to check), so that case gets its own label instead.
        worker = turn.get("worker")
        if faithfulness is not None:
            faithfulness_label = str(faithfulness)
        elif turn.get("hotel_pick"):
            faithfulness_label = "N/A (hotel-pick confirmation - no factual claims to check)"
        elif worker is not None and worker not in FAITHFULNESS_WORKERS:
            faithfulness_label = f"N/A ({worker} quotes computed figures, not retrieved facts)"
        elif not turn.get("contexts"):
            faithfulness_label = "N/A (no contexts)"
        else:
            faithfulness_label = "N/A"

        coverage = turn.get("answer_coverage")
        scores = f"**Scores:** faithfulness={faithfulness_label}"
        if coverage is not None:
            scores += f", answer_coverage={coverage} (exact match against the data, no judge)"
        lines.append(scores)
        lines.append("")
        contexts = turn.get("contexts") or []
        if contexts:
            lines.append(f"**Retrieved contexts ({len(contexts)}):**")
            for ctx in contexts:
                lines.append(f"- {ctx}")
        else:
            lines.append("**Retrieved contexts:** none")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
