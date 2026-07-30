from __future__ import annotations

from pathlib import Path


def test_terminal_planner_persists_complete_bundles_and_exposes_finalization() -> None:
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "cli" / "trip_builder_svc.py").read_text(encoding="utf-8")
    tools = (root / "src" / "cli" / "planner_tools.py").read_text(encoding="utf-8")

    assert '"item_kind": item.kind' in svc
    assert '"destination_id": destination_id' in svc
    assert '"hotel_id": hotel_data["id"]' in svc
    assert "def finalize_trip_plan()" in tools
    assert "[recommend_hotels, select_hotel, modify_trip_plan, finalize_trip_plan]" in tools
    assert "ENABLE_ITINERARY_REUSE" in svc
    assert svc.index("hotel_candidates =") < svc.index("reusable_template =")


def test_finalized_itinerary_is_not_mutated_by_the_edit_tool() -> None:
    root = Path(__file__).resolve().parents[1]
    tools = (root / "src" / "cli" / "planner_tools.py").read_text(encoding="utf-8")

    assert "Kế hoạch đã xác nhận không thể chỉnh sửa" in tools
    assert tools.index("Kế hoạch đã xác nhận không thể chỉnh sửa") < tools.index(
        "_parse_trip_change(modification_request)"
    )


def test_reuse_migration_contains_atomic_bundle_and_finalization_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (root / "scripts" / "migrations" / "20260728_add_itinerary_reuse.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE OR REPLACE FUNCTION match_itineraries" in migration
    assert "CREATE OR REPLACE FUNCTION persist_itinerary_bundle" in migration
    assert "CREATE OR REPLACE FUNCTION finalize_itinerary" in migration
    assert "CREATE OR REPLACE FUNCTION update_itinerary_embedding" in migration
    assert "filter_hotel_id uuid" in migration
    assert "itinerary.hotel_id = filter_hotel_id" in migration
    assert "ON itineraries(destination_id, duration_days, hotel_id, status)" in migration
    assert "COALESCE(item->>'item_kind', item->>'kind')" in migration
    assert "is_embedded" not in migration
    for redundant_column in (
        "reuse_credit_applied_at",
        "finalized_at",
        "embedding_status",
        "embedding_model",
        "embedding_version",
        "embedding_content_hash",
        "embedded_at",
    ):
        assert redundant_column not in migration

    schema = (root / "scripts" / "database_schema.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema
    assert "item_kind VARCHAR(20)" in schema
    assert "embedding_status" not in schema


def test_finalization_credits_every_upstream_ancestor_once() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (root / "scripts" / "migrations" / "20260728_add_itinerary_reuse.sql").read_text(
        encoding="utf-8"
    )

    assert "WITH RECURSIVE upstream_ancestors" in migration
    assert "UNION\n" in migration
    assert "WHERE id IN (SELECT id FROM upstream_ancestors)" in migration
    assert migration.index("IF v_itinerary.status = 'Finalized'") < migration.index(
        "WITH RECURSIVE upstream_ancestors"
    )


def test_backfill_script_is_resumable_and_dry_run_safe() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "backfill_itinerary_embeddings.py").read_text(encoding="utf-8")

    assert "--dry-run" in script
    assert "--limit" in script
    assert '.is_("embedding", "null")' in script
