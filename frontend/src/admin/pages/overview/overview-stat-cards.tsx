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
 * background, 16px radius, 26px tabular-nums). The third tile drops the
 * plan's "Cần xác nhận trong hôm nay" (a fake SLA) and its "Đang chờ admin
 * xác nhận" replacement: `pending_count` is payments stuck in PENDING --
 * a guest who never finished paying, which no admin action clears. It
 * names the wait honestly and surfaces `pending_over_2h`, the subset
 * actually worth chasing, matching D1's tile. */
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
        gap: 8,
      }}
    >
      <div className="skeleton-bar" style={{ width: '50%', height: 9 }} />
      <div className="skeleton-bar" style={{ width: '35%', height: 22 }} />
      <div className="skeleton-bar" style={{ width: '65%', height: 8 }} />
    </div>
  )
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
        label="Chờ thanh toán"
        value={orders.pending_count}
        subline={`Chưa thanh toán · ${orders.pending_over_2h} đơn quá 2 giờ`}
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
