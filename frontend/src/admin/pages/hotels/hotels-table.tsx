import { DataTable, type DataTableColumn } from '../../ui/data-table'
import { Switch } from '../../ui/switch'
import type { HotelRow } from '../../api/hotels-client'
import { HotelEmbeddingDot } from './hotel-embedding-dot'
import { HotelSourceChip } from './hotel-source-chip'

interface HotelsTableProps {
  rows: HotelRow[]
  selectedIds: Set<string>
  onToggleSelect: (id: string) => void
  onToggleSelectAll: () => void
  onToggleActive: (row: HotelRow, nextActive: boolean) => void
  onOpenHotel: (id: string) => void
  onDeleteHotel: (row: HotelRow) => void
  loading?: boolean
  sortState?: { key: string; direction: 'asc' | 'desc' } | null
  onSortChange?: (key: string) => void
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  const letters = parts.length === 1 ? parts[0].slice(0, 2) : parts[0][0] + parts[parts.length - 1][0]
  return letters.toUpperCase()
}

function RowCheckbox({ checked, onChange, label }: { checked: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      className="row-checkbox"
      data-checked={checked}
      onClick={(e) => {
        e.stopPropagation()
        onChange()
      }}
    >
      {checked ? '✓' : ''}
    </button>
  )
}

export function HotelsTable({
  rows,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  onToggleActive,
  onOpenHotel,
  onDeleteHotel,
  loading,
  sortState,
  onSortChange,
}: HotelsTableProps) {
  const allSelected = rows.length > 0 && rows.every((row) => selectedIds.has(row.id))

  const columns: DataTableColumn<HotelRow>[] = [
    {
      key: 'select',
      header: <RowCheckbox checked={allSelected} onChange={onToggleSelectAll} label="Chọn tất cả" />,
      width: 40,
      render: (row) => <RowCheckbox checked={selectedIds.has(row.id)} onChange={() => onToggleSelect(row.id)} label={`Chọn ${row.name}`} />,
    },
    {
      key: 'hotel',
      header: 'KHÁCH SẠN',
      sortValue: (row) => row.name,
      render: (row) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0' }}>
          <div className="hotel-avatar">{initials(row.name)}</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.name}</div>
            {row.address && (
              <div style={{ fontSize: 11.5, color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {row.address}
              </div>
            )}
          </div>
        </div>
      ),
    },
    { key: 'city', header: 'THÀNH PHỐ', sortValue: (row) => row.city ?? '', render: (row) => row.city ?? '—' },
    {
      key: 'star_rating',
      header: 'HẠNG SAO',
      sortValue: (row) => row.star_rating ?? 0,
      render: (row) => '★'.repeat(Math.max(0, Math.round(row.star_rating ?? 0))) || '—',
    },
    {
      key: 'source',
      header: 'NGUỒN',
      sortValue: (row) => (row.is_manual ? 'manual' : 'pipeline'),
      render: (row) => <HotelSourceChip isManual={row.is_manual} />,
    },
    { key: 'room_count', header: 'SỐ PHÒNG', align: 'right', sortValue: (row) => row.room_count, render: (row) => row.room_count },
    {
      key: 'embedding',
      header: 'EMBEDDING',
      sortValue: (row) => row.embedding_state,
      render: (row) => (
        <HotelEmbeddingDot embeddingState={row.embedding_state} roomCount={row.room_count} roomsMissingEmbedding={row.rooms_missing_embedding} />
      ),
    },
    {
      key: 'active',
      header: 'ĐANG BÁN',
      sortValue: (row) => (row.is_active ? 1 : 0),
      render: (row) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }} onClick={(e) => e.stopPropagation()}>
          <Switch checked={row.is_active} onChange={(next) => onToggleActive(row, next)} label={`Đang bán ${row.name}`} />
          <span style={{ fontSize: 11, color: row.is_active ? 'var(--t4)' : 'var(--t3)' }}>{row.is_active ? 'Đang bán' : 'Ngừng bán'}</span>
        </div>
      ),
    },
    {
      key: 'delete',
      header: '',
      width: 32,
      align: 'right',
      render: (row) => (
        <button
          type="button"
          className="row-delete-btn"
          aria-label={`Xoá ${row.name}`}
          title="Xoá khách sạn"
          onClick={(e) => {
            e.stopPropagation()
            onDeleteHotel(row)
          }}
        >
          🗑
        </button>
      ),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      rowClassName={(row) => [!row.is_manual && 'row--striped', selectedIds.has(row.id) && 'row--selected'].filter(Boolean).join(' ') || undefined}
      onRowClick={(row) => onOpenHotel(row.id)}
      loading={loading}
      sortState={sortState}
      onSortChange={onSortChange}
    />
  )
}
