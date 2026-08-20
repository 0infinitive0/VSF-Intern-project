"""Import smoke test for `eval/harness/*.py`.

Catches the exact failure mode that let the RAGAS eval harness die silently
across the LangGraph cutover: `eval/run_ragas.py` imported `e2e_eval` at
module scope, `e2e_eval.py` imported three `session.py` symbols the cutover
had deleted, and nothing in `make test` noticed for weeks (see
plans/260820-1106-eval-harness-graph-cutover-restore/). This test imports
every harness module and asserts none of them raise `ImportError`.

`eval/` is a separate venv (`eval/.venv-eval`) with its own dependencies
(`ragas`, `langgraph`-pinned-differently, etc.), so this test skips --
cleanly, not a failure -- whenever `ragas` cannot be imported in whatever
environment is running `backend/tests`. That keeps the backend suite
runnable without the eval venv while still catching a deleted backend
symbol whenever this DOES run under an environment that has `ragas`
(the eval venv, or a backend env that happens to have it too).
"""

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("ragas")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVAL_DIR = _REPO_ROOT / "eval"
_HARNESS_DIR = _EVAL_DIR / "harness"


def _harness_module_names() -> list[str]:
    return sorted(f"harness.{p.stem}" for p in _HARNESS_DIR.glob("*.py") if p.stem != "__init__")


@pytest.fixture(autouse=True)
def _eval_on_path():
    """`harness/*.py` uses `from harness.x import y` -- `eval/run_ragas.py`
    makes that resolve by putting `eval/` (not `eval/harness/`) on
    `sys.path`; this fixture does the same for the duration of one test.
    """
    added = str(_EVAL_DIR) not in sys.path
    if added:
        sys.path.insert(0, str(_EVAL_DIR))
    try:
        yield
    finally:
        if added:
            sys.path.remove(str(_EVAL_DIR))


@pytest.mark.parametrize("module_name", _harness_module_names())
def test_harness_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
