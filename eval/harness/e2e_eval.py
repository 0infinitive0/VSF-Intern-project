"""Phase 4: replay scripted conversations through the real agent, capture what
retrieval actually returned during each turn, and score the agent's replies
for faithfulness to those contexts and relevance to the user's question.
"""

import time
from dataclasses import dataclass, field

from ragas import SingleTurnSample
from ragas.metrics import Faithfulness, ResponseRelevancy

from harness.context_format import as_context
from harness.context_recorder import record_contexts
from harness.dataset_loader import ConversationRecord, load_golden_conversations
from harness.judge import build_judge, build_judge_embeddings
from harness.transcripts import write_transcript

from src.agents.session import create_chat_session, derive_stage, process_chat_turn

# Templated turns (recommend_hotels/select_hotel/finalize_trip_plan) render mostly
# from a template - faithfulness there is a grounding *regression* check (did a
# hotel name appear that was never retrieved?), not a quality score. Mixed turns
# (execute_trip_edit_request) blend both and get their own bucket so neither
# average is inflated by the other's character.
_TEMPLATE_TOOLS = {"recommend_hotels", "select_hotel", "finalize_trip_plan"}
_MIXED_TOOLS = {"execute_trip_edit_request"}


def _turn_class(tool: str | None) -> str:
    if tool in _TEMPLATE_TOOLS:
        return "template"
    if tool in _MIXED_TOOLS:
        return "mixed"
    return "generated"  # agent_stream, None, or any other value


@dataclass
class TurnRecord:
    user_input: str
    response: str
    tool: str | None
    turn_class: str
    contexts: list[str]
    latency_s: float
    faithfulness: float | None = None
    response_relevancy: float | None = None


@dataclass
class ConversationResult:
    record: ConversationRecord
    turns: list[TurnRecord] = field(default_factory=list)
    reached_stage: str = "intake"
    harness_failure: bool = False
    transcript_path: str | None = None
    error: str | None = None


def _replay_conversation(record: ConversationRecord) -> ConversationResult:
    session_id = f"ragas-eval-{record.id}"
    session = create_chat_session(session_id)  # no persist_hook - never writes to the real store

    result = ConversationResult(record=record)
    turn_result = None
    try:
        for turn_text in record.turns:
            with record_contexts() as captured:
                t0 = time.perf_counter()
                turn_result = process_chat_turn(session, turn_text, language=record.language)
                elapsed = time.perf_counter() - t0

            result.turns.append(
                TurnRecord(
                    user_input=turn_text,
                    response=turn_result.text,
                    tool=turn_result.tool,
                    turn_class=_turn_class(turn_result.tool),
                    contexts=[as_context(row) for row in captured],
                    latency_s=elapsed,
                )
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    if turn_result is not None:
        result.reached_stage = derive_stage(turn_result, session)
    result.harness_failure = result.reached_stage != record.expected_stage
    return result


def _score_conversation(result: ConversationResult, judge, embeddings) -> None:
    faithfulness_metric = Faithfulness(llm=judge)
    relevancy_metric = ResponseRelevancy(llm=judge, embeddings=embeddings)

    for turn in result.turns:
        sample_kwargs = {"user_input": turn.user_input, "response": turn.response}
        turn.response_relevancy = relevancy_metric.single_turn_score(SingleTurnSample(**sample_kwargs))

        if not turn.contexts:
            continue  # no contexts to be faithful to (pure intake question) - excluded, not scored 0
        faithfulness_sample = SingleTurnSample(
            user_input=turn.user_input, response=turn.response, retrieved_contexts=turn.contexts
        )
        turn.faithfulness = faithfulness_metric.single_turn_score(faithfulness_sample)


def run_e2e_eval(limit: int | None = None, score: bool = True) -> list[ConversationResult]:
    records = load_golden_conversations()
    if limit:
        records = records[:limit]

    judge = build_judge() if score else None
    embeddings = build_judge_embeddings() if score else None

    results: list[ConversationResult] = []
    for record in records:
        result = _replay_conversation(record)
        if score and result.error is None:
            _score_conversation(result, judge, embeddings)
        if result.error is None:
            path = write_transcript(
                record.id,
                [
                    {
                        "user_input": t.user_input,
                        "response": t.response,
                        "tool": t.tool,
                        "turn_class": t.turn_class,
                        "contexts": t.contexts,
                        "faithfulness": t.faithfulness,
                        "response_relevancy": t.response_relevancy,
                    }
                    for t in result.turns
                ],
            )
            result.transcript_path = str(path)
        results.append(result)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-score", dest="score", action="store_false", default=True)
    args = parser.parse_args()

    results = run_e2e_eval(limit=args.limit, score=args.score)
    for r in results:
        status = "ERROR" if r.error else ("HARNESS_FAILURE" if r.harness_failure else "ok")
        print(f"[{status}] {r.record.id:35s} reached={r.reached_stage} expected={r.record.expected_stage} "
              f"turns={len(r.turns)} error={r.error}")
