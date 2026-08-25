import { Button } from '../../ui/button'
import { DateText } from '../../ui/date-text'

export interface ActiveOrderFilter {
  key: string
  label: string
  clause: string
  onRemove: () => void
}

interface OrdersEmptyProps {
  from: string
  to: string
  filters: ActiveOrderFilter[]
  onClearAll: () => void
}

/** D1's "bộ lọc không khớp" empty state -- distinct from "chưa có đơn nào"
 * (Phase 3's shared `EmptyState`, used when there's no filter at all). Every
 * active filter renders as a removable chip, and the description sentence
 * interpolates the real filter values rather than a generic message. */
export function OrdersEmpty({ from, to, filters, onClearAll }: OrdersEmptyProps) {
  const rangePrefix = from && to ? (
    <>
      Trong <DateText value={from} /> – <DateText value={to} />{' '}
    </>
  ) : null
  const clauses = filters.map((f) => f.clause).join(' ')

  return (
    <div className="state-block">
      {filters.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
          {filters.map((filter) => (
            <span key={filter.key} className="chip chip--closed" style={{ gap: 8 }}>
              {filter.label}
              <button
                type="button"
                onClick={filter.onRemove}
                aria-label={`Bỏ lọc ${filter.label}`}
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'inherit', font: 'inherit' }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="state-block__icon state-block__icon--empty">▢</div>
      <div className="state-block__title">Không có đơn nào khớp</div>
      <div className="state-block__desc">
        {rangePrefix}không có đơn nào{clauses ? ` ${clauses}` : ''}.
      </div>
      {filters.length > 0 && (
        <Button variant="secondary" size="sm" onClick={onClearAll}>
          Xoá {filters.length} bộ lọc
        </Button>
      )}
    </div>
  )
}
