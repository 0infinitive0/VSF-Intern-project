/**
 * booking-error.ts — maps a booking-flow error message to the i18n key that
 * explains it in plain Vietnamese/English.
 *
 * booking-client.ts's request<T>() throws `new Error(detail)`, and `detail`
 * is whatever the backend's HTTPException carried (backend/src/api/
 * routes.py's _booking_http_error): the known domain codes travel as
 * their raw snake_case string (e.g. "insufficient_room_availability" — this
 * IS the whole message, not embedded in a sentence), while "not found" and
 * the generic failure path are already short English sentences. None of
 * that is fit to show a Vietnamese-speaking guest directly — this function
 * is the one place that decides which explanation they see, returning an
 * i18n KEY (not translated text) so callers do their own `t(...)`, same as
 * match-reasons.tsx's `code -> matchReason.<code>` pattern.
 */
export function bookingErrorKey(message: string | null | undefined): string {
  if (!message) return 'bookingErrGeneric'
  // Not backend error codes — sentinels booking-modal.tsx sets itself once
  // App.tsx's VNPay-return poll (GET /payments/{id}) settles on FAILED/
  // CANCELLED, or gives up after ~20s with the payment still PENDING
  // (vnpay_still_pending — the IPN webhook hasn't reached the backend
  // yet), so the guest sees why they're back on the Payment step instead
  // of silently landing there with no explanation.
  if (message.includes('vnpay_cancelled')) return 'bookingErrVnpayCancelled'
  if (message.includes('vnpay_still_pending')) return 'bookingErrVnpayPending'
  if (message.includes('vnpay_payment_failed')) return 'bookingErrVnpayFailed'
  if (message.includes('insufficient_room_availability')) return 'bookingErrRoomSoldOut'
  if (message.includes('booking_reservation_expired')) return 'bookingErrHoldExpired'
  if (message.includes('booking_not_confirmable')) return 'bookingErrNotConfirmable'
  if (message.includes('invalid_booking_request')) return 'bookingErrInvalidRequest'
  if (message.includes('guest_already_holding_elsewhere')) return 'bookingErrGuestHoldingElsewhere'
  if (message.includes('itinerary_not_persisted')) return 'bookingErrItineraryNotSaved'
  if (message.includes('booking_not_found') || message.toLowerCase().includes('booking not found')) {
    return 'bookingErrNotFound'
  }
  return 'bookingErrGeneric'
}
