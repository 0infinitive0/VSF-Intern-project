"""Tests for admin Overview (A3) -- src/api/admin/overview.py
(phase-17-overview-kpi.md). Mocked at the `orders`/`embedding`/`pipelines`
module-function boundary (same idiom as test_admin_pipelines.py mocking
`airflow_client`) -- this module makes zero Supabase/Airflow calls of its
own, so there is nothing lower-level to fake here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.api.admin import embedding as embedding_module
from src.api.admin import orders as orders_module
from src.api.admin import overview as overview_module
from src.api.admin import pipelines as pipelines_module
from src.auth import AdminUser, require_admin
from src.main import app


@pytest.fixture
def admin_override():
    app.dependency_overrides[require_admin] = lambda: AdminUser(id="admin-1", email="admin@vsftrip.vn")
    yield
    app.dependency_overrides.pop(require_admin, None)


def _order_stats(**overrides):
    base = orders_module.OrderStatsResponse(
        orders_today=18,
        orders_yesterday=14,
        confirmed_today=12,
        pending_today=6,
        revenue_today="62400000.00",
        currency="VND",
        avg_order_value="3466667.00",
        pending_count=7,
        pending_over_2h=2,
        expiring_holds_30m=3,
    )
    return base.model_copy(update=overrides)


def _order_row(**overrides):
    row = {
        "payment_id": "11111111-1111-1111-1111-111111111111",
        "guest_name": "Trần Quốc Bảo",
        "guest_email": "bao.tran@vsf.dev",
        "amount": "1850000.00",
        "booking_status": "PENDING",
        "payment_status": "PENDING",
        "needs_attention": False,
        "earliest_expires_at": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# overview.py writes zero SQL/PostgREST queries of its own (this phase's own
# success criterion) -- mechanically enforced, not just eyeballed.
# ---------------------------------------------------------------------------


def test_overview_module_never_calls_get_supabase_client_directly():
    source = Path(overview_module.__file__).read_text()
    assert "get_supabase_client" not in source
    assert "import supabase" not in source.lower()


# ---------------------------------------------------------------------------
# Per-block failure isolation -- one block raising must not blank the rest
# ---------------------------------------------------------------------------


def test_orders_block_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "get_order_stats", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_orders_block() is None


def test_attention_orders_returns_empty_list_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_attention_orders() == []


def test_expiring_holds_returns_empty_list_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "fetch_unpaid_bookings", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_expiring_holds() == []


def test_embedding_block_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(embedding_module, "get_embedding_summary", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_embedding_block() is None


def test_pipeline_block_returns_connected_false_object_not_none_when_airflow_down(monkeypatch):
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: pipelines_module.PipelinesListResponse(connected=False, items=[], reason="airflow_unavailable"))
    result = overview_module._fetch_pipeline_block()
    assert result is not None
    assert result.connected is False


@pytest.mark.asyncio
async def test_route_returns_200_even_when_every_block_fails(client, admin_override, monkeypatch):
    """The whole point of per-block try/except: a bad day for every single
    dependency still doesn't 500 the landing page."""
    monkeypatch.setattr(orders_module, "get_order_stats", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(orders_module, "fetch_unpaid_bookings", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(embedding_module, "get_embedding_summary", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    response = await client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["orders"] is None
    assert body["attention_orders"] == []
    assert body["expiring_holds"] == []
    assert body["embedding"] is None
    assert body["pipeline"] is None


# ---------------------------------------------------------------------------
# Route reuses Phase 4/12/14 as-is
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_reuses_order_stats_verbatim(client, admin_override, monkeypatch):
    monkeypatch.setattr(orders_module, "get_order_stats", lambda: _order_stats())
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([], 0))
    monkeypatch.setattr(orders_module, "fetch_unpaid_bookings", lambda **kwargs: ([], 0))
    monkeypatch.setattr(embedding_module, "get_embedding_summary", lambda: embedding_module.EmbeddingSummaryResponse(tables=[], total_missing=0))
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: pipelines_module.PipelinesListResponse(connected=True, items=[]))

    response = await client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    orders = response.json()["orders"]
    assert orders == {
        "today": 18,
        "confirmed_today": 12,
        "pending_today": 6,
        "revenue_today": "62400000.00",
        "currency": "VND",
        "pending_count": 7,
        "expiring_holds_30m": 3,
    }


# ---------------------------------------------------------------------------
# attention_orders -- classification, ranking, ≤5
# ---------------------------------------------------------------------------


def test_attention_classifies_expiring_hold_as_highest_priority(monkeypatch):
    now = datetime.now(UTC)
    row = _order_row(booking_status="RESERVED", earliest_expires_at=(now + timedelta(minutes=4)).isoformat())
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([row], 1))

    items = overview_module._fetch_attention_orders()

    assert items[0].issue == "expiring_hold"
    assert items[0].severity == "err"
    assert "phút" in items[0].issue_label


