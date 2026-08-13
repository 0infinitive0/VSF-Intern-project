"""Tests for Phase 10: score_state_patches scorer.

These run inside the backend pytest suite (not the eval venv) because the
scorer only imports from `src.domain.travel_state` (pure, no LLM) and
`pathlib`. The backend venv already has those.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Bootstrap: put the eval/ harness directory on sys.path so we can import scorer
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVAL_DIR = _REPO_ROOT / "eval"
_BACKEND_DIR = _REPO_ROOT / "backend"
_DATASETS_DIR = _EVAL_DIR / "datasets"

# The scorer adds backend/ to sys.path itself on import, but let's be explicit
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# ---------------------------------------------------------------------------
# Import scorer (without running __main__)
# ---------------------------------------------------------------------------


def _import_scorer():
    """Lazily import scorer to avoid running __main__ at import time."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "score_state_patches",
        _EVAL_DIR / "harness" / "score_state_patches.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helper to build dataset cases inline
# ---------------------------------------------------------------------------


def _case(
    utterance: str,
    patch_input: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    expected_ambiguous: bool = False,
    symptom: str | None = None,
) -> dict[str, Any]:
    return {
        "utterance": utterance,
        "context": {},
        "patch_input": patch_input,
        "expected": expected,
        "expected_ambiguous": expected_ambiguous,
        "symptom": symptom,
    }


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_strips_diacritics(self) -> None:
        scorer = _import_scorer()
        assert scorer._normalize("Đà Nẵng") == scorer._normalize("Da Nang")

    def test_casefolds(self) -> None:
        scorer = _import_scorer()
        assert scorer._normalize("BIỂN") == scorer._normalize("biển")

    def test_numeric_passthrough(self) -> None:
        scorer = _import_scorer()
        assert scorer._normalize(2000000) == 2000000

    def test_list_is_normalized_recursively(self) -> None:
        scorer = _import_scorer()
        assert scorer._normalize(["Ẩm thực", "VĂN HÓA"]) == scorer._normalize(["am thuc", "van hoa"])


# ---------------------------------------------------------------------------
# _match_changes
# ---------------------------------------------------------------------------


class TestMatchChanges:
    def test_exact_match_returns_full_tp(self) -> None:
        scorer = _import_scorer()
        produced = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        expected = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        tp, p_count, e_count = scorer._match_changes(produced, expected)
        assert tp == 1
        assert p_count == 1
        assert e_count == 1

    def test_diacritic_insensitive_match(self) -> None:
        scorer = _import_scorer()
        produced = [{"path": "destination", "operation": "set", "value": "da nang"}]
        expected = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        tp, _, _ = scorer._match_changes(produced, expected)
        assert tp == 1

    def test_wrong_value_no_tp(self) -> None:
        scorer = _import_scorer()
        produced = [{"path": "destination", "operation": "set", "value": "Hà Nội"}]
        expected = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        tp, _, _ = scorer._match_changes(produced, expected)
        assert tp == 0

    def test_wrong_path_no_tp(self) -> None:
        scorer = _import_scorer()
        produced = [{"path": "budget.max", "operation": "set", "value": 2000000}]
        expected = [{"path": "destination", "operation": "set", "value": 2000000}]
        tp, _, _ = scorer._match_changes(produced, expected)
        assert tp == 0

    def test_missing_expected_change_reduces_recall(self) -> None:
        scorer = _import_scorer()
        produced = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        expected = [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "dates.start", "operation": "set", "value": "2026-09-01"},
        ]
        tp, p_count, e_count = scorer._match_changes(produced, expected)
        assert tp == 1
        assert p_count == 1
        assert e_count == 2

    def test_extra_produced_reduces_precision(self) -> None:
        scorer = _import_scorer()
        produced = [
            {"path": "destination", "operation": "set", "value": "Đà Nẵng"},
            {"path": "dates.start", "operation": "set", "value": "2026-09-01"},
        ]
        expected = [{"path": "destination", "operation": "set", "value": "Đà Nẵng"}]
        tp, p_count, e_count = scorer._match_changes(produced, expected)
        assert tp == 1
        assert p_count == 2
        assert e_count == 1


