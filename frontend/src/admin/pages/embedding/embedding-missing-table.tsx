import { DataTable, type DataTableColumn } from '../../ui/data-table'
import { DateText } from '../../ui/date-text'
import type { EmbeddedTable } from '../../api/embedding-client'

export interface MissingRow {
  table: EmbeddedTable
  tableLabel: string
  id: string
  name: string
  hotel_name: string | null
  updated_at: string | null
}

/** embedding-missing-table.tsx — C4's optional detail table (phase-12-
 * embedding-status.md): up to 20 most-recently-touched records still
 * missing embedding, merged across all three tables (the backend only
 * answers one table per call). */
export function EmbeddingMissingTable({ rows }: { rows: MissingRow[] }) {
  const columns: DataTableColumn<MissingRow>[] = [
    { key: 'table', header: 'BẢNG', width: 100, render: (row) => row.tableLabel },
    { key: 'name', header: 'TÊN', render: (row) => row.name },
    { key: 'hotel', header: 'THUỘC KHÁCH SẠN', render: (row) => row.hotel_name ?? '—' },
    { key: 'updated_at', header: 'CẬP NHẬT LÚC', render: (row) => (row.updated_at ? <DateText value={row.updated_at} withTime /> : '—') },
  ]

  return <DataTable columns={columns} rows={rows} rowKey={(row) => `${row.table}:${row.id}`} />
}
