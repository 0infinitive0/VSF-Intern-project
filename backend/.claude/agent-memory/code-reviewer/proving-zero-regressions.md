---
name: proving-zero-regressions
description: How to actually verify "no regressions" in this backend — failure counts are unreliable because ~44 tests fail for environment reasons; compare failing test names from a clean git worktree
metadata:
  type: feedback
---

Do not accept (or produce) a "same N failed, so zero regressions" argument for
`backend/`. Compare the *set of failing test names*, per file, against a clean
checkout in a separate `git worktree` — not aggregate counts.

**Why:** The suite carries a large block of environment-dependent failures (no
live Ollama, missing fixture files by absolute path — see [[no-real-llm-in-tests]]).
On 2026-08-13 a "44 failed both before and after" stash comparison hid a real
regression: adding a `checkpointer=` kwarg to `create_chat_session` broke a test
stub with a narrower signature, and the failure was invisible in the totals.
`SessionRegistry.get()` also wraps session construction in a bare
`except Exception`, so signature errors surface as "session unavailable" rather
than a TypeError.

**How to apply:** `git worktree add /tmp/<name> HEAD`, run the same scoped
`pytest <file>` in both trees, diff the `FAILED ...::test_name` lines, then
`git worktree remove --force`. When a change adds a parameter to a widely
stubbed factory, grep tests for monkeypatched stubs of that factory and check
each stub's signature accepts `**kwargs`.
