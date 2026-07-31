from __future__ import annotations

from pathlib import Path

from src.agents.graph import build_trip_agent
from src.agents.tools.select_hotel import build_select_hotel_tool


def test_terminal_planner_persists_complete_bundles_and_exposes_finalization() -> None:
    """The string checks below assert on services/trip_planner.py's serialization
    shape, unaffected by this phase's session rewrite — genuinely a pure
    relocation for these specific lines, so repointing the path is enough. The
    tool-list check is different: `create_react_agent` no longer takes a static
    list literal (tools are now session-bound factories), so it is converted to
    a behavioural check on build_trip_agent's bound tool names — the guard that
    generate_full_itinerary stays unregistered."""
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "services" / "trip_planner.py").read_text(encoding="utf-8")

    assert '"item_kind": item.kind' in svc
    assert '"destination_id": destination_id' in svc
    assert '"hotel_id": hotel_data["id"]' in svc
    assert "ENABLE_ITINERARY_REUSE" in svc
    assert svc.index("hotel_candidates =") < svc.index("reusable_template =")

    class _FakeSession:
        session_id = "test-session"
        pending_hotel_selection = None
        trip_data = None

    _compiled_agent, tools = build_trip_agent(_FakeSession())
    tool_names = [tool.name for tool in tools]
    assert tool_names == ["recommend_hotels", "select_hotel", "modify_trip_plan", "finalize_trip_plan"]
    assert "generate_full_itinerary" not in tool_names


def test_finalized_itinerary_is_not_mutated_by_the_edit_tool() -> None:
    """The status-check-before-parse ordering that used to live in the static
    `_legacy_modify_trip_plan` @tool now lives in the plain
    services/trip_planner.py function of the same name — a genuine relocation,
    so the source-text ordering check still applies there. Also checked
    behaviourally on the live session-bound select_hotel tool's change_hotel
    branch: picking a new hotel against an already-finalized trip must be
    refused, and trip_data must come back byte-for-byte unchanged."""
    root = Path(__file__).resolve().parents[1]
    svc = (root / "src" / "services" / "trip_planner.py").read_text(encoding="utf-8")

    assert "Kế hoạch đã xác nhận không thể chỉnh sửa" in svc
    assert svc.index("Kế hoạch đã xác nhận không thể chỉnh sửa") < svc.index(
        "_parse_trip_change(modification_request)"
    )

    finalized_trip_data = {"itineraries": [{"status": "Finalized", "id": "trip-1"}]}

    class _FakeSession:
        session_id = "test-session"
        trip_data = dict(finalized_trip_data)
        pending_hotel_selection = {
            "mode": "change_hotel",
            "destination": "Đà Nẵng",
            "options": [{"id": "h1", "name": "Hotel One", "rank": 1}],
        }
        persist_hook = None

    session = _FakeSession()
    select_hotel = build_select_hotel_tool(session)
    result = select_hotel.invoke({"selection": "1"})

    assert "không thể chỉnh sửa" in result
    assert session.trip_data == finalized_trip_data
    assert session.pending_hotel_selection is None


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
