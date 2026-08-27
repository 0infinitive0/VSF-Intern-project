import type { MoneySummary } from '../../api/overview-client'
import { formatCurrency } from '../../../lib/format-currency'
import { formatCompactVnd } from '../../lib/format-compact-vnd'
import { DonutChart } from '../../ui/donut-chart'
import { EmptyState } from '../../ui/empty-state'

interface CollectedOutstandingCardProps {
  money: MoneySummary | null
}

/** collected-outstanding-card.tsx — A3 donut: money in hand vs money still
 * owed. `collected_today` = PAID payments that landed today; `outstanding` =
 * every still-PENDING payment (checkout started, VNPay never returned) — the
 * value twin of the `pending_count` tile. `null` renders the skeleton. */
export function CollectedOutstandingCard({ money }: CollectedOutstandingCardProps) {
  const collected = money ? Number(money.collected_today) : 0
  const outstanding = money ? Number(money.outstanding) : 0

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 700 }}>Đã thu / Còn treo</div>

      {money === null ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div className="skeleton-bar" style={{ width: 132, height: 132, borderRadius: 999, flexShrink: 0 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
            <div className="skeleton-bar" style={{ width: '70%', height: 10 }} />
            <div className="skeleton-bar" style={{ width: '55%', height: 10 }} />
          </div>
        </div>
      ) : collected === 0 && outstanding === 0 ? (
        <EmptyState title="Chưa có khoản nào." description="Chưa có tiền về hôm nay và không có thanh toán nào đang treo." />
      ) : (
        <DonutChart
          segments={[
            { label: 'Đã thu hôm nay', value: collected, color: 'var(--ok)' },
            { label: 'Còn treo', value: outstanding, color: 'var(--warn)' },
          ]}
          centerLabel={formatCompactVnd(collected)}
          centerSub="đã thu"
          formatValue={(v) => formatCurrency(v, 'vi')}
        />
      )}
    </div>
  )
}