def test_attention_classifies_paid_not_confirmed(monkeypatch):
    row = _order_row(needs_attention=True)
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([row], 1))

    items = overview_module._fetch_attention_orders()

    assert items[0].issue == "paid_not_confirmed"
    assert items[0].severity == "warn"


def test_attention_classifies_awaiting_long_only_past_the_2h_threshold(monkeypatch):
    now = datetime.now(UTC)
    fresh = _order_row(payment_id="p-fresh", booking_status="PENDING", created_at=(now - timedelta(minutes=30)).isoformat())
    stale = _order_row(payment_id="p-stale", booking_status="PENDING", created_at=(now - timedelta(hours=3)).isoformat())
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([fresh, stale], 2))

    items = overview_module._fetch_attention_orders()

    assert len(items) == 1
    assert items[0].payment_id == "p-stale"
    assert items[0].issue == "awaiting_long"


def test_attention_classifies_payment_failed_as_lowest_priority(monkeypatch):
    row = _order_row(payment_status="FAILED")
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([row], 1))

    items = overview_module._fetch_attention_orders()

    assert items[0].issue == "payment_failed"
    assert items[0].severity == "mute"


def test_attention_sorted_expiring_before_paid_before_awaiting_before_failed(monkeypatch):
    now = datetime.now(UTC)
    rows = [
        _order_row(payment_id="p-failed", payment_status="FAILED"),
        _order_row(payment_id="p-expiring", booking_status="RESERVED", earliest_expires_at=(now + timedelta(minutes=5)).isoformat()),
        _order_row(payment_id="p-awaiting", booking_status="PENDING", created_at=(now - timedelta(hours=3)).isoformat()),
        _order_row(payment_id="p-paid", needs_attention=True),
    ]
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: (rows, len(rows)))

    items = overview_module._fetch_attention_orders()

    assert [item.payment_id for item in items] == ["p-expiring", "p-paid", "p-awaiting", "p-failed"]


def test_attention_orders_capped_at_5(monkeypatch):
    rows = [_order_row(payment_id=f"p{i}", needs_attention=True) for i in range(8)]
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: (rows, len(rows)))

    items = overview_module._fetch_attention_orders()

    assert len(items) == 5


def test_attention_ignores_orders_with_no_real_issue(monkeypatch):
    row = _order_row(booking_status="CONFIRMED", payment_status="PAID")
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([row], 1))

    assert overview_module._fetch_attention_orders() == []


def test_classify_attention_does_not_flag_an_already_expired_hold_h2():
    """H2 code-review finding: a RESERVED hold whose `earliest_expires_at`
    is already in the past (nothing auto-releases it) must not be
    mislabeled "expiring soon" and permanently occupy rank-0."""
    now = datetime.now(UTC)
    row = _order_row(booking_status="RESERVED", earliest_expires_at=(now - timedelta(minutes=5)).isoformat())

    assert overview_module._classify_attention(row, now=now) is None


def test_attention_expiring_hold_requires_positive_minutes_left(monkeypatch):
    now = datetime.now(UTC)
    expired = _order_row(payment_id="p-expired", booking_status="RESERVED", earliest_expires_at=(now - timedelta(minutes=5)).isoformat())
    paid = _order_row(payment_id="p-paid", needs_attention=True)
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([expired, paid], 2))

    items = overview_module._fetch_attention_orders()

    assert [item.payment_id for item in items] == ["p-paid"]


def test_attention_within_bucket_ties_break_by_longest_waiting_first_m1(monkeypatch):
    """M1 code-review finding: two orders with the same issue rank used to
    fall back to `fetch_orders`' own `created_at DESC` ordering (newest
    first, the order rows arrive in). The secondary sort key must put the
    longest-waiting order (oldest `created_at`) first within a bucket
    instead -- rows are deliberately passed newest-first here, matching
    `fetch_orders`' real ordering, so a passing test can't be an accident
    of input order."""
    now = datetime.now(UTC)
    newer = _order_row(payment_id="p-newer", needs_attention=True, created_at=(now - timedelta(hours=1)).isoformat())
    older = _order_row(payment_id="p-older", needs_attention=True, created_at=(now - timedelta(hours=5)).isoformat())
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: ([newer, older], 2))

    items = overview_module._fetch_attention_orders()

    assert [item.payment_id for item in items] == ["p-older", "p-newer"]


