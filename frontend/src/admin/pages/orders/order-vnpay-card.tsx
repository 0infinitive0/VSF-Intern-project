import { DateText } from '../../ui/date-text'
import { Money } from '../../ui/money'
import { Banner } from '../../ui/banner'
import type { OrderDetailResponse } from '../../api/orders-client'

/** order-vnpay-card.tsx — D2's "Thanh toán VNPay" block (phase-05-order-
 * detail.md). L10: no "Ngân hàng" cell — `payments` only ever stores
 * `vnp_transaction_no`/`vnp_response_code`, never `vnp_BankCode`/
 * `vnp_CardType` (routes.py's IPN handler doesn't persist them). L13: the
 * attention banner states elapsed time, not a deadline the system never
 * promised.
 *
 * Gated on `payment_status`, not `vnpay.transaction_no`: the IPN handler
 * can persist `vnp_TransactionNo` as `""` (routes.py's
 * `params.get("vnp_TransactionNo", "")`), and `needs_attention` exists
 * specifically to flag that kind of abnormal IPN interaction — hiding the
 * whole card (and the banner inside it) on a falsy transaction number would
 * silence the one signal this screen exists to surface. */
export function OrderVnpayCard({ order }: { order: OrderDetailResponse }) {
  const { vnpay } = order
  if (order.payment_status !== 'PAID') return null
  const success = vnpay.response_code === '00'

  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <div style={{ fontSize: 13.5, fontWeight: 700 }}>Thanh toán VNPay</div>
        <span className={`chip chip--${success ? 'ok' : 'closed'}`}>{success ? '✓ Thành công' : '⚠ Cần kiểm tra'}</span>
      </div>
      <div className="kv-grid">
        <div>
          <div className="kv-grid__label">Mã giao dịch</div>
          <div className="kv-grid__value">{vnpay.transaction_no || '—'}</div>
        </div>
        <div>
          <div className="kv-grid__label">Số tiền</div>
          <div className="kv-grid__value">
            <Money value={Number(vnpay.amount)} />
          </div>
        </div>
        {vnpay.paid_at && (
          <div>
            <div className="kv-grid__label">Thời điểm</div>
            <div className="kv-grid__value">
              <DateText value={vnpay.paid_at} withTime />
            </div>
          </div>
        )}
      </div>

      {order.needs_attention && (
        <div style={{ marginTop: 14 }}>
          <Banner tone="warn">
            Tiền đã về nhưng đơn chưa được xác nhận — đã chờ {order.attention_hours} giờ.
          </Banner>
        </div>
      )}
    </div>
  )
}
