import type { NightRow, RangeRow } from '../../../api/hotels-client'
import { Button } from '../../../ui/button'
import { DataTable, type DataTableColumn } from '../../../ui/data-table'
import { DateText } from '../../../ui/date-text'
import { Money } from '../../../ui/money'

type RangeStatus = 'available' | 'sold_out' | 'fully_booked'

function statusOf(range: RangeRow, nightsByDate: Map<string, NightRow>): RangeStatus {
  if (range.sold_out) return 'sold_out'
  const covered: NightRow[] = []
  for (let d = range.from; d < range.to; ) {
    const night = nightsByDate.get(d)
    if (night) covered.push(night)
    const next = new Date(d + 'T00:00:00Z')
    next.setUTCDate(next.getUTCDate() + 1)
    d = next.toISOString().slice(0, 10)
  }
  // L50: sold_out=false can still be fully booked out via real bookings --
  // only call it out when every night in the range agrees, since the merge
  // key (price, sold_out) doesn't guarantee uniform availability.
  if (covered.length > 0 && covered.every((n) => n.available === 0)) return 'fully_booked'
  return 'available'
}

const STATUS_LABEL: Record<RangeStatus, string> = {
  available: 'Còn phòng',
  sold_out: 'Hết phòng',
  fully_booked: 'Đã kín',
}

const STATUS_CLASS: Record<RangeStatus, string> = {
  available: 'chip--ok',
  sold_out: 'chip--closed',
  fully_booked: 'chip--warn',
}

interface PriceRangeTableProps {
  ranges: RangeRow[]
  nights: NightRow[]
  justSavedDates: Set<string>
  onEdit: (range: RangeRow) => void
  onDelete: (range: RangeRow) => void
}

/** to-exclusive -> last included night, for display and for the edit dialog's prefill. */
function lastNightInclusive(rangeTo: string): string {
  const d = new Date(rangeTo + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

function isJustSaved(range: RangeRow, justSavedDates: Set<string>): boolean {
  if (justSavedDates.size === 0) return false
  return [...justSavedDates].some((d) => d >= range.from && d < range.to)
}

export function PriceRangeTable({ ranges, nights, justSavedDates, onEdit, onDelete }: PriceRangeTableProps) {
  const nightsByDate = new Map(nights.map((n) => [n.date, n]))

  const columns: DataTableColumn<RangeRow>[] = [
    { key: 'from', header: 'TỪ NGÀY', render: (r) => <DateText value={r.from} /> },
    { key: 'to', header: 'ĐẾN NGÀY', render: (r) => <DateText value={lastNightInclusive(r.to)} /> },
    { key: 'nights', header: 'SỐ ĐÊM', render: (r) => `${r.nights} đêm` },
    {
      key: 'price',
      header: 'GIÁ / ĐÊM',
      render: (r) => (
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Money value={Number(r.price)} />
          {isJustSaved(r, justSavedDates) && <span className="price-range-row__just-saved-badge">Vừa sửa</span>}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'TÌNH TRẠNG',
      render: (r) => {
        const status = statusOf(r, nightsByDate)
        return <span className={`chip ${STATUS_CLASS[status]}`}>{STATUS_LABEL[status]}</span>
      },
    },
    {
      key: 'actions',
      header: 'THAO TÁC',
      align: 'right',
      render: (r) => (
        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={() => onEdit(r)}>
            Sửa
          </Button>
          {r.deletable && (
            <Button variant="danger" size="sm" onClick={() => onDelete(r)}>
              Xoá
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <DataTable
      columns={columns}
      rows={ranges}
      rowKey={(r) => `${r.from}-${r.to}`}
      rowClassName={(r) => (isJustSaved(r, justSavedDates) ? 'price-range-row--just-saved' : undefined)}
    />
  )
}
