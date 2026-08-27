import type { MoneySummary } from '../../api/overview-client'
import { formatCompactVnd } from '../../lib/format-compact-vnd'
import { BarChart, type Bar } from '../../ui/bar-chart'
import { Money } from '../../ui/money'

interface RevenueTrendCardProps {
  money: MoneySummary | null
}

const WEEKDAY_VI = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7']

/** revenue-trend-card.tsx — A3 bar chart of PAID revenue per day for the
 * last 7 VN-local days, oldest → today. The backend zero-fills quiet days,
 * so there are always exactly 7 bars; today's bar is drawn in the darker
 * `--ok-ink` to anchor the eye. Header total is the sum the bars represent. */
export function RevenueTrendCard({ money }: RevenueTrendCardProps) {
  const points = money?.revenue_trend ?? null
  const total = points?.reduce((sum, p) => sum + Number(p.revenue), 0) ?? 0

  const bars: Bar[] =
    points?.map((p, i) => {
      const d = new Date(`${p.date}T00:00:00`)
      return {
        label: WEEKDAY_VI[d.getDay()],
        value: Number(p.revenue),
        color: i === points.length - 1 ? 'var(--ok-ink)' : 'var(--ok)',
        sublabel: String(d.getDate()),
      }
    }) ?? []

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Doanh thu 7 ngày</div>
        {points && (
          <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>
            Tổng <Money value={total} />
          </div>
        )}
      </div>

      {points === null ? (
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 148 }}>
          {Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="skeleton-bar" style={{ flex: 1, height: `${30 + ((i * 37) % 60)}%` }} />
          ))}
        </div>
      ) : (
        <BarChart bars={bars} orientation="vertical" height={132} formatValue={formatCompactVnd} />
      )}
    </div>
  )
}
