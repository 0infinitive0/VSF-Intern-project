import type { ReactNode } from 'react'

export interface DataTableColumn<T> {
  key: string
  header: ReactNode
  width?: number
  align?: 'left' | 'right'
  render: (row: T) => ReactNode
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string
  /** Extra class(es) for one row -- e.g. hotels-table.tsx's striped
   * "from pipeline" background and the selected-row overlay. */
  rowClassName?: (row: T) => string | undefined
  onRowClick?: (row: T) => void
}

export function DataTable<T>({ columns, rows, rowKey, rowClassName, onRowClick }: DataTableProps<T>) {
  return (
    <table className="data-table">
      <colgroup>
        {columns.map((col) => (
          <col key={col.key} style={col.width ? { width: col.width } : undefined} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {columns.map((col) => (
            <th key={col.key} data-align={col.align === 'right' ? 'right' : undefined}>
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            className={rowClassName?.(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            style={onRowClick ? { cursor: 'pointer' } : undefined}
          >
            {columns.map((col) => (
              <td key={col.key} data-align={col.align === 'right' ? 'right' : undefined}>
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
