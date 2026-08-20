"""Replay scripted conversations through the real graph, capture what retrieval
actually returned during each turn, and score the agent's replies for faithfulness
to those contexts.

Faithfulness is the only judged metric here. Everything else Layer 2 guarantees is an
exact comparison that fails the conversation outright — invented hotel ids, invented
itinerary places, a question answered without the data it asked for (`turn_metrics.py`).
A guarantee that reports 0.94 has already failed, and a judge that scores a
character-for-character grounded answer 0.0 (measured) cannot be one.

**Turns are driven through `turn_runner.run_turn`, the same function `routes.py`
wraps for every HTTP entry point, on purpose.** That function owns the paused-thread
resume branch, the `unresolved_resume_text` re-run, and `response_from_result`'s
interrupt shape — the same things a harness-side copy would have to reimplement and
then keep in sync forever. An eval whose turn semantics differ from production
measures the wrong system, and it does so silently, reporting numbers that look
fine. Same reasoning `context_recorder.py` documents for its `Client.rpc` patch.

Unlike calling `routes._run_turn_via_graph` directly (the first post-cutover fix
attempt, plan 260818-1650), this harness never imports `src.api.routes` at all: it
compiles its own throwaway graph with a fresh `MemorySaver` (plan
260820-1106-eval-harness-graph-cutover-restore, phase 1/3) instead of sharing the
server-lifespan app, and passes `persist=None` so there is no code path to the real
session store regardless of what `SESSION_PERSISTENCE_ENABLED` says — structural,
not a `routes._persistence_enabled` assertion at import time.

The turn's answer is read straight off the returned `PlannerChatResponse` — the exact
object the HTTP API serializes — rather than re-derived from graph state. `stage` and
`hotel_options` are what the user's client would have received, so the eval cannot
disagree with production about what happened on a turn.
"""

import time
from dataclasses import dataclass, field

from ragas import SingleTurnSample
from ragas.metrics import Faithfulness

from harness.context_format import as_context, hotel_options_as_answer
from harness.context_recorder import record_contexts
from harness.dataset_loader import ConversationRecord, load_golden_conversations
from harness.judge import build_judge
from harness.transcripts import write_transcript
from harness.turn_metrics import (
    answer_coverage,
    mentioned_items,
    scores_faithfulness,
    turn_class,
    ungrounded_hotel_ids,
    ungrounded_itinerary_places,
)
from harness.usage_recorder import note_scoring_operations, record_usage
from langgraph.checkpoint.memory import MemorySaver

from src.agents.graph.graph import build_graph
from src.agents.graph.response_payload import last_worker_from_task_results
from src.agents.graph.turn_runner import run_turn
from src.models.schemas import PlannerChatResponse
from src.services.place_details import get_hotel_detail

# Sentinel a golden-conversation turn can use instead of literal chat text, to
# mirror what the real UI actually sends when a user clicks a hotel card
# (frontend/src/components/hotel-option-card.tsx -> POST /hotels/select ->
# `selected_hotel_id` extra state, read deterministically by `hotel_node`) - never
# free text routed through the chat/LLM intent-classification path.
SELECT_FIRST_HOTEL_ACTION = "__ACTION:select_first_hotel__"


@dataclass
class TurnRecord:
    user_input: str
    response: str
    worker: str | None
    turn_class: str
    contexts: list[str]
    latency_s: float
    # What the judge is actually shown: the reply text plus the hotel cards sent
    # alongside it. Equal to `response` on every turn that carried no cards, and
    # kept separate from it so the transcript can still print the real chat text.
    judged_response: str = ""
    # Everything retrieval has returned in this conversation up to and including this
    # turn, which is the evidence set the answer is actually built from - `hotel_node`
    # carries `previous_options` forward, so the cards on screen are cumulative while a
    # single turn's RPC results are not. Judging the cumulative card list against one
    # turn's contexts scored the earlier search's hotels as unsupported: measured 0.42
    # on `conv-nhatrang-attraction-mix` turn 3, where 5 of the 10 cards had been
    # retrieved a turn earlier and were real. `contexts` above stays per-turn - it is
    # what the transcript shows, and what decides whether a turn retrieved anything.
    scoring_contexts: list[str] = field(default_factory=list)
    # Why a metric may be absent, recorded rather than re-inferred downstream:
    # a hotel-card click carries no question and no factual claims, and an intake
    # turn is the agent asking rather than answering.
    hotel_pick: bool = False
    asked_question: bool = False
    faithfulness: float | None = None
    # Fraction of the items an `answer_checks` question asked about that the reply
    # actually named, or None on a turn no check covers. Reported, not gated - naming
    # none of them is the failure, and that raises in `_replay_conversation`.
    answer_coverage: float | None = None


@dataclass
class ConversationResult:
    record: ConversationRecord
    turns: list[TurnRecord] = field(default_factory=list)
    reached_stage: str = "intake"
    harness_failure: bool = False
    transcript_path: str | None = None
    error: str | None = None


