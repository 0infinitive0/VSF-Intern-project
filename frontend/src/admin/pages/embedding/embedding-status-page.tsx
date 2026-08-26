import { useEffect, useRef, useState } from 'react'
import { getEmbeddingSummary, type EmbeddingSummaryResponse } from '../../api/embedding-client'
import { listHotels, reembedHotels, type HotelRow, type SourceFilter } from '../../api/hotels-client'
import { listPipelines, type PipelineItem } from '../../api/pipelines-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { EmptyState } from '../../ui/empty-state'
import { ErrorState } from '../../ui/error-state'
import { Pagination } from '../../ui/pagination'
import { Select } from '../../ui/select'
import { SkeletonTable } from '../../ui/skeleton-table'
import { PipelineRunProgress } from '../pipelines/pipeline-run-progress'
import { EmbeddingStatusTable } from './embedding-status-table'
import { EmbeddingTableCards } from './embedding-table-cards'
import { ReembedConfirmDialog } from './reembed-confirm-dialog'

const PAGE_SIZE = 25
const EMBEDDING_POLL_MS = 1000
// ~2 minutes -- if Airflow hasn't moved the run past `queued`/`running` by
// then, stop polling instead of leaving the banner looking permanently stuck
// (same idiom as hotel-detail-page.tsx's single-hotel reembed poll).
const MAX_EMBEDDING_POLL_ATTEMPTS = 120

type ReembedRunState = 'idle' | 'unavailable' | 'queued' | 'stalled' | 'success' | 'failed'

type SummaryState = { status: 'loading' } | { status: 'loaded'; data: EmbeddingSummaryResponse } | { status: 'error'; detail: string }

type HotelListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: HotelRow[]; total: number }
  | { status: 'empty' }
  | { status: 'error'; detail: string }

interface EmbeddingStatusPageProps {
  navigate: (to: string) => void
}

/** embedding-status-page.tsx — merges C4's coverage overview (phase-12-
 * embedding-status.md) with B7's per-hotel table: top cards + recently-
 * missing sample stay C4's read-only overview, the bottom section is B7's
 * paginated, filterable, selectable hotel list with the batch reembed
 * action -- "B7 thực chất là B1 với bộ lọc khác + 1 cột khác". Lives at
 * /admin/embedding under KHÁCH SẠN now that the standalone Pipeline/Dữ
 * liệu bot nav group is gone; the pipeline trigger action moved to Tổng
 * quan (/admin), so links here point there instead of a deleted page. */
