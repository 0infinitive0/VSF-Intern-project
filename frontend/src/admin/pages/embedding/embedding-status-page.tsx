import { useEffect, useState } from 'react'
import { listHotels, reembedHotels, type HotelRow, type SourceFilter } from '../../api/hotels-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { EmptyState } from '../../ui/empty-state'
import { ErrorState } from '../../ui/error-state'
import { Pagination } from '../../ui/pagination'
import { Select } from '../../ui/select'
import { SkeletonTable } from '../../ui/skeleton-table'
import { EmbeddingStatusTable } from './embedding-status-table'
import { ReembedConfirmDialog } from './reembed-confirm-dialog'

const PAGE_SIZE = 25

type ListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: HotelRow[]; total: number }
  | { status: 'empty' }
  | { status: 'error'; detail: string }

interface EmbeddingStatusPageProps {
  navigate: (to: string) => void
}

/** embedding-status-page.tsx — B7 (phase-12-embedding-status.md). "B7 thực
 * chất là B1 với bộ lọc khác + 1 cột khác": reuses `listHotels`
 * (admin_hotel_rows) with `embedding=incomplete` as the default, non-
 * clearable filter -- there is no "show everything" toggle here, that
 * screen is B1. `incomplete` (not B1's `missing`) is deliberate: B1's
 * `missing` only catches `hotel_embedded=false`, which would hide a hotel
 * that's embedded itself but still has rooms missing theirs -- exactly the
 * gap this screen exists to surface. */
export function EmbeddingStatusPage({ navigate }: EmbeddingStatusPageProps) {
  const [source, setSource] = useState<SourceFilter>('all')
  const [page, setPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)

  const [listState, setListState] = useState<ListState>({ status: 'loading' })
  const [isFetching, setIsFetching] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [reembedConfirmOpen, setReembedConfirmOpen] = useState(false)
  const [reembedIncludeRooms, setReembedIncludeRooms] = useState(false)
  const [reembedBusy, setReembedBusy] = useState(false)
  const [reembedMessage, setReembedMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    setIsFetching(true)
    setListState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listHotels({ source, embedding: 'incomplete', page, pageSize: PAGE_SIZE }).then((result) => {
      if (cancelled) return
      setIsFetching(false)
      if (!result.ok) return setListState({ status: 'error', detail: result.detail })
      if (result.data.items.length === 0) return setListState({ status: 'empty' })
      setListState({ status: 'loaded', items: result.data.items, total: result.data.total })
    })
    return () => {
      cancelled = true
    }
  }, [source, page, refreshKey])

  const items = listState.status === 'loaded' ? listState.items : []
  const total = listState.status === 'loaded' ? listState.total : 0
  // The positive "bot đã học hết" copy is only true when nothing is being
  // filtered out -- an empty result under `source !== 'all'` just means
  // that slice has no gaps, not that the whole dataset is clean.
  const isUnfiltered = source === 'all'

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

  async function handleReembedSelected() {
    setReembedBusy(true)
    setReembedMessage(null)
    const hotelIds = Array.from(selectedIds)
    const result = await reembedHotels(hotelIds, reembedIncludeRooms)
    setReembedBusy(false)
    setReembedConfirmOpen(false)
    if (!result.ok) {
      setReembedMessage({ tone: 'err', text: result.detail })
      return
    }
    setReembedMessage({
      tone: 'ok',
      text: result.data.queued
        ? `Đã gửi yêu cầu chạy lại embedding cho ${hotelIds.length} khách sạn.`
        : `Đã đánh dấu ${hotelIds.length} khách sạn cần nhúng lại. Pipeline sẽ tự nhặt ở lần chạy kế tiếp, hoặc chạy ngay ở mục Dữ liệu bot.`,
    })
    setSelectedIds(new Set())
    setRefreshKey((k) => k + 1)
  }

  return (
    <>
      <PageHeader breadcrumb="Quản trị · Khách sạn" title="Trạng thái embedding" />

      <div style={{ flex: 1, minHeight: 0, padding: '22px 28px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        {reembedMessage && <Banner tone={reembedMessage.tone}>{reembedMessage.text}</Banner>}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Select value={source} onChange={(e) => setSource(e.target.value as SourceFilter)} style={{ width: 170 }}>
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

        {listState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[16, 220, 90, 80, 100, 100, 32]} />}

        {listState.status === 'error' && (
          <div className="card">
            <ErrorState description={listState.detail} onRetry={() => setRefreshKey((k) => k + 1)} />
          </div>
        )}

        {listState.status === 'empty' && isUnfiltered && (
          <div className="card">
            <EmptyState title="✓ Toàn bộ dữ liệu đã được bot học." description="Không có khách sạn hay phòng nào đang thiếu embedding." />
          </div>
        )}

        {listState.status === 'empty' && !isUnfiltered && (
          <div className="card">
            <EmptyState description="Không có khách sạn hoặc phòng nào thiếu embedding khớp bộ lọc nguồn hiện tại." />
          </div>
        )}

        {listState.status === 'loaded' && (
          <div className="card" style={{ overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ overflowX: 'auto' }}>
              <EmbeddingStatusTable
                rows={listState.items}
                selectedIds={selectedIds}
                onToggleSelect={toggleSelect}
                onToggleSelectAll={toggleSelectAll}
                onOpenHotel={(id) => navigate(`/admin/hotels/${id}`)}
                loading={isFetching}
              />
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} loading={isFetching} />
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
