"""Tests for admin Overview (A3) -- src/api/admin/overview.py
(phase-17-overview-kpi.md). Mocked at the `orders`/`embedding`/`pipelines`
module-function boundary (same idiom as test_admin_pipelines.py mocking
`airflow_client`) -- this module makes zero Supabase/Airflow calls of its
own, so there is nothing lower-level to fake here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

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
        cancelled_today=1,
        revenue_today="62400000.00",
        currency="VND",
        avg_order_value="3466667.00",
        pending_count=7,
        pending_over_2h=2,
        expiring_holds_30m=3,
    )
    return base.model_copy(update=overrides)


def _money_summary(**overrides):
    base = orders_module.MoneySummary(
        currency="VND",
        collected_today="62400000.00",
        outstanding="8100000.00",
        revenue_trend=[orders_module.RevenueTrendPoint(date=f"2026-08-2{i}", revenue="1000000.00") for i in range(1, 8)],
        revenue_by_hotel=[orders_module.RevenueSlicePoint(label="Mường Thanh Luxury", revenue="24000000.00")],
        revenue_by_destination=[orders_module.RevenueSlicePoint(label="Nha Trang", revenue="24000000.00")],
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


def test_pending_orders_returns_empty_list_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "fetch_orders", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_pending_orders() == []


def test_expiring_holds_returns_empty_list_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "fetch_unpaid_bookings", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_expiring_holds() == []


def test_embedding_block_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(embedding_module, "get_embedding_summary", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_embedding_block() is None


def test_money_block_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(orders_module, "get_money_summary", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert overview_module._fetch_money_block() is None


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
    monkeypatch.setattr(orders_module, "get_money_summary", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    response = await client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["orders"] is None
    assert body["pending_orders"] == []
    assert body["expiring_holds"] == []
    assert body["embedding"] is None
    assert body["money"] is None
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
    monkeypatch.setattr(orders_module, "get_money_summary", _money_summary)
    monkeypatch.setattr(pipelines_module, "list_pipelines", lambda: pipelines_module.PipelinesListResponse(connected=True, items=[]))

    response = await client.get("/api/v1/admin/overview")

    assert response.status_code == 200
    orders = response.json()["orders"]
    assert orders == {
        "today": 18,
        "confirmed_today": 12,
        "pending_today": 6,
        "cancelled_today": 1,
        "revenue_today": "62400000.00",
        "currency": "VND",
        "pending_count": 7,
        "pending_over_2h": 2,
        "expiring_holds_30m": 3,
    }


# ---------------------------------------------------------------------------
# pending_orders -- "Chờ thanh toán": unpaid orders, longest-waiting first
# ---------------------------------------------------------------------------


def _capture_fetch_orders_kwargs(monkeypatch, rows=()):
    """Ordering and filtering both live in the query now, so the contract
    worth asserting is the arguments -- a fake that sorts its own rows would
    pass even if the real query came back newest-first."""
    captured: dict[str, Any] = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return list(rows), len(rows)

    monkeypatch.setattr(orders_module, "fetch_orders", fake)
    return captured


def test_pending_orders_asks_the_query_for_unpaid_rows_oldest_first(monkeypatch):
    captured = _capture_fetch_orders_kwargs(monkeypatch)

    overview_module._fetch_pending_orders()

    assert captured["payment_status"] == "PENDING"
    assert captured["oldest_first"] is True


def test_pending_orders_are_not_scoped_to_a_date_window(monkeypatch):
    """The tile above this card counts every PENDING payment ever. A card
    scoped to recent orders would show "13" next to a list explaining three
    of them, so the list must span the same all-time population."""
    captured = _capture_fetch_orders_kwargs(monkeypatch)

    overview_module._fetch_pending_orders()

    assert captured["from_"] is None
    assert captured["to_"] is None


def test_pending_orders_caps_the_page_at_5_rows(monkeypatch):
    captured = _capture_fetch_orders_kwargs(monkeypatch)

    overview_module._fetch_pending_orders()

    assert captured["start"] == 0
    assert captured["end"] == 4


def test_pending_orders_maps_row_fields_onto_the_card_shape(monkeypatch):
    row = _order_row(payment_id="11111111-1111-1111-1111-111111111111", amount="1850000.00")
    _capture_fetch_orders_kwargs(monkeypatch, [row])

    items = overview_module._fetch_pending_orders()

    assert len(items) == 1
    assert items[0].payment_id == "11111111-1111-1111-1111-111111111111"
    assert items[0].order_code == orders_module.short_code("DH", row["payment_id"])
    assert items[0].guest_name == "Trần Quốc Bảo"
    assert items[0].amount == "1850000.00"


def test_pending_orders_preserves_the_order_the_query_returned(monkeypatch):
    """No Python re-sort: rows arrive already ordered by `created_at ASC`,
    and re-sorting a 5-row page could only ever reorder within it."""
    now = datetime.now(UTC)
    rows = [
        _order_row(payment_id="p-oldest", created_at=(now - timedelta(days=9)).isoformat()),
        _order_row(payment_id="p-middle", created_at=(now - timedelta(hours=6)).isoformat()),
        _order_row(payment_id="p-newest", created_at=(now - timedelta(minutes=20)).isoformat()),
    ]
    _capture_fetch_orders_kwargs(monkeypatch, rows)

    items = overview_module._fetch_pending_orders()

    assert [item.payment_id for item in items] == ["p-oldest", "p-middle", "p-newest"]


@pytest.mark.parametrize(
    ("waited", "expected"),
    [
        (timedelta(minutes=20), "20 phút"),
        (timedelta(hours=3), "3 giờ"),
        (timedelta(hours=47), "47 giờ"),
        (timedelta(days=9), "9 ngày"),
    ],
)
def test_waiting_label_rounds_to_the_coarsest_honest_unit(waited, expected):
    """This backlog has no sweeper, so waits run to months -- "2136 giờ" is
    noise where "89 ngày" is actionable."""
    now = datetime.now(UTC)
    assert overview_module._waiting_label((now - waited).isoformat(), now=now) == expected


def test_waiting_label_never_reports_zero_for_a_brand_new_order():
    """A just-created order is "1 phút", not "0 phút" -- a zero reads as a
    rendering bug, and the row is on screen precisely because it is waiting."""
    now = datetime.now(UTC)
    assert overview_module._waiting_label(now.isoformat(), now=now) == "1 phút"


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
