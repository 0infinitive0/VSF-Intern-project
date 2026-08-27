import type { OverviewOrders } from '../../api/overview-client'
import { DonutChart } from '../../ui/donut-chart'
import { EmptyState } from '../../ui/empty-state'

interface OrderStatusCardProps {
  orders: OverviewOrders | null
}

/** order-status-card.tsx — A3 hollow-pie split of today's orders. `today`
 * = payments opened today; `confirmed_today` are booked rooms, `cancelled_today`
 * are guest cancels at the VNPay gateway (not the expiry sweep), and the rest
 * is still waiting. The three sum to `today` (the wait bucket is derived, so
 * it can't drift). `null` renders the shared skeleton; an empty day gets a
 * positive empty state rather than a bare ring. */
export function OrderStatusCard({ orders }: OrderStatusCardProps) {
  const waiting = orders ? Math.max(0, orders.today - orders.confirmed_today - orders.cancelled_today) : 0

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 14, fontWeight: 700 }}>Trạng thái đơn hôm nay</div>

      {orders === null ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div className="skeleton-bar" style={{ width: 132, height: 132, borderRadius: 999, flexShrink: 0 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
            <div className="skeleton-bar" style={{ width: '70%', height: 10 }} />
            <div className="skeleton-bar" style={{ width: '55%', height: 10 }} />
          </div>
        </div>
      ) : orders.today === 0 ? (
        <EmptyState title="Chưa có đơn nào hôm nay." description="Biểu đồ sẽ hiện khi có đơn đầu tiên trong ngày." />
      ) : (
        <DonutChart
          segments={[
            { label: 'Đã xác nhận', value: orders.confirmed_today, color: 'var(--ok)' },
            { label: 'Chờ xác nhận', value: waiting, color: 'var(--warn)' },
            { label: 'Khách huỷ', value: orders.cancelled_today, color: 'var(--err)' },
          ]}
          centerLabel={orders.today}
          centerSub="đơn"
        />
      )}
    </div>
  )
}
