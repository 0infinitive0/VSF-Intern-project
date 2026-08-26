import { useEffect, useState } from 'react'
import {
  approveAmenity,
  deleteAmenity,
  listAmenityCatalog,
  reactivateAmenity,
  retireAmenity,
  type AmenityCatalogRow,
  type CatalogSortDirection,
  type CatalogSortKey,
  type CatalogStatus,
  type RetireBlockedError,
} from '../../api/amenity-catalog-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { EmptyState } from '../../ui/empty-state'
import { ErrorState } from '../../ui/error-state'
import { Pagination } from '../../ui/pagination'
import { SkeletonTable } from '../../ui/skeleton-table'
import { Tabs } from '../../ui/tabs'
import { AddAmenityFlow } from './add-amenity-flow'
import { AmenityDraftReviewList } from './amenity-draft-review-list'
import { AmenityEditDrawer } from './amenity-edit-drawer'
import { AmenityTable } from './amenity-table'
import { AmenityToolbar } from './amenity-toolbar'
import { RetireBlockedDialog } from './retire-blocked-dialog'

const PAGE_SIZE = 25

type ListState =
  | { status: 'loading' }
  | { status: 'loaded'; items: AmenityCatalogRow[]; total: number; pendingCount: number }
  | { status: 'empty'; pendingCount: number }
  | { status: 'error'; detail: string }

/** amenity-catalog-page.tsx -- Danh mục tiện ích & tiện nghi
 * (phase-18-amenity-catalog.md). Owns filter/list state, the row-level write
 * flows (approve/reject/retire/reactivate), and the two multi-step
 * sub-flows (add, draft review) -- table/toolbar stay presentational, same
 * split as B1's hotels-page.tsx. */