export function EmbeddingStatusPage({ navigate }: EmbeddingStatusPageProps) {
  const [summary, setSummary] = useState<SummaryState>({ status: 'loading' })

  const [source, setSource] = useState<SourceFilter>('all')
  const [page, setPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)
  const [hotelListState, setHotelListState] = useState<HotelListState>({ status: 'loading' })
  const [isFetchingHotels, setIsFetchingHotels] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [reembedConfirmOpen, setReembedConfirmOpen] = useState(false)
  const [reembedIncludeRooms, setReembedIncludeRooms] = useState(false)
  const [reembedBusy, setReembedBusy] = useState(false)
  const [reembedError, setReembedError] = useState<string | null>(null)
  const [reembedRunState, setReembedRunState] = useState<ReembedRunState>('idle')
  const [reembedHotelCount, setReembedHotelCount] = useState(0)
  const [embeddingRun, setEmbeddingRun] = useState<PipelineItem | null>(null)
  const embeddingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const embeddingPollAttemptsRef = useRef(0)
  // Same `max_active_runs=1` queueing caveat as hotel-detail-page.tsx: must
  // track THIS trigger's dag_run_id, not just whatever the DAG's `last_run`
  // happens to be, or an unrelated run finishing first reads as "thành công"
  // before this batch's own (still-queued) run has executed.
  const embeddingDagRunIdRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getEmbeddingSummary().then((result) => {
      if (cancelled) return
      if (!result.ok) return setSummary({ status: 'error', detail: result.detail })
      setSummary({ status: 'loaded', data: result.data })
    })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setIsFetchingHotels(true)
    setHotelListState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listHotels({ source, embedding: 'incomplete', page, pageSize: PAGE_SIZE }).then((result) => {
      if (cancelled) return
      setIsFetchingHotels(false)
      if (!result.ok) return setHotelListState({ status: 'error', detail: result.detail })
      if (result.data.items.length === 0) return setHotelListState({ status: 'empty' })
      setHotelListState({ status: 'loaded', items: result.data.items, total: result.data.total })
    })
    return () => {
      cancelled = true
    }
  }, [source, page, refreshKey])

  const hotelItems = hotelListState.status === 'loaded' ? hotelListState.items : []
  const hotelTotal = hotelListState.status === 'loaded' ? hotelListState.total : 0
  // The positive "bot đã học hết" copy is only true when nothing is being
  // filtered out -- an empty result under `source !== 'all'` just means
  // that slice has no gaps, not that the whole dataset is clean.
  const isUnfilteredSource = source === 'all'

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
      const allSelected = hotelItems.length > 0 && hotelItems.every((row) => prev.has(row.id))
      if (allSelected) return new Set()
      return new Set(hotelItems.map((row) => row.id))
    })
  }

  async function handleReembedSelected() {
    setReembedBusy(true)
    setReembedError(null)
    const hotelIds = Array.from(selectedIds)
    const result = await reembedHotels(hotelIds, reembedIncludeRooms)
    setReembedBusy(false)
    setReembedConfirmOpen(false)
    setSelectedIds(new Set())
    if (!result.ok) {
      setReembedError(result.detail)
      return
    }
    setReembedHotelCount(hotelIds.length)
    if (!result.data.queued) {
      setReembedRunState('unavailable')
      setRefreshKey((k) => k + 1)
      return
    }
    setReembedRunState('queued')
    embeddingDagRunIdRef.current = result.data.dag_run_id ?? null
    if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    embeddingPollAttemptsRef.current = 0
    pollEmbeddingProgress()
  }

  // Polls the shared Pipelines list (same idiom as hotel-detail-page.tsx's
  // single-hotel reembed) so the banner shows real %-done instead of leaving
  // the admin staring at a static "đã gửi yêu cầu" with no idea when it'll
  // finish. Stops once the DAG's `last_run` is no longer running/queued and
  // refreshes the hotel table so rows pick up the outcome on their own.
  function pollEmbeddingProgress() {
    listPipelines().then((result) => {
      const embedding = result.ok ? (result.data.items.find((item: PipelineItem) => item.has_params) ?? null) : null
      const expectedRunId = embeddingDagRunIdRef.current
      if (expectedRunId && embedding?.last_run?.run_id !== expectedRunId) {
        setEmbeddingRun(null)
        embeddingPollAttemptsRef.current += 1
        if (embeddingPollAttemptsRef.current >= MAX_EMBEDDING_POLL_ATTEMPTS) {
          setReembedRunState('stalled')
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
          setReembedRunState('stalled')
          return
        }
        embeddingPollRef.current = setTimeout(pollEmbeddingProgress, EMBEDDING_POLL_MS)
        return
      }
      setReembedRunState(state === 'success' ? 'success' : state === 'failed' ? 'failed' : 'idle')
      setEmbeddingRun(null)
      setRefreshKey((k) => k + 1)
    })
  }

  function handleDismissReembed() {
    if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    embeddingDagRunIdRef.current = null
    setReembedRunState('idle')
    setEmbeddingRun(null)
  }

  return (
    <>
      <PageHeader breadcrumb="Quản trị · Khách sạn" title="Trạng thái embedding" />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
        {summary.status === 'loading' && <SkeletonTable rows={1} columnWidths={[200, 200, 200]} />}

        {summary.status === 'error' && <ErrorState description={summary.detail} />}

        {summary.status === 'loaded' && (
          <>
            <EmbeddingTableCards tables={summary.data.tables} />
          </>
        )}

        <div style={{ fontSize: 13.5, fontWeight: 700, marginTop: 8 }}>Khách sạn thiếu embedding</div>

        {reembedError && <Banner tone="err">{reembedError}</Banner>}

        {reembedRunState === 'unavailable' && (
          <Banner tone="warn">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1 }}>
                Đã đánh dấu {reembedHotelCount} khách sạn cần nhúng lại. Pipeline sẽ tự nhặt ở lần chạy kế tiếp, hoặc chạy ngay ở trang Tổng quan.
              </span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}

        {reembedRunState === 'stalled' && (
          <Banner tone="warn">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1, minWidth: 200 }}>
                Pipeline embedding đang chờ lâu hơn bình thường (Airflow chưa bắt đầu chạy). Đã đánh dấu {reembedHotelCount} khách sạn cần nhúng lại, bot sẽ học khi pipeline chạy.
              </span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}

        {reembedRunState === 'queued' && (
          <Banner tone="ok">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
                <span style={{ flex: 1 }}>Đã gửi yêu cầu chạy lại embedding cho {reembedHotelCount} khách sạn.</span>
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

        {reembedRunState === 'success' && (
          <Banner tone="ok">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1 }}>Đã embed thành công {reembedHotelCount} khách sạn — chatbot đã học nội dung mới.</span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}

        {reembedRunState === 'failed' && (
          <Banner tone="err">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
              <span style={{ flex: 1, minWidth: 200 }}>Chạy embedding thất bại. Thử chạy lại pipeline ở trang Tổng quan.</span>
              <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                ✕
              </Button>
            </div>
          </Banner>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Select value={source} onChange={(e) => setSource(e.target.value as SourceFilter)} style={{ width: 200 }}>
            <option value="all">Nguồn: Tất cả</option>
            <option value="manual">Tự nhập</option>
            <option value="pipeline">Từ pipeline</option>
          </Select>
          {selectedIds.size > 0 && (
            <Button variant="primary" size="sm" disabled={reembedBusy} onClick={() => setReembedConfirmOpen(true)}>
              Chạy embedding cho {selectedIds.size} khách sạn
            </Button>
          )}
        </div>

        {hotelListState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[16, 220, 90, 80, 100, 100, 32]} />}

        {hotelListState.status === 'error' && (
          <div className="card">
            <ErrorState description={hotelListState.detail} onRetry={() => setRefreshKey((k) => k + 1)} />
          </div>
        )}

        {hotelListState.status === 'empty' && isUnfilteredSource && (
          <div className="card">
            <EmptyState title="✓ Toàn bộ dữ liệu đã được bot học." description="Không có khách sạn hay phòng nào đang thiếu embedding." />
          </div>
        )}

        {hotelListState.status === 'empty' && !isUnfilteredSource && (
          <div className="card">
            <EmptyState description="Không có khách sạn hoặc phòng nào thiếu embedding khớp bộ lọc nguồn hiện tại." />
          </div>
        )}

        {hotelListState.status === 'loaded' && (
          <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ overflowX: 'auto' }}>
              <EmbeddingStatusTable
                rows={hotelListState.items}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onToggleSelectAll={toggleSelectAll}
                onOpenHotel={(id) => navigate(`/admin/hotels/${id}`)}
                loading={isFetchingHotels}
              />
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={hotelTotal} onPageChange={setPage} loading={isFetchingHotels} />
          </div>
        )}
      </div>

      <ReembedConfirmDialog
        open={reembedConfirmOpen}
        count={selectedIds.size}
        includeRooms={reembedIncludeRooms}
        busy={reembedBusy}
        onIncludeRoomsChange={setReembedIncludeRooms}
        onConfirm={handleReembedSelected}
        onClose={() => setReembedConfirmOpen(false)}
      />
    </>
  )
}
