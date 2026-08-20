"""A failed e2e conversation still leaves a readable transcript.

Before this, `write_transcript` was only called when `result.error is None`, so a
conversation that raised produced nothing but a one-line exception in the JSON --
and the JSON's per-turn rows carry worker/class/latency, not a word of what the
agent said. The turns that DID run are exactly the evidence needed to tell a
product bug from a dataset that no longer matches the graph.

`harness/transcripts.py` imports no `ragas`, so this runs in the backend venv.
"""

import sys
from pathlib import Path

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

_TURN = {
    "user_input": "Tôi muốn đi Huế trong 1 ngày từ 2026-07-01 cho 2 người.",
    "response": "Bạn muốn mức giá khách sạn khoảng nào?",
    "judged_response": "Bạn muốn mức giá khách sạn khoảng nào?",
    "worker": None,
    "turn_class": "generated",
    "hotel_pick": False,
    "asked_question": True,
    "contexts": [],
    "faithfulness": None,
    "response_relevancy": None,
}


@pytest.fixture(autouse=True)
def _eval_on_path():
    added = str(_EVAL_DIR) not in sys.path
    if added:
        sys.path.insert(0, str(_EVAL_DIR))
    try:
        yield
    finally:
        if added:
            sys.path.remove(str(_EVAL_DIR))


@pytest.fixture
def transcripts_dir(tmp_path, monkeypatch):
    """Redirect the module's output dir so the repo's real transcripts are untouched."""
    from harness import transcripts

    monkeypatch.setattr(transcripts, "_TRANSCRIPTS_DIR", tmp_path)
    return tmp_path


def test_failed_conversation_keeps_the_turns_that_ran(transcripts_dir):
    from harness.transcripts import write_transcript

    path = write_transcript(
        "conv-hue-finalize-2d",
        [_TURN],
        error="RuntimeError: no earlier turn returned hotel_options",
    )
    text = path.read_text(encoding="utf-8")

    assert "Conversation failed after 1 turn(s)." in text
    assert "no earlier turn returned hotel_options" in text
    assert _TURN["response"] in text  # the reply itself, not just the exception


def test_successful_conversation_carries_no_failure_banner(transcripts_dir):
    from harness.transcripts import write_transcript

    text = write_transcript("conv-ok", [_TURN]).read_text(encoding="utf-8")

    assert "Conversation failed" not in text
    assert _TURN["response"] in text