# ---------------------------------------------------------------------------
# embedding block -- sums across tables, missing_label generation
# ---------------------------------------------------------------------------


def test_embedding_block_sums_across_all_three_tables(monkeypatch):
    summary = embedding_module.EmbeddingSummaryResponse(
        tables=[
            embedding_module.EmbeddingTableSummary(table="hotels", label="Khách sạn", total=64, embedded=64, missing=0),
            embedding_module.EmbeddingTableSummary(table="rooms", label="Phòng", total=1246, embedded=1184, missing=62),
            embedding_module.EmbeddingTableSummary(table="attractions", label="Địa điểm", total=312, embedded=312, missing=0),
        ],
        total_missing=62,
    )
    monkeypatch.setattr(embedding_module, "get_embedding_summary", lambda: summary)

    result = overview_module._fetch_embedding_block()

    assert result.embedded == 64 + 1184 + 312
    assert result.total == 64 + 1246 + 312
    assert result.missing == 62
    assert result.missing_label == "62 phòng chưa có embedding"


def test_embedding_missing_label_empty_when_nothing_missing():
    tables = [embedding_module.EmbeddingTableSummary(table="hotels", label="Khách sạn", total=10, embedded=10, missing=0)]
    assert overview_module._missing_label(tables) == ""


def test_embedding_missing_label_joins_multiple_gaps():
    tables = [
        embedding_module.EmbeddingTableSummary(table="hotels", label="Khách sạn", total=64, embedded=61, missing=3),
        embedding_module.EmbeddingTableSummary(table="rooms", label="Phòng", total=1246, embedded=1184, missing=62),
    ]
    label = overview_module._missing_label(tables)
    assert "3 khách sạn" in label
    assert "62 phòng" in label
    assert "chưa có embedding" in label


# ---------------------------------------------------------------------------
# pipeline block -- extracts the has_params (embedding) item specifically
# ---------------------------------------------------------------------------


def test_pipeline_block_extracts_the_embedding_items_last_run(monkeypatch):
    items = [
        pipelines_module.PipelineItem(dag_id="tour_pipeline", label="Tour", description="d", is_paused=False, has_params=False, last_run=None),
        pipelines_module.PipelineItem(
            dag_id="embed_supabase_tables_pipeline",
            label="Embedding",
            description="d",
            is_paused=False,
            has_params=True,
            last_run=pipelines_module.PipelineLastRun(
                run_id="manual__x", state="success", start_date="2026-08-24T06:00:00Z", end_date="2026-08-24T06:04:12Z", duration_seconds=252
            ),
        ),
    ]
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: pipelines_module.PipelinesListResponse(connected=True, items=items))

    result = overview_module._fetch_pipeline_block()

    assert result.connected is True
    assert result.state == "success"
    assert result.run_id == "manual__x"
    assert result.duration_seconds == 252


def test_pipeline_block_connected_true_with_no_last_run_when_never_triggered(monkeypatch):
    items = [
        pipelines_module.PipelineItem(dag_id="embed_supabase_tables_pipeline", label="Embedding", description="d", is_paused=True, has_params=True, last_run=None)
    ]
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: pipelines_module.PipelinesListResponse(connected=True, items=items))

    result = overview_module._fetch_pipeline_block()

    assert result.connected is True
    assert result.state is None
    # dag_id is carried (never rendered) so the "Chạy pipeline" button can
    # trigger it without the frontend hardcoding the id itself.
    assert result.dag_id == "embed_supabase_tables_pipeline"


# ---------------------------------------------------------------------------
# expiring_holds -- must ask for holds not yet expired (H1)
# ---------------------------------------------------------------------------


def test_expiring_holds_requests_only_holds_not_yet_expired_h1(monkeypatch):
    """H1 code-review finding: without a lower bound on `expires_at`,
    ascending order surfaces the *most already-expired* holds instead of
    the soonest-to-expire ones this card exists to warn about. Asserts the
    actual wiring: `_fetch_expiring_holds` must pass a live `expires_after`
    cutoff through to `fetch_unpaid_bookings` rather than relying on
    `fetch_unpaid_bookings`'s own PostgREST filtering (mocked away here) to
    do the exclusion."""
    captured: dict[str, object] = {}

    def fake_fetch_unpaid_bookings(**kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr(orders_module, "fetch_unpaid_bookings", fake_fetch_unpaid_bookings)

    before = datetime.now(UTC)
    overview_module._fetch_expiring_holds()
    after = datetime.now(UTC)

    expires_after = captured.get("expires_after")
    assert isinstance(expires_after, datetime)
    assert before <= expires_after <= after
