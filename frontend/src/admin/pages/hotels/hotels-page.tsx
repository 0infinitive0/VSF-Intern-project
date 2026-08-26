import { useEffect, useRef, useState } from 'react'
import {
  bulkSetHotelActive,
  exportHotelsCsv,
  listHotels,
  reembedHotels,
  setHotelActive,
  type EmbeddingFilter,
  type HotelBlockedBooking,
  type HotelRow,
  type SourceFilter,
} from '../../api/hotels-client'
import { listPipelines, type PipelineItem } from '../../api/pipelines-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { EmptyState } from '../../ui/empty-state'
import { ErrorState } from '../../ui/error-state'
import { Modal } from '../../ui/modal'
import { Pagination } from '../../ui/pagination'
import { SkeletonTable } from '../../ui/skeleton-table'
import { ReembedConfirmDialog } from '../embedding/reembed-confirm-dialog'
import { PipelineRunProgress } from '../pipelines/pipeline-run-progress'
import { HotelsBulkBar } from './hotels-bulk-bar'
import { HotelsTable } from './hotels-table'
import { HotelsToolbar } from './hotels-toolbar'

const PAGE_SIZE = 25

const EMBEDDING_POLL_MS = 1000
// ~2 minutes -- same cap as hotel-detail-page.tsx's single-hotel poll; if
// Airflow hasn't moved the run past queued/running by then, stop instead of
// polling forever (the Pipelines page still has the real live status).
const MAX_EMBEDDING_POLL_ATTEMPTS = 120

type ListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: HotelRow[]; total: number }
  | { status: 'empty' }
  | { status: 'error'; detail: string }

interface RowBlockedError {
  hotelName: string
  count: number
  bookings: HotelBlockedBooking[]
}

type SortState = { key: string; direction: 'asc' | 'desc' } | null

interface HotelsPageProps {
  navigate: (to: string) => void
}

/** hotels-page.tsx — B1 orchestrator (phase-07-hotels-list.md). Owns filter
 * state, the fetched page, selection, and the two write flows (per-row
 * optimistic switch, bulk deactivate with a confirmation step) -- the
 * sub-components (toolbar/table/bulk-bar) stay presentational. */
