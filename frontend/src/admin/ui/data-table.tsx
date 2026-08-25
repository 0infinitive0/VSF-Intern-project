import { useMemo, useState, type ReactNode } from 'react'
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from '@tanstack/react-table'
import { Spinner } from './spinner'

export interface DataTableColumn<T> {
  key: string
  header: ReactNode
  width?: number
  align?: 'left' | 'right'
  render: (row: T) => ReactNode
  /** Raw comparable value for this column -- omit to leave the column unsortable. */
  sortValue?: (row: T) => string | number | null | undefined
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string
  /** Extra class(es) for one row -- e.g. hotels-table.tsx's striped
   * "from pipeline" background and the selected-row overlay. */
  rowClassName?: (row: T) => string | undefined
  onRowClick?: (row: T) => void
  /** Background refetch in flight -- dims current rows and centers a
   * spinner over the table instead of unmounting into a skeleton. */
  loading?: boolean
  /** Server-side sort: when set, rows are assumed to already be in the
   * requested order and clicking a sortable header calls `onSortChange`
   * instead of the table doing its own client-side (rows-already-loaded-
   * only) sort. Omit both to keep the default client-side behavior used by
   * hotels-table.tsx/price-range-table.tsx/hotel-tab-rooms.tsx. */
  sortState?: { key: string; direction: 'asc' | 'desc' } | null
  onSortChange?: (key: string) => void
}

const DEFAULT_COLUMN_WIDTH = 150
const MIN_COLUMN_WIDTH = 40

interface ColumnMeta {
  align?: 'left' | 'right'
}

export function DataTable<T>({ columns, rows, rowKey, rowClassName, onRowClick, loading, sortState, onSortChange }: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const controlled = !!onSortChange

  const columnDefs = useMemo<ColumnDef<T, unknown>[]>(
    () =>
      columns.map((col) => ({
        id: col.key,
        accessorFn: col.sortValue ?? (() => undefined),
        header: () => col.header,
        cell: (ctx) => col.render(ctx.row.original),
        size: col.width ?? DEFAULT_COLUMN_WIDTH,
        minSize: MIN_COLUMN_WIDTH,
        enableSorting: !!col.sortValue,
        meta: { align: col.align } satisfies ColumnMeta,
      })),
    [columns],
  )

  const table = useReactTable({
    data: rows,
    columns: columnDefs,
    state: { sorting: controlled ? [] : sorting },
    onSortingChange: controlled ? undefined : setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: controlled ? undefined : getSortedRowModel(),
    enableColumnResizing: true,
    columnResizeMode: 'onChange',
  })

  return (
    <div className="data-table-scroll">
      <table className="data-table" data-loading={loading || undefined} style={{ minWidth: table.getTotalSize() }}>
        <colgroup>
          {table.getFlatHeaders().map((header) => (
            <col key={header.id} style={{ width: header.getSize() }} />
          ))}
        </colgroup>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => {
                const align = (header.column.columnDef.meta as ColumnMeta | undefined)?.align
                const sortDir = controlled ? (sortState?.key === header.column.id ? sortState.direction : false) : header.column.getIsSorted()
                const canSort = header.column.getCanSort()
                return (
                  <th
                    key={header.id}
                    data-align={align === 'right' ? 'right' : undefined}
                    className={canSort ? 'data-table__th--sortable' : undefined}
                    onClick={canSort ? (controlled ? () => onSortChange!(header.column.id) : header.column.getToggleSortingHandler()) : undefined}
                  >
                    <span className="data-table__th-label">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {canSort && (
                        <span className="data-table__sort-icon" data-active={sortDir !== false}>
                          {sortDir === 'asc' ? '↑' : sortDir === 'desc' ? '↓' : '↕'}
                        </span>
                      )}
                    </span>
                    {header.column.getCanResize() && (
                      <div
                        className="data-table__resizer"
                        data-resizing={header.column.getIsResizing() || undefined}
                        onClick={(e) => e.stopPropagation()}
                        onDoubleClick={() => header.column.resetSize()}
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                      />
                    )}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={rowKey(row.original)}
              className={rowClassName?.(row.original)}
              onClick={onRowClick ? () => onRowClick(row.original) : undefined}
              style={onRowClick ? { cursor: 'pointer' } : undefined}
            >
              {row.getVisibleCells().map((cell) => {
                const align = (cell.column.columnDef.meta as ColumnMeta | undefined)?.align
                return (
                  <td key={cell.id} data-align={align === 'right' ? 'right' : undefined}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {loading && (
        <div className="data-table-loading-overlay">
          <Spinner size={22} />
        </div>
      )}
    </div>
  )
}
