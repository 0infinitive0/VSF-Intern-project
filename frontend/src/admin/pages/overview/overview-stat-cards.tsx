import type { ReactNode } from 'react'
import { Money } from '../../ui/money'
import type { OverviewOrders } from '../../api/overview-client'

interface OverviewStatCardsProps {
  orders: OverviewOrders | null
}

interface StatCardProps {
  label: string
  value: ReactNode
  subline: ReactNode
  valueColor?: string
  rail?: string
}

/** overview-stat-cards.tsx — A3's 4 `overviewStats` cards (phase-17-
 * overview-kpi.md), same shape as D1's order-stat-cards.tsx (`--g3`
 * background, 16px radius, 26px tabular-nums). L76 softens "Cần xác nhận
 * trong hôm nay" (a fake SLA) to "Đang chờ admin xác nhận". */
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
      <div className="tabular-nums" style={{ fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', color: valueColor }}>
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>{subline}</div>
    </div>
  )
}

function SkeletonCard() {
  return <div style={{ flex: 1, minWidth: 0, height: 84, borderRadius: 16, background: 'var(--g3)', border: '1px solid var(--stroke)' }} />
}

export function OverviewStatCards({ orders }: OverviewStatCardsProps) {
  if (!orders) {
    return (
      <div style={{ display: 'flex', gap: 12 }}>
        {Array.from({ length: 4 }, (_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: 12 }}>
      <StatCard label="Đơn hôm nay" value={orders.today} subline={`${orders.confirmed_today} đã xác nhận · ${orders.pending_today} chờ`} />
      <StatCard
        label="Doanh thu hôm nay"
        value={<Money value={Number(orders.revenue_today)} />}
        subline="Đã về tài khoản VNPay"
      />
      <StatCard
        label="Chờ xử lý"
        value={orders.pending_count}
        subline="Đang chờ admin xác nhận"
        valueColor="var(--warn-ink)"
        rail="inset 3px 0 0 var(--warn)"
      />
      <StatCard
        label="Giữ chỗ sắp hết hạn"
        value={orders.expiring_holds_30m}
        subline="Hết hạn trong 30 phút tới"
        valueColor="var(--err)"
        rail="inset 3px 0 0 var(--err)"
      />
    </div>
  )
}
