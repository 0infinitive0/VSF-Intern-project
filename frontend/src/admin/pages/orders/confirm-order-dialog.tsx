import { useState } from 'react'
import { confirmOrder, type OrderDetailResponse } from '../../api/orders-client'
import { bookingErrorVi } from '../../lib/booking-error-vi'
import { confirmableRoomCount, orderHotelNames, sumRoomCounts } from '../../lib/order-room-counts'
import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import { Money } from '../../ui/money'

interface ConfirmOrderDialogProps {
  open: boolean
  order: OrderDetailResponse
  onClose: () => void
  /** Reports the outcome banner text + tone to the page, and asks it to
   * reload D2 -- this dialog never renders its own result banner (the
   * checklist's "Banner kết quả (bộ Z)" lives on the page, after the
   * dialog has already closed). */
  onDone: (message: string, tone: 'ok' | 'err') => void
}

/** confirm-order-dialog.tsx — D3's "Hộp thoại Xác nhận" (phase-06-order-
 * actions.md). L15: copy keeps "khách nhận email xác nhận" but drops
 * "khách sạn nhận thông báo giữ phòng" -- no such notification flow exists. */
export function ConfirmOrderDialog({ open, order, onClose, onDone }: ConfirmOrderDialogProps) {
  const [submitting, setSubmitting] = useState(false)
  if (!open) return null

  const roomCount = confirmableRoomCount(order)

  async function handleConfirm() {
    setSubmitting(true)
    const result = await confirmOrder(order.payment_id)
    setSubmitting(false)
    if (!result.ok) {
      onDone(bookingErrorVi(result.detail), 'err')
      return
    }
    // `confirmed`/`failed` on the response count bookings, not rooms -- the
    // banner talks in rooms like the button label does, so re-derive from
    // `results[]` via each booking's own room_count instead of echoing the
    // booking counts back.
    const okIds = result.data.results.filter((r) => r.ok).map((r) => r.booking_id)
    const failed = result.data.results.filter((r) => !r.ok)
    const failedIds = failed.map((r) => r.booking_id)
    if (failed.length > 0) {
      onDone(
        `Đã xác nhận ${sumRoomCounts(order, okIds)} phòng, ${sumRoomCounts(order, failedIds)} phòng lỗi: ${failed.map((r) => bookingErrorVi(r.error)).join(' ')}`,
        'err',
      )
    } else {
      onDone(`Đã xác nhận đơn ${order.order_code}${result.data.email_sent ? ' và gửi email cho khách.' : '.'}`, 'ok')
    }
    onClose()
  }

  return (
    <Modal open={open} onClose={submitting ? () => {} : onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ fontSize: 16, fontWeight: 700 }}>Xác nhận đơn {order.order_code}?</div>
        <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.5 }}>
          Đơn sẽ chuyển sang <strong>Đã xác nhận</strong>. Khách nhận email xác nhận kèm mã đặt phòng.
        </div>

        <div className="kv-grid">
          <div>
            <div className="kv-grid__label">Khách</div>
            <div className="kv-grid__value">{order.guest.name || '—'}</div>
          </div>
          <div>
            <div className="kv-grid__label">Phòng</div>
            <div className="kv-grid__value">
              {roomCount} phòng · {orderHotelNames(order)}
            </div>
          </div>
          <div>
            <div className="kv-grid__label">Tổng tiền đã thu</div>
            <div className="kv-grid__value">
              <Money value={Number(order.totals.total)} />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Để sau
          </Button>
          <Button variant="primary" onClick={handleConfirm} disabled={submitting}>
            {submitting ? 'Đang xử lý…' : `Xác nhận ${roomCount} phòng`}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
