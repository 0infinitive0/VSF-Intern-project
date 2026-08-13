---
name: lint-type-baselines-are-red
description: backend/ ruff and mypy baselines are heavily red (~961 ruff, ~59 mypy errors), so "clean lint/type run" is not a usable review gate — diff against the baseline instead
metadata:
  type: project
---

`make lint` (`ruff check src/ tests/`) and `make typecheck` (`mypy src/`) both
fail hard on the existing tree — roughly 961 ruff findings and ~59 mypy errors
across pre-existing modules as of 2026-08-13. Neither is enforced in CI.

**Why:** The rules (`ruff.toml` selects E,F,I,N,W,UP) were adopted after most of
the code was written, so a raw run tells you nothing about the change under
review and burns budget if you report it as a blocker.

**How to apply:** When reviewing, run ruff/mypy scoped to the *changed paths*
only and report the delta, ranked Low unless a type error implies a real runtime
path (e.g. `with_structured_output` returning `dict | BaseModel` means an
attribute access can raise and silently take a fallback branch). Same
diff-not-totals discipline as [[proving-zero-regressions]].
