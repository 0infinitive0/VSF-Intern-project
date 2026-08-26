import { useEffect, useState } from 'react'
import { listHotels } from '../../api/hotels-client'
import {
  exportOrdersCsv,
  getOrderStats,
  listOrders,
  listUnpaidBookings,
  releaseExpiredHolds,
  type OrderRow,
  type OrderStatsResponse,
  type OrdersTab,
  type UnpaidBookingRow,
} from '../../api/orders-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { EmptyState } from '../../ui/empty-state'
import { ErrorState } from '../../ui/error-state'
import { Pagination } from '../../ui/pagination'
import { SkeletonTable } from '../../ui/skeleton-table'
import { Tabs, type TabItem } from '../../ui/tabs'
import type { BookingStatusKey, PaymentStatusKey } from './order-status-chip'
import { OrderStatCards } from './order-stat-cards'
import { OrdersEmpty, type ActiveOrderFilter } from './orders-empty'
import { OrdersTable } from './orders-table'
import { OrdersToolbar, type HotelOption } from './orders-toolbar'
import { UnpaidHoldsTable } from './unpaid-holds-table'

const PAGE_SIZE = 25
const STATS_POLL_MS = 60_000

const BOOKING_STATUS_LABELS: Record<BookingStatusKey, string> = {
  PENDING: 'Chờ xác nhận',
  RESERVED: 'Đang giữ chỗ',
  CONFIRMED: 'Đã xác nhận',
  MIXED: 'Một phần',
  CANCELLED: 'Đã huỷ',
  EXPIRED: 'Hết hạn giữ',
  UNKNOWN: 'Không rõ',
}

const PAYMENT_STATUS_LABELS: Record<PaymentStatusKey, string> = {
  PENDING: 'Chờ thanh toán',
  PAID: 'Đã thanh toán',
  FAILED: 'Thất bại',
  CANCELLED: 'Đã huỷ',
  NONE: 'Chưa có',
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function defaultDateRange(): { from: string; to: string } {
  const to = new Date()
  const from = new Date(to)
  from.setDate(from.getDate() - 6)
  return { from: isoDate(from), to: isoDate(to) }
}

type PaidListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: OrderRow[]; total: number }
  | { status: 'error'; detail: string }

type UnpaidListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: UnpaidBookingRow[]; total: number; expiringCount: number }
  | { status: 'error'; detail: string }

interface OrdersPageProps {
  navigate: (to: string) => void
}

/** orders-page.tsx — D1 orchestrator (phase-04-orders-list.md). Both tabs'
 * lists are fetched unconditionally (not just the active tab) so switching
 * tabs never shows a stale skeleton, and so the two tab badges ("Đơn hàng ·
 * 128") reflect the *other* tab's count even while it's off screen. The
 * paid-tab badge does still move with tab 1's own filters -- same count the
 * toolbar's "Hiển thị n / N" shows -- since tab 1 has no separate
 * "unfiltered total" to fall back to. Tab 2 has no toolbar in the design --
 * only tab 1's filters affect its own fetch. */
