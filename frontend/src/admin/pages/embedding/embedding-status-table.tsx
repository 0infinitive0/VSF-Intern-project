import { DataTable, type DataTableColumn } from '../../ui/data-table'
import type { HotelRow } from '../../api/hotels-client'
import { HotelEmbeddingDot } from '../hotels/hotel-embedding-dot'
import { HotelSourceChip } from '../hotels/hotel-source-chip'

interface EmbeddingStatusTableProps {
  rows: HotelRow[]
  selectedIds: Set<string>
  onToggleSelect: (id: string) => void
  onToggleSelectAll: () => void
  onOpenHotel: (id: string) => void
  loading?: boolean
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

/** embedding-status-table.tsx — B7's table (phase-12-embedding-status.md):
 * "B7 thực chất là B1 với bộ lọc khác + 1 cột khác" -- shares `admin_hotel_rows`
 * (via hotels-client.ts's `listHotels`/`HotelRow`) and hotels-table.tsx's
 * dot/source-chip components, but swaps B1's ĐANG BÁN switch column for
 * PHÒNG CHƯA NHÚNG + TRẠNG THÁI, since B7 has no deactivate action. */
export function EmbeddingStatusTable({ rows, selectedIds, onToggleSelect, onToggleSelectAll, onOpenHotel, loading }: EmbeddingStatusTableProps) {
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
      render: (row) => (
        <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.name}</div>
      ),
    },
    { key: 'source', header: 'NGUỒN', render: (row) => <HotelSourceChip isManual={row.is_manual} /> },
    { key: 'room_count', header: 'SỐ PHÒNG', align: 'right', render: (row) => row.room_count },
    { key: 'rooms_missing', header: 'PHÒNG CHƯA NHÚNG', align: 'right', render: (row) => row.rooms_missing_embedding },
    {
      key: 'status',
      header: 'TRẠNG THÁI',
      render: (row) => (
        <HotelEmbeddingDot
          embeddingState={row.embedding_state}
          roomCount={row.room_count}
          roomsMissingEmbedding={row.rooms_missing_embedding}
          roomsStaleEmbedding={row.rooms_stale_embedding}
        />
      ),
    },
    { key: 'menu', header: '', width: 32, align: 'right', render: () => <span style={{ color: 'var(--t4)' }}>⋯</span> },
  ]

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      rowClassName={(row) => (selectedIds.has(row.id) ? 'row--selected' : undefined)}
      onRowClick={(row) => onOpenHotel(row.id)}
      loading={loading}
    />
  )
}
