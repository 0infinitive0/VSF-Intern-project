"""Persists full per-conversation transcripts to eval/results/transcripts/ so
a wrong-looking score can be checked against exactly what the agent saw and
said, not just the aggregate number.
"""

from pathlib import Path

_TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "results" / "transcripts"


def write_transcript(conversation_id: str, turns: list[dict]) -> Path:
    """turns: list of dicts with keys user_input, response, tool, turn_class,
    contexts (list[str]), faithfulness, response_relevancy (scores may be None).
    """
    _TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _TRANSCRIPTS_DIR / f"{conversation_id}.md"

    lines = [f"# Transcript: {conversation_id}", ""]
    for i, turn in enumerate(turns, start=1):
        lines.append(f"## Turn {i} ({turn.get('turn_class', 'unknown')}, tool={turn.get('tool')})")
        lines.append("")
        lines.append(f"**User:** {turn['user_input']}")
        lines.append("")
        lines.append(f"**Agent:** {turn['response']}")
        lines.append("")
        faithfulness = turn.get("faithfulness")
        relevancy = turn.get("response_relevancy")
        # "no contexts" is only accurate when contexts are genuinely empty (a
        # pure intake question) - a select_hotel turn can carry real contexts
        # while still being excluded (its confirmation text makes no factual
        # claims to check), so that case gets its own label instead.
        if faithfulness is not None:
            faithfulness_label = str(faithfulness)
        elif turn.get("tool") == "select_hotel":
            faithfulness_label = "N/A (select_hotel confirmation - no factual claims to check)"
        elif not turn.get("contexts"):
            faithfulness_label = "N/A (no contexts)"
        else:
            faithfulness_label = "N/A"

        if relevancy is not None:
            relevancy_label = str(relevancy)
        elif turn.get("tool") == "select_hotel":
            relevancy_label = "N/A (select_hotel confirmation - no factual claims to check)"
        elif turn.get("tool") is None:
            relevancy_label = "N/A (agent asking a clarifying question, not answering one)"
        else:
            relevancy_label = "N/A"
        grounding = turn.get("hotel_grounding")
        grounding_label = f"{grounding} (deterministic ID check, see eval/README.md)" if grounding is not None else "N/A"
        lines.append(
            f"**Scores:** faithfulness={faithfulness_label}, response_relevancy={relevancy_label}, "
            f"hotel_grounding={grounding_label}"
        )
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