def _worker_for_turn(app, session_id: str) -> str | None:
    """The node that produced this turn's reply, or None if no worker ran.

    `load_context` resets `task_results` to `[]` at the top of every turn, so the last
    entry belongs to this turn and never leaks in from the previous one.
    """
    config = {"configurable": {"thread_id": session_id}}
    state = app.get_state(config).values or {}
    last = last_worker_from_task_results(state)
    return last[0] if last is not None else None


def _expected_answer_items(kind: str, shown_hotel_options: list) -> list[str]:
    """The true answer to an `answer_checks` question, read from the product's data.

    Deliberately not frozen into the dataset: a room list that lives in a `.jsonl` is
    wrong the day someone renames a room, and the eval would then report the agent as
    broken. `get_hotel_detail` is the same function the chat tool and `GET /hotels/{id}`
    both call, so the expectation cannot disagree with what the user is shown.

    Stay dates are left out on purpose - they change availability and price, not which
    room types the hotel HAS, which is what the question asks.
    """
    if kind == "lists_rooms_of_selected_hotel":
        if not shown_hotel_options:
            return []
        detail = get_hotel_detail(str(shown_hotel_options[0].id)) or {}
        return [str(room.get("name") or "") for room in (detail.get("rooms") or []) if room.get("name")]
    raise AssertionError(f"no resolver for answer_check kind {kind!r}")  # dataset_loader validates


