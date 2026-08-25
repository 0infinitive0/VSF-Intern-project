import type { OrderDetailResponse } from '../../api/orders-client'

/** order-guest-card.tsx — D2's "Thông tin khách" block (phase-05-order-
 * detail.md): 4 cells, `order_count` from the backend's L11 count (guest
 * email when present, else the anonymous temporary_user_ref). */
export function OrderGuestCard({ guest }: { guest: OrderDetailResponse['guest'] }) {
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ fontSize: 13.5, fontWeight: 700, marginBottom: 14 }}>Thông tin khách</div>
      <div className="kv-grid">
        <div>
          <div className="kv-grid__label">Họ tên</div>
          <div className="kv-grid__value">{guest.name || '—'}</div>
        </div>
        <div>
          <div className="kv-grid__label">Email</div>
          <div className="kv-grid__value">{guest.email || '—'}</div>
        </div>
        <div>
          <div className="kv-grid__label">Điện thoại</div>
          <div className="kv-grid__value">{guest.phone || '—'}</div>
        </div>
        <div>
          <div className="kv-grid__label">Số đơn đã đặt</div>
          <div className="kv-grid__value">{guest.order_count}</div>
        </div>
      </div>
    </div>
  )
}
