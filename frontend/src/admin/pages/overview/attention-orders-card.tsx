import type { OverviewAttentionOrder } from '../../api/overview-client'
import { EmptyState } from '../../ui/empty-state'
import { Money } from '../../ui/money'

interface AttentionOrdersCardProps {
  items: OverviewAttentionOrder[] | null
  navigate: (to: string) => void
}

const SEVERITY_CHIP_CLASS: Record<string, string> = { err: 'chip--err', warn: 'chip--warn', mute: 'chip--closed' }
// D1's rail treatment (phase-04-orders-list.md) reused verbatim for the two
// urgent tiers -- "mute" (payment_failed) gets no rail, it's informational.
const SEVERITY_RAIL: Record<string, string | undefined> = {
  err: 'inset 3px 0 0 var(--err)',
  warn: 'inset 3px 0 0 var(--warn)',
  mute: undefined,
}

/** attention-orders-card.tsx — A3's "Đơn cần xử lý ngay" block (phase-17-
 * overview-kpi.md). Ranking/≤5 already happened server-side
 * (overview.py's `_fetch_attention_orders`); this only renders. Positive
 * empty state, not the default "Chưa có dữ liệu" -- an admin with nothing
 * to do should feel that as good news, not a broken screen. */
export function AttentionOrdersCard({ items, navigate }: AttentionOrdersCardProps) {
  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Đơn cần xử lý ngay</div>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => navigate('/admin/orders')}>
          Xem tất cả đơn
        </button>
      </div>

      {items === null && <div style={{ height: 120, opacity: 0.4 }} />}

      {items !== null && items.length === 0 && (
        <EmptyState title="✓ Không có đơn nào cần xử lý ngay." description="Mọi đơn hôm nay đều đã ổn." />
      )}

      {items !== null && items.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 480 }}>
            <thead>
              <tr>
                <th>MÃ ĐƠN</th>
                <th>KHÁCH</th>
                <th data-align="right">TỔNG TIỀN</th>
                <th>VẤN ĐỀ</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.payment_id}
                  onClick={() => navigate(`/admin/orders/${item.payment_id}`)}
                  style={{ cursor: 'pointer', boxShadow: SEVERITY_RAIL[item.severity] }}
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
                    <span className={`chip ${SEVERITY_CHIP_CLASS[item.severity] ?? 'chip--closed'}`} style={{ fontSize: 11.5 }}>
                      {item.issue_label}
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
