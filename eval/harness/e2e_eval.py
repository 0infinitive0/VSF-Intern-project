"""Phase 4: replay scripted conversations through the real agent, capture what
retrieval actually returned during each turn, and score the agent's replies
for faithfulness to those contexts and relevance to the user's question.
"""

import time
from dataclasses import dataclass, field

from ragas import SingleTurnSample
from ragas.metrics import Faithfulness, ResponseRelevancy

from harness.context_format import as_context, context_id
from harness.context_recorder import record_contexts
from harness.dataset_loader import ConversationRecord, load_golden_conversations
from harness.judge import build_judge, build_judge_embeddings
from harness.transcripts import write_transcript

from src.agents.session import create_chat_session, derive_stage, handle_frontend_hotel_selection, process_chat_turn

# Sentinel a golden-conversation turn can use instead of literal chat text, to
# mirror what the real UI actually sends when a user clicks a hotel card
# (frontend/src/components/hotel-option-card.tsx -> POST /hotels/select ->
# handle_frontend_hotel_selection(session, hotel_id) with the exact ID) -
# never free text routed through the chat/LLM intent-classification path.
SELECT_FIRST_HOTEL_ACTION = "__ACTION:select_first_hotel__"

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
    hotel_grounding: float | None = None


@dataclass
class ConversationResult:
    record: ConversationRecord
    turns: list[TurnRecord] = field(default_factory=list)
    reached_stage: str = "intake"
    harness_failure: bool = False
    transcript_path: str | None = None
    error: str | None = None


def _hotel_grounding_ratio(session, cumulative_context_ids: set[str]) -> float | None:
    """Deterministic BR-07 grounding check: of the hotels currently shown to the
    user (session.pending_hotel_selection.options), what fraction have actually
    been returned by a real retrieval call at some point in this conversation?
    Exact ID comparison, no LLM/judge involved - this is what the templated
    recommend_hotels/select_hotel replies (a fixed "check the Hotels tab"
    sentence with no hotel facts of its own) make RAGAS's text-based
    Faithfulness metric structurally unable to check (see eval/README.md)."""
    options = (session.pending_hotel_selection or {}).get("options") or []
    option_ids = [str(opt.get("id") or opt.get("hotel_id") or "") for opt in options if opt.get("id") or opt.get("hotel_id")]
    if not option_ids:
        return None
    grounded = sum(1 for oid in option_ids if oid in cumulative_context_ids)
    return grounded / len(option_ids)


def _replay_conversation(record: ConversationRecord) -> ConversationResult:
    session_id = f"ragas-eval-{record.id}"
    session = create_chat_session(session_id)  # no persist_hook - never writes to the real store

    result = ConversationResult(record=record)
    turn_result = None
    cumulative_context_ids: set[str] = set()
    try:
        for turn_text in record.turns:
            with record_contexts() as captured:
                t0 = time.perf_counter()
                if turn_text == SELECT_FIRST_HOTEL_ACTION:
                    options = (session.pending_hotel_selection or {}).get("options") or []
                    if not options:
                        raise RuntimeError(
                            f"{SELECT_FIRST_HOTEL_ACTION} used but pending_hotel_selection has no "
                            "options - the prior turn must have retrieved hotels first."
                        )
                    hotel_id = str(options[0].get("id") or options[0].get("hotel_id") or "")
                    turn_result = handle_frontend_hotel_selection(session, hotel_id)
                else:
                    turn_result = process_chat_turn(session, turn_text, language=record.language)
                elapsed = time.perf_counter() - t0

            turn_contexts = [as_context(row) for row in captured]
            cumulative_context_ids.update(cid for ctx in turn_contexts if (cid := context_id(ctx)))

            grounding = None
            if turn_result.tool in ("recommend_hotels", "select_hotel"):
                grounding = _hotel_grounding_ratio(session, cumulative_context_ids)

            result.turns.append(
                TurnRecord(
                    user_input=turn_text,
                    response=turn_result.text,
                    tool=turn_result.tool,
                    turn_class=_turn_class(turn_result.tool),
                    contexts=turn_contexts,
                    latency_s=elapsed,
                    hotel_grounding=grounding,
                )
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.reached_stage = "error"
        result.harness_failure = True  # an exception never reaches expected_stage - must count as a failure,
        # not the dataclass default (False), or a run full of exceptions silently reports as 100% success
        return result

    if turn_result is not None:
        result.reached_stage = derive_stage(turn_result, session)
    result.harness_failure = result.reached_stage != record.expected_stage
    return result


def _score_conversation(result: ConversationResult, judge, embeddings) -> None:
    faithfulness_metric = Faithfulness(llm=judge)
    relevancy_metric = ResponseRelevancy(llm=judge, embeddings=embeddings)

    for turn in result.turns:
        if turn.tool == "select_hotel":
            # select_hotel's response is a generic confirmation ("itinerary is
            # ready, check the tab") with no factual claims of its own, and its
            # user_input is the SELECT_FIRST_HOTEL_ACTION sentinel, not a real
            # question - both metrics score a structural 0.0 here regardless of
            # answer quality, which reads as "hallucinating" when it's actually
            # "nothing to check". Excluded, not scored 0.
            continue

        if turn.tool is None:
            # A tool=None turn in this flow is the agent asking its own
            # clarifying intake question back to the user (e.g. "how many
            # people?"), not answering one. ResponseRelevancy scores a
            # *question* against the user's prior statement structurally low
            # regardless of how appropriate the question actually was -
            # excluded, not scored as if it were a real (low) answer.
            pass
        else:
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
                        "hotel_grounding": t.hotel_grounding,
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
