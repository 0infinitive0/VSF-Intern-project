import type { ReactNode } from 'react'
import { Money } from '../../ui/money'
import type { OrderStatsResponse } from '../../api/orders-client'

interface OrderStatCardsProps {
  stats: OrderStatsResponse | null
}

interface StatCardProps {
  label: string
  value: ReactNode
  subline: ReactNode
  valueColor?: string
  rail?: string
}

/** D1's 4 `orderStats` cards (phase-04-orders-list.md) -- `--g3` background,
 * 16px radius, 26px tabular-nums figures. `rail`/`valueColor` are only set
 * for the two attention-worthy cards (Chờ xử lý, Giữ chỗ sắp hết hạn). */
function StatCard({ label, value, subline, valueColor, rail }: StatCardProps) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: 'var(--g3)',
        border: '1px solid var(--stroke)',
        borderRadius: 16,
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        boxShadow: rail,
      }}
    >
      <div style={{ fontSize: 12, color: 'var(--t3)' }}>{label}</div>
      <div className="tabular-nums" style={{ fontSize: 26, fontWeight: 700, color: valueColor }}>
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>{subline}</div>
    </div>
  )
}

function SkeletonCard() {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        height: 84,
        borderRadius: 16,
        background: 'var(--g3)',
        border: '1px solid var(--stroke)',
      }}
    />
  )
}

export function OrderStatCards({ stats }: OrderStatCardsProps) {
  if (!stats) {
    return (
      <div style={{ display: 'flex', gap: 12 }}>
        {Array.from({ length: 4 }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    )
  }

  const orderDelta = stats.orders_today - stats.orders_yesterday
  const deltaLabel = orderDelta === 0 ? 'Không đổi so với hôm qua' : `${orderDelta > 0 ? '+' : ''}${orderDelta} so với hôm qua`

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      <StatCard label="Đơn hôm nay" value={stats.orders_today} subline={deltaLabel} />
      <StatCard
        label="Doanh thu hôm nay"
        value={<Money value={Number(stats.revenue_today)} />}
        subline={
          <>
            Trung bình <Money value={Number(stats.avg_order_value)} />/đơn
          </>
        }
      />
      <StatCard
        label="Chờ xử lý"
        value={stats.pending_count}
        subline={`${stats.pending_over_2h} quá 2 giờ`}
        valueColor="var(--warn-ink)"
        rail="inset 3px 0 0 var(--warn)"
      />
      <StatCard
        label="Giữ chỗ sắp hết hạn"
        value={stats.expiring_holds_30m}
        subline="Hết hạn trong 30 phút tới"
        valueColor="var(--err)"
        rail="inset 3px 0 0 var(--err)"
      />
    </div>
  )
}
