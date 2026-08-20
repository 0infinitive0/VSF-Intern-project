"""What each e2e turn is measured by, and what each measurement refuses to cover.

Faithfulness -- Layer 2's only judged metric -- needs the answer's facts to have
come from the captured contexts. The exact checks (`ungrounded_hotel_ids`,
`ungrounded_itinerary_places`, `answer_coverage`) need the reply to name things
that exist in the product's data. Applying either where its relationship does not
hold returns a meaningless number rather than a low one, and a meaningless number
in a report reads as a finding. These tests pin the boundary.

`ResponseRelevancy` was dropped from Layer 2 on 2026-08-20; the turns it used to
score are covered by `answer_coverage`, which is why nothing here scores relevancy.

`harness/turn_metrics.py` imports no `ragas`, so this runs in the plain backend
venv (unlike `test_eval_harness_imports.py`).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


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


@pytest.mark.parametrize(
    ("worker", "expected"),
    [
        ("hotel_node", "template"),
        ("booking_node", "template"),
        ("budget_check", "template"),
        ("itinerary_node", "mixed"),
        (None, "generated"),
        ("a_node_added_after_this_map_was_written", "generated"),
    ],
)
def test_turn_class(worker, expected):
    from harness.turn_metrics import turn_class

    assert turn_class(worker) == expected


@pytest.mark.parametrize(
    ("worker", "hotel_pick", "has_contexts", "expected"),
    [
        # Facts on the cards came from the retrieval this turn recorded.
        ("hotel_node", False, True, True),
        # An itinerary reply is a schedule; its day/meal claims are unverifiable against
        # a list of place names, so it is covered by `ungrounded_itinerary_places`
        # instead of by a judge.
        ("itinerary_node", False, True, False),
        # qa_node / intake_qa write no task_results entry, so worker is None; their
        # answer is built on the contexts captured that turn.
        (None, False, True, True),
        # Computed figures: a stay total is in no retrieved context.
        ("booking_node", False, True, False),
        ("budget_check", False, True, False),
        # Nothing retrieved -> nothing to be faithful to.
        ("hotel_node", False, False, False),
        (None, False, False, False),
        # A card click's confirmation makes no factual claims of its own.
        ("hotel_node", True, True, False),
    ],
)
def test_scores_faithfulness(worker, hotel_pick, has_contexts, expected):
    from harness.turn_metrics import scores_faithfulness

    assert (
        scores_faithfulness(worker=worker, hotel_pick=hotel_pick, has_contexts=has_contexts)
        is expected
    )


_HOTEL_CONTEXTS = [
    "[8e27710b-60eb-40b1-bbcf-dce9f514dc0f] Emerald Bay — 5 sao — 850,409 VND/đêm",
    "[f9f42b85-c29e-48c6-8003-72bd0559bd2d] Starcity Bayfront — 5 sao — 1,156,790 VND/đêm",
]


def _option(hotel_id):
    return SimpleNamespace(id=hotel_id)


def test_cards_all_traced_back_to_retrieval_report_nothing():
    from harness.turn_metrics import ungrounded_hotel_ids

    options = [_option("8e27710b-60eb-40b1-bbcf-dce9f514dc0f"), _option("f9f42b85-c29e-48c6-8003-72bd0559bd2d")]

    assert ungrounded_hotel_ids(options, _HOTEL_CONTEXTS) == ()


def test_an_invented_hotel_card_is_named():
    """BR-07's real guarantee. Faithfulness cannot be trusted with it: measured 0.0 on a
    turn whose five cards matched their contexts character for character."""
    from harness.turn_metrics import ungrounded_hotel_ids

    options = [_option("8e27710b-60eb-40b1-bbcf-dce9f514dc0f"), _option("00000000-0000-0000-0000-000000000000")]

    assert ungrounded_hotel_ids(options, _HOTEL_CONTEXTS) == ("00000000-0000-0000-0000-000000000000",)


def test_a_card_retrieved_on_an_earlier_turn_is_still_grounded():
    """`hotel_node` carries `previous_options` forward, so the check runs against the
    conversation's cumulative contexts — not the turn's own."""
    from harness.turn_metrics import ungrounded_hotel_ids

    earlier_only = [_HOTEL_CONTEXTS[0]]

    assert ungrounded_hotel_ids([_option("8e27710b-60eb-40b1-bbcf-dce9f514dc0f")], earlier_only) == ()


def test_a_turn_with_no_cards_reports_nothing():
    from harness.turn_metrics import ungrounded_hotel_ids

    assert ungrounded_hotel_ids([], _HOTEL_CONTEXTS) == ()
    assert ungrounded_hotel_ids(None, _HOTEL_CONTEXTS) == ()


_ITINERARY_REPLY = (
    "Ngày 1: Ăn sáng tại Cơm Cậu Cả, Tham quan Công viên Văn hoá Lê Thị Riêng, "
    "Nghỉ ngơi tại Eastin Grand Hotel Saigon.\n"
    "Đã dựng xong lịch trình 2 ngày quanh Eastin Grand Hotel Saigon."
)
_ITINERARY_CONTEXTS = [
    "[9d5a2101-3706-5637-8e4a-68aacc275bc4] Cơm Cậu Cả",
    "[1abd8a1b-79a5-5a92-8b76-172a16f2504c] Công viên Văn hoá Lê Thị Riêng",
    "[f8ac2e3a-9b43-4f52-a452-c89d2a41423c] Eastin Grand Hotel Saigon — 5 sao — 2,000,000 VND/đêm",
]


def test_a_fully_retrieved_itinerary_reports_nothing_ungrounded():
    from harness.turn_metrics import ungrounded_itinerary_places

    assert ungrounded_itinerary_places(_ITINERARY_REPLY, _ITINERARY_CONTEXTS) == ()


def test_an_invented_place_in_the_itinerary_is_named():
    """The hallucination this turn can actually commit, and the one no LLM metric here
    covers — RAGAS scores the schedule's day/meal claims, which no context can support."""
    from harness.turn_metrics import ungrounded_itinerary_places

    reply = _ITINERARY_REPLY.replace("Cơm Cậu Cả", "Nhà Hàng Không Tồn Tại")

    assert ungrounded_itinerary_places(reply, _ITINERARY_CONTEXTS) == ("Nhà Hàng Không Tồn Tại",)


