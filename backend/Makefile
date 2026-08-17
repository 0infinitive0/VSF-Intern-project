.PHONY: run test lint format typecheck check clean eval-ragas eval-state-patches

run:
	uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

check: lint format test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +

# Runs the RAGAS eval harness (../eval/) and writes a timestamped report pair
# to ../eval/results/. Isolated venv — see eval/README.md. For a report with
# hand-authored findings/caveats (recommended), run report.py directly with
# --findings/--caveats instead of chaining this target.
eval-ragas:
	../eval/.venv-eval/bin/python ../eval/run_ragas.py
	../eval/.venv-eval/bin/python ../eval/harness/report.py "$$(ls -t ../eval/results/ragas-*.json | grep -v report | head -1)"

# Runs the State Patch Accuracy scorer (Phase 10) and writes a timestamped
# report to ../eval/results/state-patches-<ts>.json.
# Pass --baseline to also commit the result as the reference baseline.
eval-state-patches:
	../eval/.venv-eval/bin/python ../eval/harness/score_state_patches.py

