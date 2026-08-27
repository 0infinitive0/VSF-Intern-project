import type { ReactNode } from 'react'
import type { RevenueSlicePoint } from '../../api/overview-client'
import { formatCompactVnd } from '../../lib/format-compact-vnd'
import { BarChart, type Bar } from '../../ui/bar-chart'
import { EmptyState } from '../../ui/empty-state'

interface RevenueSliceCardProps {
  title: string
  caption?: ReactNode
  /** `null` = still loading. */
  slices: RevenueSlicePoint[] | null
  emptyTitle: string
  emptyDescription: string
}

/** revenue-slice-card.tsx — A3 "revenue by X" horizontal bars, top 5.
 * Backs both the by-hotel and by-destination cards (`get_money_summary`
 * returns each as a `RevenueSlicePoint[]`). Each order's whole amount is
 * credited to its primary hotel / that hotel's destination — multi-hotel
 * orders aren't split, so read it as "what's driving bookings", not a
 * ledger. `null` → skeleton; empty list → positive empty state. */
export function RevenueSliceCard({ title, caption, slices, emptyTitle, emptyDescription }: RevenueSliceCardProps) {
  const bars: Bar[] = slices?.map((s) => ({ label: s.label, value: Number(s.revenue) })) ?? []

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>{title}</div>
        {caption != null && <div style={{ fontSize: 12, color: 'var(--t3)' }}>{caption}</div>}
      </div>

      {slices === null ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="skeleton-bar" style={{ width: `${90 - i * 12}%`, height: 12 }} />
          ))}
        </div>
      ) : slices.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} />
      ) : (
        <BarChart bars={bars} orientation="horizontal" accent="var(--ok)" formatValue={formatCompactVnd} />
      )}
    </div>
  )
}
