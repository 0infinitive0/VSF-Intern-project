/**
 * booking-error.ts — maps a booking-flow error message to the i18n key that
 * explains it in plain Vietnamese/English.
 *
 * booking-client.ts's request<T>() throws `new Error(detail)`, and `detail`
 * is whatever the backend's HTTPException carried (backend/src/api/
 * routes.py's _booking_http_error): the four known domain codes travel as
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
  if (message.includes('insufficient_room_availability')) return 'bookingErrRoomSoldOut'
  if (message.includes('booking_reservation_expired')) return 'bookingErrHoldExpired'
  if (message.includes('booking_not_confirmable')) return 'bookingErrNotConfirmable'
  if (message.includes('invalid_booking_request')) return 'bookingErrInvalidRequest'
  if (message.includes('guest_already_holding_elsewhere')) return 'bookingErrGuestHoldingElsewhere'
  if (message.includes('booking_not_found') || message.toLowerCase().includes('booking not found')) {
    return 'bookingErrNotFound'
  }
  return 'bookingErrGeneric'
}