# ---------------------------------------------------------------------------
# _score_case
# ---------------------------------------------------------------------------


class TestScoreCase:
    def test_exact_match(self) -> None:
        scorer = _import_scorer()
        case = _case(
            "tôi muốn đi Đà Nẵng",
            patch_input=[{"path": "destination", "operation": "set", "value": "Đà Nẵng"}],
            expected=[{"path": "destination", "operation": "set", "value": "Đà Nẵng"}],
        )
        result = scorer._score_case(case)
        assert result["exact_match"] == 1
        assert result["tp"] == 1
        assert result["produced"] == 1
        assert result["expected_count"] == 1

    def test_wrong_value_not_exact_match(self) -> None:
        scorer = _import_scorer()
        case = _case(
            "tôi muốn đi Hà Nội",
            patch_input=[{"path": "destination", "operation": "set", "value": "Hà Nội"}],
            expected=[{"path": "destination", "operation": "set", "value": "Đà Nẵng"}],
        )
        result = scorer._score_case(case)
        assert result["exact_match"] == 0
        assert result["tp"] == 0

    def test_empty_patch_and_expected_is_exact_match(self) -> None:
        scorer = _import_scorer()
        case = _case("bạn có thể giải phương trình không", patch_input=[], expected=[])
        result = scorer._score_case(case)
        assert result["exact_match"] == 1

    def test_ambiguous_date_flags_correctly(self) -> None:
        scorer = _import_scorer()
        case = _case(
            "ngày 01/07",
            patch_input=[{"path": "dates.start", "operation": "set", "value": "01/07"}],
            expected=[],
            expected_ambiguous=True,
        )
        result = scorer._score_case(case)
        assert result["expected_ambiguous"] is True
        # apply_patch should flag this as ambiguous (missing year)
        assert result["ambiguous_correct"] == 1

    def test_not_applicable_budget(self) -> None:
        scorer = _import_scorer()
        case = _case(
            "không có ngân sách cụ thể",
            patch_input=[{"path": "budget.max", "operation": "set", "value": None}],
            expected=[{"path": "budget.max", "operation": "set", "value": None}],
        )
        result = scorer._score_case(case)
        assert result["exact_match"] == 1

    def test_rejected_path_not_in_expected(self) -> None:
        """A path not in ALLOWED_PATHS is rejected by apply_patch — produced_applied is empty."""
        scorer = _import_scorer()
        case = _case(
            "set unknown path",
            patch_input=[{"path": "unknown.nonexistent", "operation": "set", "value": "x"}],
            expected=[],  # we expect nothing to be applied
        )
        result = scorer._score_case(case)
        assert result["produced"] == 0  # rejected, not applied
        assert result["exact_match"] == 1  # expected nothing, got nothing applied


# ---------------------------------------------------------------------------
# _aggregate
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_perfect_precision_recall(self) -> None:
        scorer = _import_scorer()
        results = [
            {"tp": 2, "produced": 2, "expected_count": 2, "exact_match": 1, "expected_ambiguous": False, "ambiguous_correct": None},
            {"tp": 1, "produced": 1, "expected_count": 1, "exact_match": 1, "expected_ambiguous": False, "ambiguous_correct": None},
        ]
        summary = scorer._aggregate(results)
        assert summary["micro_precision"] == 1.0
        assert summary["micro_recall"] == 1.0
        assert summary["micro_f1"] == 1.0
        assert summary["exact_match_rate"] == 1.0

    def test_partial_recall(self) -> None:
        scorer = _import_scorer()
        results = [
            {"tp": 1, "produced": 1, "expected_count": 2, "exact_match": 0, "expected_ambiguous": False, "ambiguous_correct": None},
        ]
        summary = scorer._aggregate(results)
        assert summary["micro_recall"] == 0.5
        assert summary["micro_precision"] == 1.0

    def test_symptom_exact_match_reported(self) -> None:
        scorer = _import_scorer()
        results = [
            {"tp": 1, "produced": 1, "expected_count": 1, "exact_match": 1,
             "expected_ambiguous": False, "ambiguous_correct": None, "symptom": "Đổi theme ngày 1"},
            {"tp": 0, "produced": 1, "expected_count": 1, "exact_match": 0,
             "expected_ambiguous": False, "ambiguous_correct": None, "symptom": "Ngân sách"},
        ]
        summary = scorer._aggregate(results)
        assert summary["symptom_exact_match"] == 0.5


