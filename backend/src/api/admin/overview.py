"""Admin Overview (A3, phase-17-overview-kpi.md) -- the `/admin` landing
page. Ghép lại số liệu đã có từ ba nhánh trước, không viết truy vấn mới
(phase's own rule, and its own success criterion: this module contains zero
SQL/PostgREST calls of its own). Every number here is either a direct call
into Phase 4's `orders.py` / Phase 12's `embedding.py` / Phase 14's
`pipelines.py`, or Python-side classification/labeling on top of what those
already return.

Each of the three source blocks is wrapped in its own `try/except` -- one
failing (Airflow down, a transient Supabase error) must not blank the other
two (L78 / risk table: "Một khối lỗi làm trắng cả trang").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.admin import embedding as embedding_module
from src.api.admin import orders as orders_module
from src.api.admin import pipelines as pipelines_module
from src.services.vnpay_service import VN_TZ

logger = logging.getLogger(__name__)

overview_router = APIRouter(prefix="/overview", tags=["admin-overview"])

# Rows in the "Chờ thanh toán" card. Not a filter -- the tile above it still
# counts every PENDING payment; this only bounds what the card renders.
_PENDING_ORDERS_LIMIT = 5


class OverviewOrders(BaseModel):
    today: int
    confirmed_today: int
    pending_today: int
    # Orders opened today whose payment the guest cancelled at the VNPay
    # gateway (not the expiry sweep) -- a slice of `pending_today`, broken out
    # for the "Trạng thái đơn hôm nay" donut.
    cancelled_today: int
    revenue_today: str
    currency: str
    # `pending_count` counts payments still in PENDING -- checkout started,
    # VNPay never came back with PAID/FAILED/CANCELLED. That is a guest who
    # hasn't finished paying, not an order queued for an admin (the
    # admin-actionable state is `needs_attention`: PAID but booking not yet
    # CONFIRMED). `pending_over_2h` carries the same 2-hour cut D1's tile
    # already shows, so A3's subline can name the actionable subset instead
    # of mislabelling the whole all-time backlog.
    pending_count: int
    pending_over_2h: int
    expiring_holds_30m: int


class OverviewPendingOrder(BaseModel):
    payment_id: str
    order_code: str
    guest_name: str | None = None
    guest_email: str | None = None
    amount: str
    # Backend-generated, same posture as `OverviewEmbedding.missing_label`:
    # the "9 giờ" / "3 ngày" rounding is a labelling rule, and the tile above
    # this card already gets its 2-hour cut from the backend too -- splitting
    # it so the frontend re-derives the unit would let the two drift.
    waiting_label: str


class OverviewExpiringHold(BaseModel):
    booking_id: str
    hold_code: str
    guest_label: str | None = None
    hotel_name: str | None = None
    room_name: str | None = None
    expires_at: str | None = None


class OverviewEmbedding(BaseModel):
    embedded: int
    total: int
    missing: int
    missing_label: str


class OverviewPipeline(BaseModel):
    connected: bool
    state: str | None = None
    last_run_at: str | None = None
    duration_seconds: int | None = None
    run_id: str | None = None
    # Never rendered (plan's "không hiện dag_id trên UI" is a display rule,
    # not a "never send it" one) -- carried so the header's "Chạy pipeline"
    # button can call `POST /pipelines/{dag_id}/runs` for the embedding DAG
    # specifically without the frontend hardcoding that id itself.
    dag_id: str | None = None


class OverviewResponse(BaseModel):
    date: str
    orders: OverviewOrders | None = None
    pending_orders: list[OverviewPendingOrder] = Field(default_factory=list)
    expiring_holds: list[OverviewExpiringHold] = Field(default_factory=list)
    embedding: OverviewEmbedding | None = None
    pipeline: OverviewPipeline | None = None
    # Revenue charts. `None` (block raised) blanks only its own cards, same
    # posture as every other block here.
    money: orders_module.MoneySummary | None = None


def _fetch_orders_block() -> OverviewOrders | None:
    try:
        stats = orders_module.get_order_stats()
    except Exception:
        logger.exception("Overview: orders stats block failed")
        return None
    return OverviewOrders(
        today=stats.orders_today,
        confirmed_today=stats.confirmed_today,
        pending_today=stats.pending_today,
        cancelled_today=stats.cancelled_today,
        revenue_today=stats.revenue_today,
        currency=stats.currency,
        pending_count=stats.pending_count,
        pending_over_2h=stats.pending_over_2h,
        expiring_holds_30m=stats.expiring_holds_30m,
    )


def _waiting_label(created_at: str, *, now: datetime) -> str:
    """Rounds to the coarsest unit that still reads honestly. This list is
    an all-time backlog -- `payments` has no sweeper, so a guest who
    abandoned checkout in May is still PENDING today -- and "2136 giờ" is
    noise where "89 ngày" is a fact an admin can act on."""
    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    hours = (now - created).total_seconds() / 3600
    if hours < 1:
        return f"{max(1, round(hours * 60))} phút"
    if hours < 48:
        return f"{round(hours)} giờ"
    return f"{round(hours / 24)} ngày"


def _fetch_pending_orders() -> list[OverviewPendingOrder]:
    """"Chờ thanh toán" -- orders whose payment never came back from VNPay,
    longest-waiting first.

    Deliberately unfiltered by date and by booking status, so this card and
    the `pending_count` tile above it describe the same population: the tile
    counts every PENDING payment ever, and an admin who reads "13" then sees
    a list scoped to the last 3 days has been shown two different things
    under one heading. Ordering is pushed into `fetch_orders` (`oldest_first`)
    rather than done here -- with only 5 rows displayed, sorting a
    newest-first page in Python would surface the newest orders' oldest
    members, not the genuinely longest-waiting ones.
    """
    try:
        now = datetime.now(UTC)
        rows, _total = orders_module.fetch_orders(
            start=0,
            end=_PENDING_ORDERS_LIMIT - 1,
            with_count=False,
            oldest_first=True,
            booking_status=None,
            payment_status="PENDING",
            from_=None,
            to_=None,
            hotel_id=None,
            q=None,
            needs_attention=None,
        )
        return [
            OverviewPendingOrder(
                payment_id=row["payment_id"],
                order_code=orders_module.short_code("DH", row["payment_id"]),
                guest_name=row.get("guest_name"),
                guest_email=row.get("guest_email"),
                amount=orders_module.money_str(row["amount"]),
                waiting_label=_waiting_label(row["created_at"], now=now),
            )
            for row in rows
        ]
    except Exception:
        logger.exception("Overview: pending_orders block failed")
        return []


def _fetch_expiring_holds() -> list[OverviewExpiringHold]:
    try:
        # `expires_after=now` (H1 code-review finding): without a lower
        # bound, ascending `expires_at` surfaces the *most already-expired*
        # holds (nothing auto-releases them), not the soonest-to-expire
        # ones this card is meant to warn about. This makes the list a
        # strict subset of the `expiring_holds_30m` stat tile above it
        # (that tile also has no upper bound on the window and no cap of
        # 5) -- the two are related but not identical counts by design.
        rows, _total = orders_module.fetch_unpaid_bookings(
            start=0,
            end=4,
            with_count=False,
            booking_status="RESERVED",
            from_=None,
            to_=None,
            hotel_id=None,
            expires_after=datetime.now(UTC),
        )
        holds: list[OverviewExpiringHold] = []
        for row in rows:
            ref = row.get("temporary_user_ref")
            holds.append(
                OverviewExpiringHold(
                    booking_id=row["booking_id"],
                    hold_code=orders_module.short_code("GC", row["booking_id"]),
                    guest_label=f"Khách ẩn danh · {ref[:8]}" if ref else None,
                    hotel_name=row.get("hotel_name"),
                    room_name=row.get("room_name"),
                    expires_at=row.get("expires_at"),
                )
            )
        return holds
    except Exception:
        logger.exception("Overview: expiring_holds block failed")
        return []


def _missing_label(tables: list[Any]) -> str:
    """Mirrors embedding-coverage-page.tsx's `missingBannerText` (Phase 12
    frontend) in Python, since this label is backend-generated here (spec's
    own "missing_label do backend sinh") -- same single-table-rooms special
    case, same joined-list fallback for multiple gaps."""
    gaps = [t for t in tables if t.missing > 0]
    if not gaps:
        return ""
    if len(gaps) == 1 and gaps[0].table == "rooms":
        return f"{gaps[0].missing} phòng chưa có embedding"
    parts = [f"{t.missing} {t.label.lower()}" for t in gaps]
    return f"{', '.join(parts)} chưa có embedding"


def _fetch_embedding_block() -> OverviewEmbedding | None:
    try:
        summary = embedding_module.get_embedding_summary()
    except Exception:
        logger.exception("Overview: embedding block failed")
        return None
    embedded = sum(t.embedded for t in summary.tables)
    total = sum(t.total for t in summary.tables)
    return OverviewEmbedding(embedded=embedded, total=total, missing=summary.total_missing, missing_label=_missing_label(summary.tables))


def _fetch_money_block() -> orders_module.MoneySummary | None:
    try:
        return orders_module.get_money_summary()
    except Exception:
        logger.exception("Overview: money block failed")
        return None


def _fetch_pipeline_block() -> OverviewPipeline | None:
    """`list_pipelines()` never raises (Phase 14's own contract) and is
    already 10s-cached, so this reuses it as-is rather than calling
    Airflow again -- same reasoning as the risk table's poll-frequency
    mitigation."""
    try:
        pipelines = pipelines_module.list_pipelines()
    except Exception:
        logger.exception("Overview: pipeline block failed unexpectedly")
        return None
    if not pipelines.connected:
        return OverviewPipeline(connected=False)
    embedding_item = next((item for item in pipelines.items if item.has_params), None)
    if embedding_item is None:
        return OverviewPipeline(connected=True)
    if embedding_item.last_run is None:
        return OverviewPipeline(connected=True, dag_id=embedding_item.dag_id)
    return OverviewPipeline(
        connected=True,
        state=embedding_item.last_run.state,
        last_run_at=embedding_item.last_run.start_date,
        duration_seconds=embedding_item.last_run.duration_seconds,
        run_id=embedding_item.last_run.run_id,
        dag_id=embedding_item.dag_id,
    )


@overview_router.get("", response_model=OverviewResponse)
def get_overview() -> OverviewResponse:
    """The blocks are independent reads (Supabase several times over, Airflow
    via Phase 14's own 10s cache) with no data dependency between them, so
    they *could* run in parallel -- and originally did, via a
    `ThreadPoolExecutor`, to keep the page under this phase's "dưới 2 giây"
    target (~3s sequential against real data).

    That fan-out is gone: `get_supabase_client()` is one `@lru_cache`d
    `httpx.Client` with HTTP/2, shared process-wide, and a sync httpx client
    is **not safe for concurrent use across threads** -- interleaved writes
    from the worker threads corrupt the single HPACK encoder on the h2
    connection, the server sends GOAWAY(COMPRESSION_ERROR), and *every*
    in-flight block fails at once. Under load that was ~100% reproducible
    (the whole landing page rendered skeletons). Run sequentially on the one
    request thread it is correct and ~2-3s; the durable fix for the speed is
    a per-thread client or HTTP/1.1 on the shared one, tracked separately."""
    return OverviewResponse(
        date=datetime.now(VN_TZ).date().isoformat(),
        orders=_fetch_orders_block(),
        pending_orders=_fetch_pending_orders(),
        expiring_holds=_fetch_expiring_holds(),
        embedding=_fetch_embedding_block(),
        money=_fetch_money_block(),
        pipeline=_fetch_pipeline_block(),
    )
