/**
 * vnpay-return.ts — detects a bounce-back from VNPay's hosted payment page
 * (backend's VNPAY_RETURN_URL points here, e.g.
 * "https://app.example.com/?payment_return=1" — plan
 * 260818-vnpay-payment-and-email-confirmation). Mirrors
 * auth/oauth-redirect-error.ts's pattern exactly: read once on boot via
 * URLSearchParams, then strip the marker so a refresh doesn't re-trigger it.
 *
 * Deliberately carries no payment id or any other VNPay data in the URL —
 * that would be display-only anyway, never trusted for confirmation (see
 * booking-client.ts's doc comment on why the backend's IPN webhook is the
 * only real source of truth). The actual pending payment id comes from
 * roomHold.paymentId (use-room-hold.ts), persisted to sessionStorage right
 * before the redirect away — App.tsx reads that, not this URL, to know
 * WHICH payment to poll.
 */
export function consumeVnpayReturn(): boolean {
  const query = new URLSearchParams(window.location.search)
  if (query.get('payment_return') !== '1') return false
  query.delete('payment_return')
  const rest = query.toString()
  window.history.replaceState({}, '', window.location.pathname + (rest ? `?${rest}` : ''))
  return true
}

/** Read-only twin of consumeVnpayReturn() — same URL check, but never
 * strips the marker. Exists purely so App.tsx can know "are we returning
 * from VNPay" synchronously on the very FIRST render (a lazy useState
 * initializer, before any effect has run) to gate the processing-screen
 * splash that hides the session-bootstrap flash — the real, marker-
 * consuming call still happens exactly once, inside that effect, as
 * before. Safe to call any number of times before that: reading
 * URLSearchParams has no side effect of its own. */
export function isVnpayReturnPending(): boolean {
  return new URLSearchParams(window.location.search).get('payment_return') === '1'
}
