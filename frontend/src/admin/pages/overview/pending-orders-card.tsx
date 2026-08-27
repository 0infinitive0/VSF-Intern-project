import type { OverviewPendingOrder } from '../../api/overview-client'
import { EmptyState } from '../../ui/empty-state'
import { Money } from '../../ui/money'

interface PendingOrdersCardProps {
  items: OverviewPendingOrder[] | null
  navigate: (to: string) => void
}

function SkeletonRows() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div className="skeleton-bar" style={{ width: 64, height: 10 }} />
          <div className="skeleton-bar" style={{ width: 110, height: 10 }} />
          <div className="skeleton-bar" style={{ width: 56, height: 10, marginLeft: 'auto' }} />
          <div className="skeleton-bar" style={{ width: 84, height: 18, borderRadius: 999 }} />
        </div>
      ))}
    </div>
  )
}

/** pending-orders-card.tsx — A3's "Chờ thanh toán" block: orders whose VNPay
 * payment never came back, longest-waiting first. Backend already ordered and
 * capped them (`_fetch_pending_orders`); this only renders.
 *
 * Every row is the same kind of wait, so there is no per-row severity to
 * encode — one warn rail on all of them, unlike the block this replaced,
 * which mixed four different issue types under one heading. */
export function PendingOrdersCard({ items, navigate }: PendingOrdersCardProps) {
  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Chờ thanh toán</div>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => navigate('/admin/orders')}>
          Xem tất cả đơn
        </button>
      </div>

      {items === null && <SkeletonRows />}

      {items !== null && items.length === 0 && (
        <EmptyState title="✓ Không có đơn nào chờ thanh toán." description="Mọi đơn đều đã thanh toán xong." />
      )}

      {items !== null && items.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 480 }}>
            <thead>
              <tr>
                <th>MÃ ĐƠN</th>
                <th>KHÁCH</th>
                <th data-align="right">TỔNG TIỀN</th>
                <th>CHỜ</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.payment_id}
                  onClick={() => navigate(`/admin/orders/${item.payment_id}`)}
                  style={{ cursor: 'pointer', boxShadow: 'inset 3px 0 0 var(--warn)' }}
                >
                  <td>{item.order_code}</td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{item.guest_name ?? '—'}</div>
                    {item.guest_email && <div style={{ fontSize: 11.5, color: 'var(--t3)' }}>{item.guest_email}</div>}
                  </td>
                  <td data-align="right">
                    <Money value={Number(item.amount)} />
                  </td>
                  <td>
                    <span className="chip chip--warn" style={{ fontSize: 11.5 }}>
                      {item.waiting_label}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