# ---------------------------------------------------------------------------
# Full dataset: all 5 symptoms exist
# ---------------------------------------------------------------------------


class TestAllFiveSymptomsInDataset:
    REQUIRED_SYMPTOM_KEYWORDS = [
        "Đổi theme",       # 1: day theme not applying
        "Ngân sách",       # 2: budget gate
        "thiếu năm",       # 3: missing year ambiguity
        "thứ tự",          # 4: day/month order
        "Từ chối",         # 5: scope rejection
    ]

    def test_all_five_symptoms_present(self) -> None:
        dataset_path = _DATASETS_DIR / "state_patches.jsonl"
        if not dataset_path.exists():
            pytest.skip("state_patches.jsonl not found")

        cases = [json.loads(line) for line in dataset_path.read_text().splitlines() if line.strip()]
        symptom_texts = [str(case.get("symptom") or "") for case in cases]

        for keyword in self.REQUIRED_SYMPTOM_KEYWORDS:
            matched = any(keyword.lower() in symptom.lower() for symptom in symptom_texts)
            assert matched, (
                f"No symptom case found matching keyword {keyword!r}. "
                f"Existing symptoms: {symptom_texts}"
            )

    def test_dataset_has_at_least_fifteen_cases(self) -> None:
        dataset_path = _DATASETS_DIR / "state_patches.jsonl"
        if not dataset_path.exists():
            pytest.skip("state_patches.jsonl not found")

        cases = [line for line in dataset_path.read_text().splitlines() if line.strip()]
        assert len(cases) >= 15, f"Expected ≥15 cases; found {len(cases)}"


# ---------------------------------------------------------------------------
# run_scorer integration (in-process, no file I/O)
# ---------------------------------------------------------------------------


class TestRunScorer:
    def test_run_scorer_returns_summary_dict(self, tmp_path: Path) -> None:
        scorer = _import_scorer()
        # Point scorer at the real dataset
        dataset_path = _DATASETS_DIR / "state_patches.jsonl"
        if not dataset_path.exists():
            pytest.skip("state_patches.jsonl not found")

        output = tmp_path / "test-report.json"
        summary = scorer.run_scorer(dataset_path=dataset_path, output_path=output)

        assert isinstance(summary, dict)
        assert "micro_precision" in summary
        assert "micro_recall" in summary
        assert "micro_f1" in summary
        assert "exact_match_rate" in summary
        assert output.exists()

    def test_run_scorer_symptom_cases_all_pass(self, tmp_path: Path) -> None:
        """All five symptom cases must score exact_match=1 — they represent
        already-correct behavior that we guard as a regression signal."""
        scorer = _import_scorer()
        dataset_path = _DATASETS_DIR / "state_patches.jsonl"
        if not dataset_path.exists():
            pytest.skip("state_patches.jsonl not found")

        # Run the scorer
        output = tmp_path / "report.json"
        scorer.run_scorer(dataset_path=dataset_path, output_path=output)
        report = json.loads(output.read_text())

        symptom_cases = [c for c in report["cases"] if c.get("symptom")]
        failed = [c for c in symptom_cases if c.get("exact_match") != 1]
        assert not failed, (
            f"{len(failed)} symptom case(s) did not pass:\n"
            + "\n".join(f"  {c['symptom']}: produced={c['produced_applied']}" for c in failed)
        )