def test_an_itinerary_the_parser_cannot_read_is_reported_not_passed():
    """A template change must turn this check loud, not off."""
    from harness.turn_metrics import ungrounded_itinerary_places

    assert ungrounded_itinerary_places("Ngày 1: xong rồi nhé", _ITINERARY_CONTEXTS) == (
        "<unparsed itinerary reply>",
    )


def test_a_reply_that_is_not_an_itinerary_is_left_alone():
    from harness.turn_metrics import ungrounded_itinerary_places

    assert ungrounded_itinerary_places("Mình tìm được 5 khách sạn phù hợp.", []) == ()


_ROOMS = [
    "Phòng Deluxe Giường Đôi Hướng Phố (Deluxe City View Double Room)",
    "Grand Deluxe",
    "Suite Hướng biển",
]


def test_coverage_counts_a_room_named_by_either_half_of_its_bilingual_name():
    """Room names are stored bilingually. An answer using only the Vietnamese half names
    the same room — counting it as missing would report a correct answer as incomplete."""
    from harness.turn_metrics import answer_coverage

    reply = "Khách sạn có Phòng Deluxe Giường Đôi Hướng Phố và Grand Deluxe."

    assert answer_coverage(reply, _ROOMS) == pytest.approx(2 / 3)


def test_coverage_matches_on_the_english_half_too():
    from harness.turn_metrics import mentioned_items

    reply = "Available: Deluxe City View Double Room."

    assert mentioned_items(reply, _ROOMS) == (_ROOMS[0],)


def test_an_answer_naming_no_real_room_covers_nothing():
    """The failure the check exists to catch: the question went unanswered, or was
    answered with rooms that do not exist."""
    from harness.turn_metrics import answer_coverage, mentioned_items

    reply = "Mình chưa có thông tin phòng cho khách sạn này."

    assert mentioned_items(reply, _ROOMS) == ()
    assert answer_coverage(reply, _ROOMS) == 0.0


def test_coverage_is_none_when_there_is_nothing_to_cover():
    """No rooms in the data is not a 0% answer — it is not a measurement at all."""
    from harness.turn_metrics import answer_coverage

    assert answer_coverage("bất kỳ câu trả lời nào", []) is None