export function OrdersPage({ navigate }: OrdersPageProps) {
  const [tab, setTab] = useState<OrdersTab>('paid')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [bookingStatus, setBookingStatus] = useState<BookingStatusKey | undefined>(undefined)
  const [paymentStatus, setPaymentStatus] = useState<PaymentStatusKey | undefined>(undefined)
  const [hotelId, setHotelId] = useState<string | undefined>(undefined)
  const [{ from, to }, setDateRange] = useState(defaultDateRange)
  const [paidPage, setPaidPage] = useState(1)
  const [unpaidPage, setUnpaidPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)

  const [paidState, setPaidState] = useState<PaidListState>({ status: 'loading' })
  const [unpaidState, setUnpaidState] = useState<UnpaidListState>({ status: 'loading' })
  const [paidFetching, setPaidFetching] = useState(false)
  const [unpaidFetching, setUnpaidFetching] = useState(false)
  const [stats, setStats] = useState<OrderStatsResponse | null>(null)
  const [hotels, setHotels] = useState<HotelOption[]>([])

  const [releaseBusy, setReleaseBusy] = useState(false)
  const [releaseResult, setReleaseResult] = useState<{ released: number; skipped: number } | null>(null)
  const [releaseError, setReleaseError] = useState<string | null>(null)
  const [csvBusy, setCsvBusy] = useState(false)
  const [csvError, setCsvError] = useState<string | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(timer)
  }, [q])

  useEffect(() => {
    setPaidPage(1)
  }, [debouncedQ, bookingStatus, paymentStatus, hotelId, from, to])

  useEffect(() => {
    listHotels({ page: 1, pageSize: 100 }).then((result) => {
      if (result.ok) setHotels(result.data.items.map((h) => ({ id: h.id, name: h.name })))
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    setPaidFetching(true)
    setPaidState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listOrders({
      tab: 'paid',
      bookingStatus,
      paymentStatus,
      hotelId,
      q: debouncedQ || undefined,
      from,
      to,
      page: paidPage,
      pageSize: PAGE_SIZE,
    }).then((result) => {
      if (cancelled) return
      setPaidFetching(false)
      if (!result.ok) return setPaidState({ status: 'error', detail: result.detail })
      setPaidState({ status: 'loaded', items: result.data.items, total: result.data.total })
    })
    return () => {
      cancelled = true
    }
  }, [debouncedQ, bookingStatus, paymentStatus, hotelId, from, to, paidPage, refreshKey])

  useEffect(() => {
    let cancelled = false
    setUnpaidFetching(true)
    setUnpaidState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listUnpaidBookings({ tab: 'unpaid', page: unpaidPage, pageSize: PAGE_SIZE }).then((result) => {
      if (cancelled) return
      setUnpaidFetching(false)
      if (!result.ok) return setUnpaidState({ status: 'error', detail: result.detail })
      setUnpaidState({ status: 'loaded', items: result.data.items, total: result.data.total, expiringCount: result.data.expiring_count })
    })
    return () => {
      cancelled = true
    }
  }, [unpaidPage, refreshKey])

  useEffect(() => {
    let cancelled = false
    function poll() {
      getOrderStats().then((result) => {
        if (!cancelled && result.ok) setStats(result.data)
      })
    }
    poll()
    const timer = setInterval(poll, STATS_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [refreshKey])

  async function handleExportCsv() {
    setCsvBusy(true)
    setCsvError(null)
    // Tab 2 has no toolbar/filters (per the design) and its own list fetch
    // below never applies any -- the CSV export must match, or an admin
    // exporting tab 2 silently gets a file scoped to tab 1's date range
    // instead of the same unfiltered set the table on screen shows.
    const result = await exportOrdersCsv({
      tab,
      bookingStatus: tab === 'paid' ? bookingStatus : undefined,
      paymentStatus: tab === 'paid' ? paymentStatus : undefined,
      hotelId: tab === 'paid' ? hotelId : undefined,
      q: tab === 'paid' ? debouncedQ || undefined : undefined,
      from: tab === 'paid' ? from : undefined,
      to: tab === 'paid' ? to : undefined,
      page: 1,
      pageSize: PAGE_SIZE,
    })
    setCsvBusy(false)
    if (!result.ok) setCsvError(result.detail)
  }

  async function handleReleaseExpired() {
    setReleaseBusy(true)
    setReleaseError(null)
    setReleaseResult(null)
    const result = await releaseExpiredHolds()
    setReleaseBusy(false)
    if (!result.ok) {
      setReleaseError(result.detail)
      return
    }
    setReleaseResult({ released: result.data.released, skipped: result.data.skipped })
    // Releasing shrinks the unpaid list -- staying on e.g. page 3 could now
    // be past the end of the (smaller) result set.
    setUnpaidPage(1)
    setRefreshKey((k) => k + 1)
  }

  function clearAllFilters() {
    setQ('')
    setBookingStatus(undefined)
    setPaymentStatus(undefined)
    setHotelId(undefined)
  }

  const paidTotal = paidState.status === 'loaded' ? paidState.total : 0
  const unpaidTotal = unpaidState.status === 'loaded' ? unpaidState.total : 0

  const activeFilters: ActiveOrderFilter[] = []
  if (hotelId) {
    const hotelName = hotels.find((h) => h.id === hotelId)?.name ?? hotelId
    activeFilters.push({ key: 'hotel', label: `Khách sạn: ${hotelName}`, clause: `của ${hotelName}`, onRemove: () => setHotelId(undefined) })
  }
  if (paymentStatus) {
    const label = PAYMENT_STATUS_LABELS[paymentStatus]
    activeFilters.push({
      key: 'payment',
      label: `Thanh toán: ${label}`,
      clause: `với thanh toán ${label.toLowerCase()}`,
      onRemove: () => setPaymentStatus(undefined),
    })
  }
  if (bookingStatus) {
    const label = BOOKING_STATUS_LABELS[bookingStatus]
    activeFilters.push({
      key: 'booking',
      label: `Trạng thái đơn: ${label}`,
      clause: `với trạng thái ${label.toLowerCase()}`,
      onRemove: () => setBookingStatus(undefined),
    })
  }
  if (debouncedQ) {
    activeFilters.push({ key: 'q', label: `Tìm kiếm: "${debouncedQ}"`, clause: `khớp "${debouncedQ}"`, onRemove: () => setQ('') })
  }

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Đơn hàng"
        title="Danh sách đơn hàng"
        action={
          <Button variant="secondary" size="sm" disabled={csvBusy} onClick={handleExportCsv}>
            ↓ Xuất CSV
          </Button>
        }
      />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
        {csvError && <Banner tone="err">{csvError}</Banner>}
        {releaseError && <Banner tone="err">{releaseError}</Banner>}
        {releaseResult && (
          <Banner tone={releaseResult.skipped > 0 ? 'warn' : 'ok'}>
            Đã giải phóng {releaseResult.released} giữ chỗ hết hạn.
            {releaseResult.skipped > 0 && ` ${releaseResult.skipped} giữ chỗ không thể giải phóng.`}
          </Banner>
        )}

        <OrderStatCards stats={stats} />

        <Tabs
          items={[
            { key: 'paid', label: `Đơn hàng · ${paidTotal}` } satisfies TabItem,
            { key: 'unpaid', label: `Đặt phòng chưa thanh toán · ${unpaidTotal}` } satisfies TabItem,
          ]}
          activeKey={tab}
          onChange={(key) => setTab(key as OrdersTab)}
        />

        {tab === 'paid' && (
          <>
            <OrdersToolbar
              q={q}
              onQChange={setQ}
              bookingStatus={bookingStatus}
              onBookingStatusChange={setBookingStatus}
              paymentStatus={paymentStatus}
              onPaymentStatusChange={setPaymentStatus}
              hotelId={hotelId}
              onHotelIdChange={setHotelId}
              hotels={hotels}
              from={from}
              to={to}
              onFromChange={(value) => setDateRange((prev) => ({ ...prev, from: value }))}
              onToChange={(value) => setDateRange((prev) => ({ ...prev, to: value }))}
              shownCount={paidState.status === 'loaded' ? paidState.items.length : 0}
              totalCount={paidTotal}
            />

            {paidState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[70, 160, 140, 110, 50, 90, 90, 90, 90]} />}

            {paidState.status === 'error' && (
              <div className="card">
                <ErrorState description={paidState.detail} onRetry={() => setRefreshKey((k) => k + 1)} />
              </div>
            )}

            {paidState.status === 'loaded' && paidState.items.length === 0 && activeFilters.length > 0 && (
              <div className="card">
                <OrdersEmpty from={from} to={to} filters={activeFilters} onClearAll={clearAllFilters} />
              </div>
            )}

            {paidState.status === 'loaded' && paidState.items.length === 0 && activeFilters.length === 0 && (
              <div className="card">
                <EmptyState title="Chưa có đơn nào" description="Chưa có đơn hàng nào trong khoảng ngày đã chọn." />
              </div>
            )}

            {paidState.status === 'loaded' && paidState.items.length > 0 && (
              <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <div style={{ overflowX: 'auto' }}>
                  <OrdersTable rows={paidState.items} onOpenOrder={(id) => navigate(`/admin/orders/${id}`)} loading={paidFetching} />
                </div>
                <div style={{ fontSize: 11, color: 'var(--t4)', padding: '8px 14px', borderTop: '1px solid var(--line)' }}>
                  Dòng có dải màu bên trái: đã thanh toán, chưa xác nhận · sắp hết hạn giữ chỗ.
                </div>
                <Pagination page={paidPage} pageSize={PAGE_SIZE} total={paidTotal} onPageChange={setPaidPage} loading={paidFetching} />
              </div>
            )}
          </>
        )}

        {tab === 'unpaid' && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 13, color: 'var(--t3)' }}>
                {unpaidTotal} lượt giữ chỗ chưa gắn thanh toán
                {unpaidState.status === 'loaded' && ` · ${unpaidState.expiringCount} sắp hết hạn`}
              </span>
              <div style={{ flex: 1 }} />
              <Button variant="secondary" size="sm" disabled={releaseBusy} onClick={handleReleaseExpired}>
                Giải phóng phòng hết hạn
              </Button>
            </div>

            {unpaidState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[70, 140, 180, 90, 80]} />}

            {unpaidState.status === 'error' && (
              <div className="card">
                <ErrorState description={unpaidState.detail} onRetry={() => setRefreshKey((k) => k + 1)} />
              </div>
            )}

            {unpaidState.status === 'loaded' && unpaidState.items.length === 0 && (
              <div className="card">
                <EmptyState title="Không có giữ chỗ chưa thanh toán" description="Mọi đặt phòng hiện đều đã gắn với một giao dịch thanh toán." />
              </div>
            )}

            {unpaidState.status === 'loaded' && unpaidState.items.length > 0 && (
              <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <div style={{ overflowX: 'auto' }}>
                  <UnpaidHoldsTable rows={unpaidState.items} loading={unpaidFetching} />
                </div>
                <Pagination page={unpaidPage} pageSize={PAGE_SIZE} total={unpaidTotal} onPageChange={setUnpaidPage} loading={unpaidFetching} />
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}
