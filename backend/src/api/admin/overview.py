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

import concurrent.futures
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.api.admin import embedding as embedding_module
from src.api.admin import orders as orders_module
from src.api.admin import pipelines as pipelines_module
from src.services.vnpay_service import VN_TZ

logger = logging.getLogger(__name__)

overview_router = APIRouter(prefix="/overview", tags=["admin-overview"])

# Same window used by orders.py's own stats -- "sắp hết hạn" / "chờ lâu" must
# agree with the numbers those tiles already show.
_EXPIRING_SOON_MINUTES = orders_module._EXPIRING_SOON_MINUTES
_PENDING_OVER_HOURS = orders_module._PENDING_OVER_HOURS
# Bounded candidate pool for "Đơn cần xử lý ngay" -- classified and ranked in
# Python from here, not a new query per issue type. Recent orders only: an
# order that's been sitting for weeks isn't "cần xử lý ngay" so much as
# abandoned, and D1 is where an admin goes looking for that.
_ATTENTION_LOOKBACK_DAYS = 3
_ATTENTION_CANDIDATE_LIMIT = 100


class OverviewOrders(BaseModel):
    today: int
    confirmed_today: int
    pending_today: int
    revenue_today: str
    currency: str
    pending_count: int
    expiring_holds_30m: int


class OverviewAttentionOrder(BaseModel):
    payment_id: str
    order_code: str
    guest_name: str | None = None
    guest_email: str | None = None
    amount: str
    issue: Literal["expiring_hold", "paid_not_confirmed", "awaiting_long", "payment_failed"]
    issue_label: str
    severity: Literal["err", "warn", "mute"]


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
    attention_orders: list[OverviewAttentionOrder] = Field(default_factory=list)
    expiring_holds: list[OverviewExpiringHold] = Field(default_factory=list)
    embedding: OverviewEmbedding | None = None
    pipeline: OverviewPipeline | None = None


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
        revenue_today=stats.revenue_today,
        currency=stats.currency,
        pending_count=stats.pending_count,
        expiring_holds_30m=stats.expiring_holds_30m,
    )


AttentionIssue = Literal["expiring_hold", "paid_not_confirmed", "awaiting_long", "payment_failed"]
AttentionSeverity = Literal["err", "warn", "mute"]


# (issue, issue_label, severity, rank) -- rank is the plan's explicit order:
# sắp hết hạn trước, rồi đã trả tiền chưa xác nhận, rồi chờ lâu nhất.
# payment_failed has no stated rank in the plan -- placed last (lowest
# urgency: nothing time-sensitive is happening, the guest already knows).
def _classify_attention(row: dict[str, Any], *, now: datetime) -> tuple[AttentionIssue, str, AttentionSeverity, int] | None:
    booking_status = row.get("booking_status")
    earliest_expires_at = row.get("earliest_expires_at")
    if booking_status == "RESERVED" and earliest_expires_at:
        expires = datetime.fromisoformat(str(earliest_expires_at).replace("Z", "+00:00"))
        minutes_left = (expires - now).total_seconds() / 60
        # Lower bound (H2 code-review finding): without `0 <`, a hold that
        # expired hours ago and was never released still matches here,
        # rounds to "Hết hạn giữ sau 0 phút", and permanently occupies
        # rank-0 -- shadowing genuine paid_not_confirmed issues below it.
        # An already-expired hold isn't "expiring soon", it's stale.
        if 0 < minutes_left <= _EXPIRING_SOON_MINUTES:
            minutes_label = max(0, round(minutes_left))
            return ("expiring_hold", f"Hết hạn giữ sau {minutes_label} phút", "err", 0)
    if row.get("needs_attention"):
        return ("paid_not_confirmed", "Trả tiền, chưa xác nhận", "warn", 1)
    if booking_status == "PENDING":
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        hours_waiting = (now - created).total_seconds() / 3600
        if hours_waiting >= _PENDING_OVER_HOURS:
            return ("awaiting_long", f"Chờ xác nhận {round(hours_waiting)} giờ", "warn", 2)
    if row.get("payment_status") == "FAILED":
        return ("payment_failed", "Thanh toán thất bại", "mute", 3)
    return None


def _fetch_attention_orders() -> list[OverviewAttentionOrder]:
    try:
        now = datetime.now(UTC)
        # `from_` is orders.py's own server-side date filter (M6 code-review
        # finding) -- the prior lexicographic string comparison on
        # `created_at` happened to sort correctly only because ISO 8601
        # timestamps do, and did an unbounded fetch-then-filter that wasted
        # the rows PostgREST already excluded via `.gte()`.
        since_date = (datetime.now(VN_TZ) - timedelta(days=_ATTENTION_LOOKBACK_DAYS)).date()
        rows, _total = orders_module.fetch_orders(
            start=0,
            end=_ATTENTION_CANDIDATE_LIMIT - 1,
            with_count=False,
            booking_status=None,
            payment_status=None,
            from_=since_date,
            to_=None,
            hotel_id=None,
            q=None,
            needs_attention=None,
        )
        classified: list[tuple[tuple[AttentionIssue, str, AttentionSeverity, int], dict[str, Any]]] = []
        for row in rows:
            result = _classify_attention(row, now=now)
            if result is not None:
                classified.append((result, row))
        # Secondary key (M1 code-review finding): within the same issue
        # rank, ties used to fall back to `fetch_orders`' own
        # `created_at DESC` ordering (newest-first) -- the opposite of
        # "chờ lâu nhất" (longest-waiting first). Ascending `created_at`
        # as the tiebreak makes the oldest, most-neglected order in each
        # bucket surface first.
        classified.sort(key=lambda pair: (pair[0][3], str(pair[1].get("created_at", ""))))
        top = classified[:5]
        return [
            OverviewAttentionOrder(
                payment_id=row["payment_id"],
                order_code=orders_module.short_code("DH", row["payment_id"]),
                guest_name=row.get("guest_name"),
                guest_email=row.get("guest_email"),
                amount=orders_module.money_str(row["amount"]),
                issue=issue,
                issue_label=issue_label,
                severity=severity,
            )
            for (issue, issue_label, severity, _rank), row in top
        ]
    except Exception:
        logger.exception("Overview: attention_orders block failed")
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
    """The 5 blocks are independent reads against different backends
    (Supabase twice over, Supabase again, Supabase again, Airflow via
    Phase 14's own 10s cache) -- run sequentially they summed to ~3s in
    testing against real data, blowing this phase's own "dưới 2 giây"
    criterion. Fetched in parallel here (same `ThreadPoolExecutor` pattern
    as Phase 14's `_fetch_pipelines_list`) since none of them depend on
    another's result, bringing real-data latency to roughly the slowest
    single block instead of their sum."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        orders_future = pool.submit(_fetch_orders_block)
        attention_future = pool.submit(_fetch_attention_orders)
        holds_future = pool.submit(_fetch_expiring_holds)
        embedding_future = pool.submit(_fetch_embedding_block)
        pipeline_future = pool.submit(_fetch_pipeline_block)

        return OverviewResponse(
            date=datetime.now(VN_TZ).date().isoformat(),
            orders=orders_future.result(),
            attention_orders=attention_future.result(),
            expiring_holds=holds_future.result(),
            embedding=embedding_future.result(),
            pipeline=pipeline_future.result(),
        )
