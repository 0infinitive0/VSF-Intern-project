/**
 * guest-ref.ts — the anonymous `temporary_user_ref` the booking API uses to
 * own a reservation (backend/src/models/schemas.py's BookingReservationRequest
 * / BookingOwnershipRequest — a free-form 1..128 char string, no Supabase
 * auth user required). Generated once per browser and persisted in
 * localStorage so the SAME visitor can confirm/cancel a hold they created
 * earlier — in another tab, or after a refresh mid-checkout. A brand-new
 * visitor (or a private window) simply gets a fresh ref and, by design, can
 * never touch someone else's booking with it.
 *
 * Deliberately NOT tied to Supabase auth.user.id: this ref exists precisely
 * for the guest-booking path the backend supports with no sign-in required
 * (see docs/chat_api_contract.md's Authentication section, noted in
 * place-client.ts) — reusing the Supabase id here would make a signed-out
 * guest's earlier hold un-confirmable the moment they sign in.
 */
const STORAGE_KEY = 'vota_temporary_user_ref'

export function getGuestRef(): string {
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const fresh = crypto.randomUUID()
    window.localStorage.setItem(STORAGE_KEY, fresh)
    return fresh
  } catch {
    // Storage unavailable (private-mode edge cases) — fall back to a
    // per-call ref rather than throwing. The caller just won't be able to
    // confirm/cancel this particular booking after a reload, which is a
    // strictly smaller problem than the hold never starting at all.
    return crypto.randomUUID()
  }
}
