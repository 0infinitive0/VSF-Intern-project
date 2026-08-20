"""Rendering contract for the two strings a Faithfulness sample is made of.

An NLI judge compares text: if a retrieved context says "950,000 VND/đêm" and
the answer under test says "950.000đ/đêm", the judge can call a true statement
unsupported. `harness/context_format.py` renders both sides through one
formatter so they cannot drift; these tests pin that, plus the fact that the
retrieval layer's context string did not change shape.

No `ragas` import is involved (unlike `test_eval_harness_imports.py`), so this
runs in the plain backend venv.
"""

import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"

_HOTEL_ROW = {
    "id": "8e27710b-60eb-40b1-bbcf-dce9f514dc0f",
    "name": "Khách Sạn & Spa Emerald Bay Nha Trang",
    # numeric columns arrive as Decimal from PostgREST, float off the response model
    "star_rating": 4.0,
    "average_nightly_price": Decimal("950000"),
    "total_stay_price": Decimal("1900000"),
    "stay_night_count": 2,
    "currency": "VND",
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


def test_default_context_shape_is_unchanged():
    """Layer 1's scores were established against this exact string. Widening it
    by default would move retrieval numbers with no retrieval change behind them.
    """
    from harness.context_format import as_context

    assert as_context(_HOTEL_ROW, city="Nha Trang") == (
        "[8e27710b-60eb-40b1-bbcf-dce9f514dc0f] Khách Sạn & Spa Emerald Bay Nha Trang, Nha Trang"
    )


def test_detail_context_carries_the_numbers_the_cards_quote():
    from harness.context_format import as_context

    assert as_context(_HOTEL_ROW, detail=True) == (
        "[8e27710b-60eb-40b1-bbcf-dce9f514dc0f] Khách Sạn & Spa Emerald Bay Nha Trang"
        " — 4 sao — 950,000 VND/đêm — tổng 1,900,000 VND cho 2 đêm"
    )


def test_detail_is_a_no_op_for_rows_without_hotel_pricing():
    """`match_attractions` / `match_itineraries` rows flow through the same
    renderer and must not grow a dangling separator."""
    from harness.context_format import as_context

    row = {"id": "a12e4403-198d-4d8a-91c4-cfd547d13fa8", "name": "Tháp Bà Ponagar"}
    assert as_context(row, detail=True) == as_context(row)


def test_answer_and_context_spell_the_same_price_the_same_way():
    """The parity that makes the pairing scoreable at all."""
    from harness.context_format import as_context, hotel_options_as_answer

    option = SimpleNamespace(
        name=_HOTEL_ROW["name"],
        star_rating=4.0,
        average_nightly_price=950000.0,
        total_stay_price=1900000.0,
        stay_night_count=2,
        currency="VND",
    )
    answer = hotel_options_as_answer("Mình tìm được 1 khách sạn phù hợp.", [option])
    facts = "4 sao — 950,000 VND/đêm — tổng 1,900,000 VND cho 2 đêm"

    assert answer == f"Mình tìm được 1 khách sạn phù hợp.\n1. {_HOTEL_ROW['name']} — {facts}"
    assert facts in as_context(_HOTEL_ROW, detail=True)


def test_answer_is_the_reply_itself_when_no_cards_were_sent():
    """Intake and Q&A turns must keep scoring exactly the text they scored before."""
    from harness.context_format import hotel_options_as_answer

    assert hotel_options_as_answer("Bạn muốn đi mấy ngày?", []) == "Bạn muốn đi mấy ngày?"
