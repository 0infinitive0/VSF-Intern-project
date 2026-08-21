from evals.hotel_preference_corpus import CASES, evaluate_matcher


def test_offline_hotel_preference_corpus_quality_gate() -> None:
    assert len(CASES) == 210
    metrics = evaluate_matcher()
    assert metrics["bind_precision"] >= 0.99
    assert metrics["bind_recall"] >= 0.99
    assert metrics["silent_drop_rate"] == 0.0
