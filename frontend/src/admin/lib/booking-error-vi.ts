/**
 * booking-error-vi.ts — translates the RPC error codes booking_service._call
 * (backend) raises into a Vietnamese sentence for D3's per-booking error
 * list (phase-06-order-actions.md).
 *
 * Not a reuse of ../../../lib/booking-error.ts: that file returns an i18n
 * KEY for the guest-facing chat app to look up in its own translation
 * table, not translated text — the two are fit for different call sites,
 * so this is its own small table rather than a shared one.
 */
const BOOKING_ERROR_VI: Record<string, string> = {
  booking_not_confirmable: 'Phòng này không ở trạng thái xác nhận được (có thể đã huỷ hoặc hết hạn giữ chỗ).',
  // Not in the plan's table (that only covers confirm) -- this dialog's own
  // 409 all-fail code for cancel, parallel to booking_not_confirmable.
  booking_not_cancellable: 'Không còn phòng nào trong đơn có thể huỷ (đã huỷ hoặc hết hạn từ trước).',
  booking_reservation_expired: 'Lượt giữ chỗ đã hết hạn, phòng đã được trả về kho.',
  booking_not_found: 'Không tìm thấy lượt đặt phòng này.',
  insufficient_room_availability: 'Không còn đủ phòng trống cho khoảng ngày này.',
  booking_operation_failed: 'Thao tác không thực hiện được. Thử lại hoặc kiểm tra log máy chủ.',
}

/** Translates a known snake_case RPC error code. `code` isn't always one of
 * those -- it's also used on the top-level `result.detail` from adminFetch,
 * which can be a 422 field-error sentence, a network-failure message, or
 * "order_not_found", none of which this table owns -- so an unrecognized
 * value passes through unchanged rather than collapsing to a generic
 * message that would bury the actual detail. */
export function bookingErrorVi(code: string | null | undefined): string {
  if (!code) return BOOKING_ERROR_VI.booking_operation_failed
  return BOOKING_ERROR_VI[code] ?? code
}
