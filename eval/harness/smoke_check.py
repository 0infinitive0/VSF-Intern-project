"""Phase 1 smoke check: prove the judge wiring can actually discriminate
before any real data is involved. Run with:

    eval/.venv-eval/bin/python eval/harness/smoke_check.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ragas import SingleTurnSample  # noqa: E402
from ragas.metrics import Faithfulness, NonLLMContextPrecisionWithReference  # noqa: E402

from harness.judge import build_judge, build_judge_embeddings  # noqa: E402

FAITHFUL = SingleTurnSample(
    user_input="What is the capital of Vietnam?",
    response="The capital of Vietnam is Hanoi.",
    retrieved_contexts=["Hanoi is the capital city of Vietnam."],
)

HALLUCINATED = SingleTurnSample(
    user_input="What is the capital of Vietnam?",
    response="The capital of Vietnam is Paris, and it has a population of 30 million people.",
    retrieved_contexts=["Hanoi is the capital city of Vietnam."],
)

VIETNAMESE = SingleTurnSample(
    user_input="Thủ đô của Việt Nam là gì?",
    response="Thủ đô của Việt Nam là Hà Nội.",
    retrieved_contexts=["Hà Nội là thủ đô của Việt Nam."],
)

PRECISION_SAMPLE = SingleTurnSample(
    retrieved_contexts=["[hotel-1] Beachfront Resort"],
    reference_contexts=["[hotel-1] Beachfront Resort"],
)


def main() -> None:
    judge = build_judge()
    embeddings = build_judge_embeddings()
    print(f"embeddings backend: {type(embeddings.embeddings).__name__}")

    faithfulness = Faithfulness(llm=judge)
    precision = NonLLMContextPrecisionWithReference()

    scores = {}
    for name, sample in [("faithful", FAITHFUL), ("hallucinated", HALLUCINATED), ("vietnamese", VIETNAMESE)]:
        start = time.perf_counter()
        scores[name] = faithfulness.single_turn_score(sample)
        elapsed = time.perf_counter() - start
        print(f"faithfulness[{name}] = {scores[name]:.4f} ({elapsed:.2f}s)")

    precision_score = precision.single_turn_score(PRECISION_SAMPLE)
    print(f"non_llm_context_precision[identical] = {precision_score:.4f}")

    assert scores["faithful"] - scores["hallucinated"] >= 0.3, (
        f"judge cannot discriminate: faithful={scores['faithful']:.4f} "
        f"hallucinated={scores['hallucinated']:.4f}"
    )
    assert scores["vietnamese"] == scores["vietnamese"], "vietnamese sample returned NaN"
    print("\nOK: judge discriminates faithful vs hallucinated; Vietnamese sample scored.")


if __name__ == "__main__":
    main()