def _replay_conversation(record: ConversationRecord, app) -> ConversationResult:
    # Unique per conversation: one compiled graph is cached for the whole run and all
    # conversations share it, separated only by `thread_id`. Also keeps the run's ids
    # from ever colliding with a real session's.
    session_id = f"ragas-eval-{record.id}"

    result = ConversationResult(record=record)
    response: PlannerChatResponse | None = None
    # The cards currently ON SCREEN, which is not the same as the cards the previous
    # turn returned. A user can ask something in between ("chỗ chơi cho trẻ em gần
    # khách sạn") and get a reply carrying no `hotel_options` at all - the hotel list
    # from the earlier turn is still rendered, and still clickable. Reading only the
    # previous response made `conv-nhatrang-attraction-mix` die on a click the real UI
    # allows, i.e. the harness failed a conversation the product handles.
    shown_hotel_options: list = []
    # Insertion-ordered set: dict keys, so a place retrieved again on a later turn is
    # not duplicated into the judge's context window.
    conversation_contexts: dict[str, None] = {}
    try:
        for turn_number, turn_text in enumerate(record.turns, start=1):
            hotel_pick = turn_text == SELECT_FIRST_HOTEL_ACTION
            extra_state = None
            if hotel_pick:
                if not shown_hotel_options:
                    raise RuntimeError(
                        f"{SELECT_FIRST_HOTEL_ACTION} used but no earlier turn in this "
                        "conversation returned hotel_options - one of them must retrieve "
                        "hotels first."
                    )
                extra_state = {"selected_hotel_id": str(shown_hotel_options[0].id)}

            with record_contexts() as captured:
                t0 = time.perf_counter()
                response = run_turn(
                    app, session_id, turn_text, record.language, extra_state, persist=None,
                )
                elapsed = time.perf_counter() - t0

            worker = _worker_for_turn(app, session_id)
            if response.hotel_options:
                shown_hotel_options = list(response.hotel_options)

            # `detail=True`: the answer judged below quotes the star ratings and
            # prices off the hotel cards, so the contexts have to carry them too.
            turn_contexts = [as_context(row, detail=True) for row in captured]
            conversation_contexts.update(dict.fromkeys(turn_contexts))

            # BR-07, as an assertion rather than a score: a card whose id no retrieval in
            # this conversation returned is an invented hotel, full stop. Kept out of the
            # metrics block on purpose — this is a guarantee, and a guarantee that reports
            # 0.94 has already failed.
            invented_hotels = ungrounded_hotel_ids(
                response.hotel_options, list(conversation_contexts)
            )
            if invented_hotels:
                raise RuntimeError(
                    "hotel card(s) shown that no retrieval in this conversation returned: "
                    f"{', '.join(invented_hotels)}"
                )

            # An itinerary that schedules a place retrieval never returned is the one
            # hallucination this turn can commit, and no LLM metric covers it (see
            # `turn_metrics.FAITHFULNESS_WORKERS`). Exact comparison, so it fails the
            # conversation outright rather than moving an average by a few hundredths.
            if worker == "itinerary_node":
                invented = ungrounded_itinerary_places(response.reply, list(conversation_contexts))
                if invented:
                    raise RuntimeError(
                        "itinerary scheduled place(s) no retrieval in this conversation "
                        f"returned: {', '.join(invented)}"
                    )

            # The dataset says which turn owes which information; the product's own data
            # says what the true answer is. No embedding, no judge — see
            # `turn_metrics.KNOWN_ANSWER_CHECKS` for why this replaces ResponseRelevancy
            # on the turns it covers.
            coverage = None
            for check in record.answer_checks:
                if check["turn"] != turn_number:
                    continue
                expected = _expected_answer_items(check["kind"], shown_hotel_options)
                coverage = answer_coverage(response.reply, expected)
                if expected and not mentioned_items(response.reply, expected):
                    raise RuntimeError(
                        f"turn {turn_number} answered '{check['kind']}' without naming a "
                        f"single one of the {len(expected)} item(s) in the data"
                    )

            result.turns.append(
                TurnRecord(
                    user_input=turn_text,
                    response=response.reply,
                    answer_coverage=coverage,
                    worker=worker,
                    turn_class=turn_class(worker),
                    contexts=turn_contexts,
                    scoring_contexts=list(conversation_contexts),
                    latency_s=elapsed,
                    judged_response=hotel_options_as_answer(response.reply, response.hotel_options),
                    hotel_pick=hotel_pick,
                    # No worker ran and intake is still open: the reply is `ask_slot`'s
                    # next question (possibly with an `intake_qa` answer in front of it),
                    # not an answer to the user's own question.
                    asked_question=worker is None and response.stage == "intake",
                )
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.reached_stage = "error"
        result.harness_failure = True  # an exception never reaches expected_stage - must count as a failure,
        # not the dataclass default (False), or a run full of exceptions silently reports as 100% success
        return result

    if response is not None:
        # The stage the graph itself returned, not a harness re-derivation of it.
        result.reached_stage = response.stage
    result.harness_failure = result.reached_stage != record.expected_stage
    return result


def _score_conversation(result: ConversationResult, judge) -> None:
    """Faithfulness is the only judged metric Layer 2 keeps.

    `ResponseRelevancy` was removed on 2026-08-20 (project owner's decision) rather than
    reported alongside it. It scores `cosine(user_input, question-reverse-generated-from
    -the-answer)`, which on this product measures the wrong thing in the wrong direction:
    a more complete answer produces a richer generated question, further from what the
    user typed, so completeness LOWERS the score. Its measured ceiling was 0.79, an LLM
    `noncommittal` flag zeroed it unpredictably (0.632 and 0.0 on equally good answers),
    and the turns it covered are now covered exactly by `answer_checks`. Nothing about
    answer quality went unmeasured by dropping it.
    """
    faithfulness_metric = Faithfulness(llm=judge)

    for turn in result.turns:
        # The answer the user received - caption plus cards - never the caption alone.
        # See `hotel_options_as_answer`.
        answer = turn.judged_response or turn.response

        # Which turns this can actually measure, and why, lives in `turn_metrics.py`. A
        # turn it excludes is left at None: a metric applied where its relationship does
        # not exist returns a meaningless number, not a low one, and a meaningless number
        # in a report reads as a finding.
        if scores_faithfulness(
            worker=turn.worker, hotel_pick=turn.hotel_pick, has_contexts=bool(turn.contexts)
        ):
            note_scoring_operations(1)
            turn.faithfulness = faithfulness_metric.single_turn_score(
                SingleTurnSample(
                    user_input=turn.user_input,
                    response=answer,
                    retrieved_contexts=turn.scoring_contexts or turn.contexts,
                )
            )


def run_e2e_eval(
    limit: int | None = None, score: bool = True, *, include_en_mirrors: bool = False
) -> list[ConversationResult]:
    records = load_golden_conversations(include_en_mirrors=include_en_mirrors)
    if limit:
        records = records[:limit]

    judge = build_judge() if score else None

    # One throwaway graph, one throwaway MemorySaver, for the whole run — never
    # `routes._get_graph_v2()`, which would share server-lifespan graph state.
    # Isolation between conversations comes from each getting its own `thread_id`
    # (`ragas-eval-<record.id>`), not from rebuilding the graph.
    app = build_graph(checkpointer=MemorySaver())

    results: list[ConversationResult] = []
    for record in records:
        # The product's own spend for a whole conversation, kept apart from the eval's
        # spend below. They answer different questions and are never summed.
        with record_usage(scope="app"):
            result = _replay_conversation(record, app)
        if score and result.error is None:
            with record_usage(scope="judge"):
                _score_conversation(result, judge)
        # Written for a failed conversation too. An exception is exactly when someone
        # needs to read what the agent actually said on the turns that DID run - the
        # `rows` in the JSON carry only worker/class/latency, not a word of the reply.
        path = write_transcript(
            record.id,
            [
                {
                    "user_input": t.user_input,
                    "response": t.response,
                    "judged_response": t.judged_response,
                    "worker": t.worker,
                    "turn_class": t.turn_class,
                    "hotel_pick": t.hotel_pick,
                    "asked_question": t.asked_question,
                    "contexts": t.contexts,
                    "faithfulness": t.faithfulness,
                    "answer_coverage": t.answer_coverage,
                }
                for t in result.turns
            ],
            error=result.error,
        )
        result.transcript_path = str(path)
        results.append(result)
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-score", dest="score", action="store_false", default=True)
    parser.add_argument("--include-en-mirrors", action="store_true", default=False)
    args = parser.parse_args()

    results = run_e2e_eval(limit=args.limit, score=args.score, include_en_mirrors=args.include_en_mirrors)
    for r in results:
        status = "ERROR" if r.error else ("HARNESS_FAILURE" if r.harness_failure else "ok")
        print(f"[{status}] {r.record.id:35s} reached={r.reached_stage} expected={r.record.expected_stage} "
              f"turns={len(r.turns)} error={r.error}")
