---
name: project-known-test-failures
description: As of 2026-07-30, 4 pytest failures are pre-existing and unrelated to code changes — uncommitted scripts/migrations/*.sql files
metadata:
  type: project
---

As of 2026-07-30, `pytest tests/ -q` baseline is **143 passed, 4 failed**. All 4 failures are
`FileNotFoundError` on migration SQL files that exist in tests' assertions but were never
committed to `scripts/migrations/`:

- `test_itinerary_store.py::test_persistence_migration_uses_builtin_uuid_generation`
- `test_trip_intake.py::test_destination_alias_schema_and_terminal_loader_contract`
- `test_trip_reuse_flow.py::test_reuse_migration_contains_atomic_bundle_and_finalization_contracts`
- `test_trip_reuse_flow.py::test_finalization_credits_every_upstream_ancestor_once`

Only `scripts/migrations/20260727_add_itinerary_day_themes.sql` is actually committed.

**Why:** these tests assert migration-file *contents* as a schema contract, but the migrations
were authored in earlier sessions without being added to git.

**How to apply:** when reviewing a diff, treat these 4 as the baseline — do not attribute them to
the change under review. Verify the count is still exactly 4 and the same names; anything else is
a real regression. If a later session commits the missing `.sql` files, delete this memory.