export function AmenityCatalogPage() {
  const [scope, setScope] = useState<'hotel' | 'room'>('hotel')
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [category, setCategory] = useState('all')
  const [status, setStatus] = useState<CatalogStatus>('all')
  const [sortKey, setSortKey] = useState<CatalogSortKey>('name')
  const [sortDirection, setSortDirection] = useState<CatalogSortDirection>('asc')
  const [page, setPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)

  const [listState, setListState] = useState<ListState>({ status: 'loading' })
  const [isFetching, setIsFetching] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [rowError, setRowError] = useState<string | null>(null)

  const [editingRow, setEditingRow] = useState<AmenityCatalogRow | null>(null)
  const [addFlowOpen, setAddFlowOpen] = useState(false)
  const [draftItems, setDraftItems] = useState<AmenityCatalogRow[] | null>(null)
  const [retireBlocked, setRetireBlocked] = useState<{ row: AmenityCatalogRow; blocked: RetireBlockedError } | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), 300)
    return () => clearTimeout(timer)
  }, [q])

  useEffect(() => {
    setPage(1)
  }, [scope, debouncedQ, category, status, sortKey, sortDirection])

  useEffect(() => {
    let cancelled = false
    setIsFetching(true)
    setListState((prev) => (prev.status === 'loaded' ? prev : { status: 'loading' }))
    listAmenityCatalog({ scope, status, category, q: debouncedQ || undefined, sort: sortKey, direction: sortDirection, page, pageSize: PAGE_SIZE }).then(
      (result) => {
        if (cancelled) return
        setIsFetching(false)
        if (!result.ok) return setListState({ status: 'error', detail: result.detail })
        if (result.data.items.length === 0) return setListState({ status: 'empty', pendingCount: result.data.pending_count })
        setListState({ status: 'loaded', items: result.data.items, total: result.data.total, pendingCount: result.data.pending_count })
      },
    )
    return () => {
      cancelled = true
    }
  }, [scope, status, category, debouncedQ, sortKey, sortDirection, page, refreshKey])

  // Same key again flips direction; a different key starts fresh at
  // ascending -- no third "unsorted" state, since the backend always orders
  // by something (label_vi by default) so there's no meaningful "off".
  function handleSortChange(key: CatalogSortKey) {
    if (key === sortKey) setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const items = listState.status === 'loaded' ? listState.items : []
  const total = listState.status === 'loaded' ? listState.total : 0
  const pendingCount = listState.status === 'loaded' || listState.status === 'empty' ? listState.pendingCount : 0

  function refresh() {
    setRefreshKey((k) => k + 1)
  }

  async function handleApprove(row: AmenityCatalogRow) {
    setBusyId(row.id)
    setRowError(null)
    const result = await approveAmenity(row.id)
    setBusyId(null)
    if (!result.ok) return setRowError(result.detail)
    refresh()
  }

  async function handleReject(row: AmenityCatalogRow) {
    setBusyId(row.id)
    setRowError(null)
    const result = await deleteAmenity(row.id)
    setBusyId(null)
    if (!result.ok) return setRowError(result.detail)
    refresh()
  }

  async function handleRetire(row: AmenityCatalogRow) {
    setBusyId(row.id)
    setRowError(null)
    const result = await retireAmenity(row.id)
    setBusyId(null)
    if (!result.ok) {
      if (result.blocked) setRetireBlocked({ row, blocked: result.blocked })
      else setRowError(result.detail)
      return
    }
    refresh()
  }

  async function handleReactivate(row: AmenityCatalogRow) {
    setBusyId(row.id)
    setRowError(null)
    const result = await reactivateAmenity(row.id)
    setBusyId(null)
    if (!result.ok) return setRowError(result.detail)
    refresh()
  }

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Khách sạn"
        title="Danh mục tiện ích & tiện nghi"
        action={
          <>
            {pendingCount > 0 && <span className="chip chip--pending tabular-nums">{pendingCount} chờ duyệt</span>}
            <Button variant="primary" size="sm" onClick={() => setAddFlowOpen(true)}>
              + Thêm tiện ích
            </Button>
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, padding: '18px 28px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        {rowError && <Banner tone="err">{rowError}</Banner>}

        <Tabs
          items={[
            { key: 'hotel', label: 'Tiện ích khách sạn' },
            { key: 'room', label: 'Tiện nghi phòng' },
          ]}
          activeKey={scope}
          onChange={(key) => setScope(key as 'hotel' | 'room')}
        />

        <AmenityToolbar
          q={q}
          onQChange={setQ}
          category={category}
          onCategoryChange={setCategory}
          status={status}
          onStatusChange={setStatus}
          shownCount={items.length}
          totalCount={total}
        />

        {listState.status === 'loading' && <SkeletonTable rows={8} columnWidths={[220, 170, 160, 160, 130, 220]} />}

        {listState.status === 'error' && (
          <div className="card">
            <ErrorState description={listState.detail} onRetry={refresh} />
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
              <AmenityTable
                rows={items}
                onEdit={setEditingRow}
                onApprove={handleApprove}
                onReject={handleReject}
                onRetire={handleRetire}
                onReactivate={handleReactivate}
                busyId={busyId}
                loading={isFetching}
                sortKey={sortKey}
                sortDirection={sortDirection}
                onSortChange={handleSortChange}
              />
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} loading={isFetching} />
          </div>
        )}
      </div>

      <AddAmenityFlow open={addFlowOpen} onClose={() => setAddFlowOpen(false)} scope={scope} onDrafted={setDraftItems} />

      <AmenityDraftReviewList
        open={draftItems !== null}
        onClose={() => setDraftItems(null)}
        items={draftItems ?? []}
        scope={scope}
        onDone={() => {
          setDraftItems(null)
          refresh()
        }}
      />

      <AmenityEditDrawer
        open={editingRow !== null}
        onClose={() => setEditingRow(null)}
        row={editingRow}
        scope={scope}
        onSaved={() => {
          setEditingRow(null)
          refresh()
        }}
      />

      <RetireBlockedDialog
        open={retireBlocked !== null}
        onClose={() => setRetireBlocked(null)}
        row={retireBlocked?.row ?? null}
        blocked={retireBlocked?.blocked ?? null}
        onReload={refresh}
      />
    </>
  )
}
