import { DataTable, type DataTableColumn } from '../../ui/data-table'
import { categoryLabel } from '../../lib/amenity-categories'
import type { AmenityCatalogRow, CatalogSortDirection, CatalogSortKey } from '../../api/amenity-catalog-client'

interface AmenityTableProps {
  rows: AmenityCatalogRow[]
  onEdit: (row: AmenityCatalogRow) => void
  onApprove: (row: AmenityCatalogRow) => void
  onReject: (row: AmenityCatalogRow) => void
  onRetire: (row: AmenityCatalogRow) => void
  onReactivate: (row: AmenityCatalogRow) => void
  busyId: string | null
  loading?: boolean
  sortKey: CatalogSortKey
  sortDirection: CatalogSortDirection
  onSortChange: (key: CatalogSortKey) => void
}

function usageText(row: AmenityCatalogRow): string {
  const parts: string[] = []
  if (row.hotel_count > 0) parts.push(`${row.hotel_count} khách sạn`)
  if (row.room_count > 0) parts.push(`${row.room_count} phòng`)
  return parts.length > 0 ? parts.join(' · ') : 'Chưa dùng'
}

function scopeLabel(scope: AmenityCatalogRow['scope']): string {
  return scope === 'room' ? 'Phòng' : 'Khách sạn'
}

/** Reuses the shared 3-state dot (ui pattern from hotel-embedding-dot.tsx)
 * instead of a new component -- "Đã duyệt"/"Chờ duyệt"/"Đã ngừng dùng" are
 * exactly the same "mark + label" shape, just a third `--muted` variant
 * added to admin.css for retired (phase-18 decision: not one of B1's own
 * two states, so it isn't reused as-is, only its structure). */
function StatusDot({ row }: { row: AmenityCatalogRow }) {
  if (!row.is_approved) {
    return (
      <span className="embedding-dot">
        <span className="embedding-dot__mark embedding-dot__mark--warn" />
        <span className="embedding-dot__label embedding-dot__label--warn">Chờ duyệt</span>
      </span>
    )
  }
  if (row.retired_at) {
    return (
      <span className="embedding-dot">
        <span className="embedding-dot__mark embedding-dot__mark--muted" />
        <span className="embedding-dot__label embedding-dot__label--muted">Đã ngừng dùng</span>
      </span>
    )
  }
  return (
    <span className="embedding-dot">
      <span className="embedding-dot__mark embedding-dot__mark--ok" />
      <span className="embedding-dot__label embedding-dot__label--ok">Đã duyệt</span>
    </span>
  )
}

export function AmenityTable({
  rows,
  onEdit,
  onApprove,
  onReject,
  onRetire,
  onReactivate,
  busyId,
  loading,
  sortKey,
  sortDirection,
  onSortChange,
}: AmenityTableProps) {
  const columns: DataTableColumn<AmenityCatalogRow>[] = [
    {
      key: 'name',
      header: 'TÊN',
      sortValue: (row) => row.label_vi,
      render: (row) => (
        <div style={{ padding: '8px 0' }}>
          <div style={{ fontWeight: 600 }}>{row.label_vi}</div>
          <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>{row.label_en}</div>
        </div>
      ),
    },
    {
      key: 'category',
      header: 'NHÓM',
      width: 170,
      sortValue: (row) => categoryLabel(row.category),
      render: (row) => <span className="chip chip--closed">{categoryLabel(row.category)}</span>,
    },
    {
      key: 'scope',
      header: 'PHẠM VI',
      width: 160,
      sortValue: (row) => row.scope,
      render: (row) => (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="chip chip--closed">{scopeLabel(row.scope)}</span>
          {row.scope === 'both' && <span className="chip chip--closed">Phòng</span>}
        </div>
      ),
    },
    {
      key: 'usage',
      header: 'DÙNG Ở',
      width: 160,
      sortValue: (row) => row.hotel_count + row.room_count,
      render: (row) => <span className="tabular-nums">{usageText(row)}</span>,
    },
    {
      key: 'status',
      header: 'TRẠNG THÁI',
      width: 130,
      // Chờ duyệt trước Đã duyệt trước Đã ngừng dùng -- what needs attention first.
      sortValue: (row) => (!row.is_approved ? 0 : row.retired_at ? 2 : 1),
      render: (row) => <StatusDot row={row} />,
    },
    {
      key: 'actions',
      header: '',
      width: 220,
      align: 'right',
      render: (row) => {
        const isBusy = busyId === row.id
        if (!row.is_approved) {
          return (
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }} onClick={(e) => e.stopPropagation()}>
              <button type="button" className="btn btn--primary btn--sm" disabled={isBusy} onClick={() => onApprove(row)}>
                Duyệt
              </button>
              <button type="button" className="btn btn--danger btn--sm" disabled={isBusy} onClick={() => onReject(row)}>
                Từ chối
              </button>
            </div>
          )
        }
        if (row.retired_at) {
          return (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }} onClick={(e) => e.stopPropagation()}>
              <button type="button" className="btn btn--secondary btn--sm" disabled={isBusy} onClick={() => onReactivate(row)}>
                Bật lại
              </button>
            </div>
          )
        }
        const usageBlocked = row.hotel_count + row.room_count > 0
        const childBlocked = row.child_count > 0
        const blocked = usageBlocked || childBlocked
        const title = usageBlocked ? `Đang dùng ở ${usageText(row)}` : childBlocked ? `Còn ${row.child_count} tiện ích con` : undefined
        return (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }} onClick={(e) => e.stopPropagation()}>
            <button type="button" className="btn btn--secondary btn--sm" disabled={isBusy} onClick={() => onEdit(row)}>
              Sửa
            </button>
            <button type="button" className="btn btn--secondary btn--sm" disabled={isBusy || blocked} title={title} onClick={() => onRetire(row)}>
              Ngừng dùng
            </button>
          </div>
        )
      },
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      rowClassName={(row) => (!row.is_approved ? 'row--attention' : undefined)}
      onRowClick={(row) => (row.is_approved && !row.retired_at ? onEdit(row) : undefined)}
      loading={loading}
      sortState={{ key: sortKey, direction: sortDirection }}
      onSortChange={(key) => onSortChange(key as CatalogSortKey)}
    />
  )
}