export function HotelsPage({ navigate }: HotelsPageProps) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [source, setSource] = useState<SourceFilter>('all')
  const [isActive, setIsActive] = useState<boolean | undefined>(undefined)
  const [embedding, setEmbedding] = useState<EmbeddingFilter>('all')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<SortState>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const [listState, setListState] = useState<ListState>({ status: 'loading' })
  const [isFetching, setIsFetching] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [rowError, setRowError] = useState<RowBlockedError | null>(null)
  const [bulkConfirmOpen, setBulkConfirmOpen] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkBlockedCount, setBulkBlockedCount] = useState<number | null>(null)
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [csvBusy, setCsvBusy] = useState(false)
  const [csvError, setCsvError] = useState<string | null>(null)
  const [reembedConfirmOpen, setReembedConfirmOpen] = useState(false)
  const [reembedIncludeRooms, setReembedIncludeRooms] = useState(false)
  // Mirrors hotel-detail-page.tsx's single-hotel reembed state machine so
  // the bulk action reports the pipeline's real completion instead of just
  // the trigger response ("loading" while the request is in flight,
  // "queued"+progress while the DAG run itself executes, then the real
  // success/failed outcome).
  const [reembedState, setReembedState] = useState<'idle' | 'loading' | 'queued' | 'unavailable' | 'stalled' | 'success' | 'failed'>('idle')
  const [reembedCount, setReembedCount] = useState(0)
  const [reembedErrorDetail, setReembedErrorDetail] = useState<string | null>(null)
  const [embeddingRun, setEmbeddingRun] = useState<PipelineItem | null>(null)
  const embeddingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const embeddingPollAttemptsRef = useRef(0)
  // Tracks THIS trigger's dag_run_id (not just the DAG's `last_run`) --
  // same reasoning as hotel-detail-page.tsx: the DAG's `max_active_runs=1`
  // can queue this run behind an unrelated one already in flight.
  const embeddingDagRunIdRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    }
  }, [])

  // Debounce the search box so every keystroke doesn't fire a request.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(timer)
  }, [q])

  // Any filter or sort change re-pages to 1 -- a stale page number past the
  // new filtered/ordered total would just render an empty page.
  useEffect(() => {
    setPage(1)
  }, [debouncedQ, source, isActive, embedding, sort])

  useEffect(() => {
    let cancelled = false
    setIsFetching(true)
    setListState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listHotels({
      q: debouncedQ || undefined,
      source,
      isActive,
      embedding,
      page,
      pageSize: PAGE_SIZE,
      sort: sort?.key,
      sortDir: sort?.direction,
    }).then((result) => {
      if (cancelled) return
      setIsFetching(false)
      if (!result.ok) return setListState({ status: 'error', detail: result.detail })
      if (result.data.items.length === 0) return setListState({ status: 'empty' })
      setListState({ status: 'loaded', items: result.data.items, total: result.data.total })
    })
    return () => {
      cancelled = true
    }
  }, [debouncedQ, source, isActive, embedding, page, sort, refreshKey])

  function handleSortChange(key: string) {
    setSort((prev) => (!prev || prev.key !== key ? { key, direction: 'asc' } : { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' }))
  }

  const items = listState.status === 'loaded' ? listState.items : []

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    setSelectedIds((prev) => {
      const allSelected = items.length > 0 && items.every((row) => prev.has(row.id))
      if (allSelected) return new Set()
      return new Set(items.map((row) => row.id))
    })
  }

  async function handleToggleActive(row: HotelRow, next: boolean) {
    if (listState.status !== 'loaded') return
    setRowError(null)
    const snapshot = listState
    setListState({ ...snapshot, items: snapshot.items.map((r) => (r.id === row.id ? { ...r, is_active: next } : r)) })

    const result = await setHotelActive(row.id, next)
    if (!result.ok) {
      setListState(snapshot)
      setRowError({ hotelName: row.name, count: result.count ?? 0, bookings: result.bookings ?? [] })
    }
  }

  async function handleBulkDeactivate() {
    setBulkBusy(true)
    setBulkBlockedCount(null)
    setBulkError(null)
    const result = await bulkSetHotelActive(Array.from(selectedIds), false)
    setBulkBusy(false)
    setBulkConfirmOpen(false)
    if (!result.ok) {
      setBulkError(result.detail)
      return
    }
    const blockedIds = new Set(result.data.blocked.map((b) => b.hotel_id))
    if (listState.status === 'loaded') {
      setListState({
        ...listState,
        items: listState.items.map((row) => (selectedIds.has(row.id) && !blockedIds.has(row.id) ? { ...row, is_active: false } : row)),
      })
    }
    setBulkBlockedCount(result.data.blocked.length)
    setSelectedIds(blockedIds.size > 0 ? blockedIds : new Set())
  }

  async function handleBulkReembed() {
    const hotelIds = Array.from(selectedIds)
    setReembedState('loading')
    setReembedCount(hotelIds.length)
    setReembedErrorDetail(null)
    const result = await reembedHotels(hotelIds, reembedIncludeRooms)
    setReembedConfirmOpen(false)
    setSelectedIds(new Set())
    // Cleared to NULL server-side regardless of outcome below -- refresh
    // now so the table's embedding dots already show "cần nhúng lại".
    setRefreshKey((k) => k + 1)

    if (!result.ok) {
      setReembedState('failed')
      setReembedErrorDetail(result.detail)
      return
    }
    if (!result.data.queued) {
      setReembedState('unavailable')
      return
    }
    setReembedState('queued')
    embeddingDagRunIdRef.current = result.data.dag_run_id ?? null
    if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    embeddingPollAttemptsRef.current = 0
    pollEmbeddingProgress()
  }

  // Polls the shared Pipelines list (same idiom as hotel-detail-page.tsx's
  // single-hotel reembed) so the bulk action reports real %-done and the
  // actual success/failed outcome instead of leaving a static "đã gửi yêu
  // cầu" banner up with no idea when the DAG run actually finishes.
  function pollEmbeddingProgress() {
    listPipelines().then((result) => {
      const embedding = result.ok ? (result.data.items.find((item: PipelineItem) => item.has_params) ?? null) : null
      const expectedRunId = embeddingDagRunIdRef.current
      if (expectedRunId && embedding?.last_run?.run_id !== expectedRunId) {
        setEmbeddingRun(null)
        embeddingPollAttemptsRef.current += 1
        if (embeddingPollAttemptsRef.current >= MAX_EMBEDDING_POLL_ATTEMPTS) {
          setReembedState('stalled')
          return
        }
        embeddingPollRef.current = setTimeout(pollEmbeddingProgress, EMBEDDING_POLL_MS)
        return
      }
      setEmbeddingRun(embedding)
      const state = embedding?.last_run?.state
      if (state === 'running' || state === 'queued') {
        embeddingPollAttemptsRef.current += 1
        if (embeddingPollAttemptsRef.current >= MAX_EMBEDDING_POLL_ATTEMPTS) {
          setReembedState('stalled')
          return
        }
        embeddingPollRef.current = setTimeout(pollEmbeddingProgress, EMBEDDING_POLL_MS)
        return
      }
      // Run finished -- stop, show the real outcome, and refresh the list so
      // every touched row's embedding dot picks up the result.
      setReembedState(state === 'success' ? 'success' : state === 'failed' ? 'failed' : 'idle')
      setEmbeddingRun(null)
      setRefreshKey((k) => k + 1)
    })
  }

  // Dismisses any reembed banner (queued/stalled/success/failed/unavailable).
  // Also stops an in-flight poll -- the pipeline itself keeps running on the
  // backend regardless, this only stops the UI from tracking it further.
  function handleDismissReembed() {
    if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    embeddingDagRunIdRef.current = null
    setReembedState('idle')
    setEmbeddingRun(null)
  }

  async function handleExportCsv() {
    setCsvBusy(true)
    setCsvError(null)
    const result = await exportHotelsCsv({
      q: debouncedQ || undefined,
      source,
      isActive,
      embedding,
      page,
      pageSize: PAGE_SIZE,
      sort: sort?.key,
      sortDir: sort?.direction,
    })
    setCsvBusy(false)
    if (!result.ok) setCsvError(result.detail)
  }

  const total = listState.status === 'loaded' ? listState.total : 0
  const shownCount = items.length

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Khách sạn"
        title="Danh sách khách sạn"
        action={
          <>
            <Button variant="secondary" size="sm" disabled={csvBusy} onClick={handleExportCsv}>
              ↓ Xuất CSV
            </Button>
            <Button variant="primary" size="sm" onClick={() => navigate('/admin/hotels/new')}>
              + Thêm khách sạn
            </Button>
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        {csvError && <Banner tone="err">{csvError}</Banner>}
        {bulkError && <Banner tone="err">{bulkError}</Banner>}

        {reembedState === 'unavailable' && (
          <Banner tone="warn">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1 }}>
                Đã đánh dấu {reembedCount} khách sạn cần nhúng lại. Pipeline sẽ tự nhặt ở lần chạy kế tiếp, hoặc chạy ngay ở trang Tổng quan.
              </span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}
        {reembedState === 'stalled' && (
          <Banner tone="warn">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1, minWidth: 200 }}>
                Pipeline embedding đang chờ lâu hơn bình thường (Airflow chưa bắt đầu chạy). Đã đánh dấu {reembedCount} khách sạn cần nhúng lại,
                bot sẽ học khi pipeline chạy.
              </span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}
        {reembedState === 'queued' && (
          <Banner tone="ok">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
                <span style={{ flex: 1 }}>Đã gửi yêu cầu chạy lại embedding cho {reembedCount} khách sạn.</span>
                <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                  ✕
                </Button>
              </div>
              {embeddingRun?.last_run?.state === 'running' ? (
                <PipelineRunProgress lastRun={embeddingRun.last_run} />
              ) : (
                <span style={{ fontSize: 11.5 }}>Đang chờ pipeline bắt đầu…</span>
              )}
            </div>
          </Banner>
        )}
        {reembedState === 'success' && (
          <Banner tone="ok">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1 }}>Đã embed thành công {reembedCount} khách sạn — chatbot đã học nội dung mới.</span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}
        {reembedState === 'failed' && (
          <Banner tone="err">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1, minWidth: 200 }}>
                {reembedErrorDetail ?? 'Chạy embedding thất bại. Thử chạy lại pipeline ở trang Tổng quan.'}
              </span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}

        {rowError && (
          <Banner tone="err">
            <div>
              {rowError.hotelName ? `Không thể ngừng bán "${rowError.hotelName}"` : 'Một số khách sạn không thể ngừng bán'} vì còn{' '}
              {rowError.count || rowError.bookings.length} đơn CONFIRMED chưa checkout:
              {rowError.bookings.length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                  {rowError.bookings.map((b) => (
                    <li key={b.booking_id}>
                      {b.room_name} — check-in {b.check_in_date}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Banner>
        )}

        {bulkBlockedCount !== null && bulkBlockedCount > 0 && (
          <Banner tone="warn">{bulkBlockedCount} khách sạn không thể ngừng bán vì còn đơn CONFIRMED chưa checkout.</Banner>
        )}

        <HotelsToolbar
          q={q}
          onQChange={setQ}
          source={source}
          onSourceChange={setSource}
          isActive={isActive}
          onIsActiveChange={setIsActive}
          embedding={embedding}
          onEmbeddingChange={setEmbedding}
          shownCount={shownCount}
          totalCount={total}
        />

        {listState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[16, 200, 90, 60, 90, 60, 100, 80]} />}

        {listState.status === 'error' && (
          <div className="card">
            <ErrorState description={listState.detail} onRetry={() => setRefreshKey((k) => k + 1)} />
          </div>
        )}

        {listState.status === 'empty' && (
          <div className="card">
            <EmptyState />
          </div>
        )}

        {listState.status === 'loaded' && (
          <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ overflowX: 'auto' }}>
              <HotelsTable
                rows={listState.items}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onToggleSelectAll={toggleSelectAll}
                onToggleActive={handleToggleActive}
                onOpenHotel={(id) => navigate(`/admin/hotels/${id}`)}
                loading={isFetching}
                sortState={sort}
                onSortChange={handleSortChange}
              />
            </div>
            <div style={{ fontSize: 11, color: 'var(--t4)', padding: '8px 14px', borderTop: '1px solid var(--line)' }}>
              Dòng kẻ sọc: dữ liệu lấy từ nguồn OTA — sẽ bị ghi đè khi chạy lại pipeline nhập liệu.
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} loading={isFetching} />
          </div>
        )}
      </div>

      <HotelsBulkBar
        selectedCount={selectedIds.size}
        busy={bulkBusy || reembedState === 'loading'}
        onDeactivate={() => setBulkConfirmOpen(true)}
        onReembed={() => setReembedConfirmOpen(true)}
        onClear={() => setSelectedIds(new Set())}
      />

      <Modal open={bulkConfirmOpen} onClose={() => setBulkConfirmOpen(false)}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Ngừng bán {selectedIds.size} khách sạn?</div>
        <div style={{ fontSize: 13, color: 'var(--t3)' }}>
          Khách sạn còn đơn CONFIRMED chưa checkout sẽ được bỏ qua và báo lại sau khi hoàn tất.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={() => setBulkConfirmOpen(false)} disabled={bulkBusy}>
            Huỷ
          </Button>
          <Button variant="danger" size="sm" onClick={handleBulkDeactivate} disabled={bulkBusy}>
            Ngừng bán
          </Button>
        </div>
      </Modal>

      <ReembedConfirmDialog
        open={reembedConfirmOpen}
        count={selectedIds.size}
        includeRooms={reembedIncludeRooms}
        busy={reembedState === 'loading'}
        onIncludeRoomsChange={setReembedIncludeRooms}
        onConfirm={handleBulkReembed}
        onClose={() => setReembedConfirmOpen(false)}
      />
    </>
  )
}
