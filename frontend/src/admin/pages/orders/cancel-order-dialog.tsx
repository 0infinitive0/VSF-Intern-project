import { useEffect, useState } from 'react'
import { cancelOrder, type OrderDetailResponse } from '../../api/orders-client'
import { bookingErrorVi } from '../../lib/booking-error-vi'
import { cancellableRoomCount, orderHotelNames, sumRoomCounts } from '../../lib/order-room-counts'
import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import { Money } from '../../ui/money'
import { Select } from '../../ui/select'
import { Textarea } from '../../ui/textarea'

interface CancelOrderDialogProps {
  open: boolean
  order: OrderDetailResponse
  onClose: () => void
  /** Reports the outcome banner text + tone to the page, and asks it to
   * reload D2 -- same contract as ConfirmOrderDialog's `onDone`. */
  onDone: (message: string, tone: 'ok' | 'err') => void
}

// L18 (plan): no reasons table backs this -- hardcoded here, mirrored
// server-side only as an audit-log free-text value (backend doesn't
// enforce membership, so this list is this dialog's own source of truth).
const CANCEL_REASONS = ['Khách yêu cầu huỷ', 'Hết phòng', 'Thanh toán không hợp lệ', 'Đơn trùng', 'Lý do khác']

/** cancel-order-dialog.tsx — D3's "Hộp thoại Huỷ" (phase-06-order-actions.md).
 * L16: the HẬU QUẢ block never mentions email -- decision #11 (no
 * cancellation email at all), and email_service has no template for one. */
export function CancelOrderDialog({ open, order, onClose, onDone }: CancelOrderDialogProps) {
  const [reason, setReason] = useState(CANCEL_REASONS[0])
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Reset the form each time the dialog opens -- the parent keeps this
  // component mounted, so without this a note typed then abandoned would
  // still be sitting there the next time the admin opens the dialog.
  useEffect(() => {
    if (open) {
      setReason(CANCEL_REASONS[0])
      setNote('')
    }
  }, [open])

  if (!open) return null

  const roomCount = cancellableRoomCount(order)
  const canSubmit = reason.trim().length > 0 && !submitting

  async function handleCancel() {
    setSubmitting(true)
    const result = await cancelOrder(order.payment_id, { reason, note: note.trim() || null })
    setSubmitting(false)
    if (!result.ok) {
      onDone(bookingErrorVi(result.detail), 'err')
      return
    }
    // `cancelled`/`failed` counts bookings, not rooms -- see confirm dialog
    // for the same fix.
    const okIds = result.data.results.filter((r) => r.ok).map((r) => r.booking_id)
    const failed = result.data.results.filter((r) => !r.ok)
    const failedIds = failed.map((r) => r.booking_id)
    if (failed.length > 0) {
      onDone(
        `Đã huỷ ${sumRoomCounts(order, okIds)} phòng, ${sumRoomCounts(order, failedIds)} phòng lỗi: ${failed.map((r) => bookingErrorVi(r.error)).join(' ')}`,
        'err',
      )
    } else {
      onDone(`Đã huỷ ${sumRoomCounts(order, okIds)} phòng của đơn ${order.order_code}.`, 'ok')
    }
    onClose()
  }

  return (
    <Modal open={open} onClose={submitting ? () => {} : onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 22,
              height: 22,
              borderRadius: 999,
              background: 'var(--err-soft)',
              color: 'var(--err)',
              fontWeight: 700,
              fontSize: 13,
            }}
          >
            !
          </span>
          <div style={{ fontSize: 16, fontWeight: 700 }}>Huỷ đơn {order.order_code}?</div>
        </div>
        <div style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.5 }}>
          Hành động này <strong>không thể hoàn tác</strong>.
        </div>

        <Select label="Lý do huỷ (bắt buộc)" value={reason} onChange={(e) => setReason(e.target.value)} disabled={submitting}>
          {CANCEL_REASONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </Select>

        <Textarea
          label="Ghi chú thêm (tuỳ chọn)"
          placeholder="Ghi chú thêm (tuỳ chọn)…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={submitting}
        />

        <div>
          <div style={{ fontSize: 10.5, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--t4)', fontWeight: 700, marginBottom: 8 }}>
            Hậu quả
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--t2)', lineHeight: 1.6 }}>
            <li>
              {roomCount} phòng tại {orderHotelNames(order)} được trả lại kho phòng ngay lập tức
            </li>
            <li>
              Khoản đã thu <Money value={Number(order.totals.total)} /> phải hoàn thủ công qua VNPay
            </li>
          </ul>
        </div>

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Giữ nguyên đơn
          </Button>
          <Button variant="danger" onClick={handleCancel} disabled={!canSubmit}>
            {submitting ? 'Đang xử lý…' : `Huỷ ${roomCount} phòng`}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
