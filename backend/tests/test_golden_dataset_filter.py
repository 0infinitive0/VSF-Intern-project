"""The Vietnamese-only filter on the golden datasets.

Runs inside the backend pytest suite rather than the eval venv, following
`test_score_state_patches.py`: `dataset_loader` imports nothing but the standard
library, so it loads standalone without the harness package's `.env` bootstrap.

The regression these tests exist for is a later "simplify the filter" commit
collapsing `_is_en_mirror` to `language == "vi"`. That version passes a count check
on the conversations, quietly drops the two English-sentence BR-10 probes, and
reports as *better* scores from a smaller set — never as an error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVAL_DIR = _REPO_ROOT / "eval"

#: The BR-10 cross-language probes. Named explicitly, not derived from a prefix
#: match: the point is that these exact ids survive, and a test that recomputed
#: them from the same data the filter reads could not fail.
#: `hotel-crosslang-libertycentral-vi` was removed from the dataset entirely on
#: 2026-08-20 (user decision) — its low llm_precision/llm_context_relevance was a
#: real, already-filed retriever gap (RETRIEVER FINDING 2026-08-10, BR-10: the
#: search never surfaced the hotel for an exact-brand-name query), and it kept
#: suppressing the headline average. Down from 5 probes to 4.
_CROSSLANG_IDS = {
    "hotel-crosslang-hyatt-vi",
    "hotel-crosslang-novotel-vi",
    "hotel-crosslang-khachsan-en",
    "hotel-crosslang-khachsan-pullman-en",
}

#: The two probes whose `language` field says `en` — an English sentence carrying a
#: Vietnamese brand name ("find me a room at Khách Sạn Mường Thanh Luxury"). A mixed
#: query is a Vietnamese-user scenario, so they are in scope; a filter keyed on the
#: `language` field would delete both.
_EN_SENTENCE_CROSSLANG_IDS = {"hotel-crosslang-khachsan-en", "hotel-crosslang-khachsan-pullman-en"}


@pytest.fixture(scope="module")
def loader():
    spec = importlib.util.spec_from_file_location(
        "eval_dataset_loader", _EVAL_DIR / "harness" / "dataset_loader.py"
    )
    assert spec and spec.loader, f"could not load dataset_loader from {_EVAL_DIR}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_load_is_vietnamese_only(loader):
    assert len(loader.load_golden_retrieval()) == 23
    assert len(loader.load_golden_conversations()) == 9


def test_include_en_mirrors_restores_the_full_set(loader):
    assert len(loader.load_golden_retrieval(include_en_mirrors=True)) == 36
    assert len(loader.load_golden_conversations(include_en_mirrors=True)) == 10


def test_all_crosslang_probes_survive_a_default_load(loader):
    kept = {r.id for r in loader.load_golden_retrieval()}

    assert _CROSSLANG_IDS <= kept


def test_en_sentence_crosslang_probes_are_not_filtered_as_mirrors(loader):
    """The specific bug the filter's design exists to prevent.

    Both of these have `language == "en"`. Neither is a mirror — a mirror shares its
    `pair_id` with a `vi` record, and these hold a `pair_id` no other record uses.
    """
    kept = {r.id for r in loader.load_golden_retrieval()}

    assert _EN_SENTENCE_CROSSLANG_IDS <= kept
    assert all(r.language == "en" for r in loader.load_golden_retrieval() if r.id in _EN_SENTENCE_CROSSLANG_IDS)


def test_every_removed_record_is_a_genuine_mirror(loader):
    """Nothing is dropped except EN records that have a VI partner under one pair_id."""
    full = loader.load_golden_retrieval(include_en_mirrors=True)
    kept_ids = {r.id for r in loader.load_golden_retrieval()}
    removed = [r for r in full if r.id not in kept_ids]

    assert len(removed) == 13
    for record in removed:
        assert record.language == "en"
        partners = [o for o in full if o.pair_id == record.pair_id and o.language == "vi"]
        assert partners, f"{record.id} was removed but has no vi partner — it is not a mirror"


def test_filtering_never_deletes_from_the_files(loader):
    """The excluded records stay on disk; the loader filters at read time."""
    ids_on_disk = {r.id for r in loader.load_golden_retrieval(include_en_mirrors=True)}

    assert "hotel-nhatrang-city-en" in ids_on_disk
    assert {r.id for r in loader.load_golden_conversations(include_en_mirrors=True)} >= {"conv-hcm-luxury-en"}
