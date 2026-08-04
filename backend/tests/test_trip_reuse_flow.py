from __future__ import annotations

from pathlib import Path

from src.agents.state import initial_state
from src.agents.tools.direct_invoke import invoke_tool_directly
from src.agents.tools.select_hotel import select_hotel


def test_terminal_planner_persists_complete_bundles_and_exposes_finalization() -> None:
    """Asserts on services/trip_planner.py's serialization shape — unaffected
    by this phase's tool rewrite, a pure relocation for these specific lines,
    so repointing the path is enough.

    The tool-name/registration check that used to live here was deleted in
    Phase 4 (260802-1437-langgraph-full-orchestration-and-durable-state),
    per validation decision 1: it asserted `"generate_full_itinerary" not in
    tool_names` against a per-session bound tool list that no longer exists
    as a mechanism — after this phase's rewrite it would pass while checking
    nothing. Phase 2's characterization suite (tests/test_chat_turn_
    characterization.py) pins the INVARIANT instead: no sequence of turns
    produces an itinerary while a hotel selection is pending and unresolved."""
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "services" / "trip_planner.py").read_text(encoding="utf-8")

    assert '"item_kind": item.kind' in svc
    assert '"destination_id": destination_id' in svc
    assert '"hotel_id": hotel_data["id"]' in svc
    assert "ENABLE_ITINERARY_REUSE" in svc
    assert svc.index("hotel_candidates =") < svc.index("reusable_template =")


def test_finalized_itinerary_is_not_mutated_by_the_edit_tool() -> None:
    """The status-check-before-parse ordering that used to live in the static
    `_legacy_modify_trip_plan` @tool now lives in the plain
    services/trip_planner.py function of the same name — a genuine relocation,
    so the source-text ordering check still applies there. Also checked
    behaviourally on the real module-level select_hotel tool's change_hotel
    branch (Phase 4: no more session-bound factory, driven via
    invoke_tool_directly the same way process_chat_turn's deterministic
    cascade does): picking a new hotel against an already-finalized trip
    must be refused, and trip_data must come back byte-for-byte unchanged."""
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "services" / "trip_planner.py").read_text(encoding="utf-8")

    assert "Kế hoạch đã xác nhận không thể chỉnh sửa" in svc
    assert svc.index("Kế hoạch đã xác nhận không thể chỉnh sửa") < svc.index(
        "_parse_trip_change(modification_request)"
    )

    finalized_trip_data = {"itineraries": [{"status": "Finalized", "id": "trip-1"}]}

    state = initial_state("test-session")
    state["trip_data"] = dict(finalized_trip_data)
    state["pending_hotel_selection"] = {
        "mode": "change_hotel",
        "destination": "Đà Nẵng",
        "options": [{"id": "h1", "name": "Hotel One", "rank": 1}],
    }

    reply, updates = invoke_tool_directly(select_hotel, state, session_id="test-session", selection="1")

    assert "không thể chỉnh sửa" in reply
    assert updates["trip_data"] == finalized_trip_data
    assert updates["pending_hotel_selection"] is None


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
    assert "filter_planning_constraints jsonb" in migration
    assert "itinerary.hotel_id = filter_hotel_id" in migration
    assert "itinerary.planning_constraints = filter_planning_constraints" in migration
    assert "ON itineraries(destination_id, duration_days, hotel_id, status)" in migration
    assert "COALESCE(item->>'item_kind', item->>'kind')" in migration
    assert "Finalized itinerary % is immutable" in migration
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
    assert "planning_constraints" in script
