/**
 * session-client.ts — history rail data calls: list / restore / delete.
 * Kept separate from chat-client.ts (which owns the live chat contract) since
 * this hits Phase 4 endpoints that don't exist on every backend yet.
 *
 * A 404 from GET /chat/sessions means "this backend hasn't shipped session
 * persistence" (Phase 4), not an error — callers get an empty list, same as
 * a genuinely empty history. Network failures degrade the same way so the
 * sidebar never shows an error state for an optional feature. A 401 means
 * the caller's token is missing/invalid (plan
 * 260814-supabase-auth-and-per-user-history) — also degrades to an empty
 * list here (this endpoint's contract, unlike the chat endpoints, never
 * throws), but is reported to the session-expired bus so the rest of the
 * app still reacts.
 */
import type { BookingReceipt, SessionRestore, SessionSummary } from '../types'
import { authHeaders } from './auth-headers'
import { reportSessionExpired } from '../auth/session-expired-bus'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

export async function listSessions(): Promise<SessionSummary[]> {
  try {
    const res = await fetch(`${BASE}/chat/sessions`, { headers: await authHeaders() })
    if (res.status === 401) reportSessionExpired()
    if (!res.ok) return []
    const data = await res.json()
    if (Array.isArray(data)) return data as SessionSummary[]
    return (data?.sessions as SessionSummary[]) ?? []
  } catch {
    return []
  }
}

export async function restoreSession(sessionId: string): Promise<SessionRestore | null> {
  try {
    const res = await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}/restore`, {
      headers: await authHeaders(),
    })
    if (res.status === 401) reportSessionExpired()
    if (!res.ok) return null
    return (await res.json()) as SessionRestore
  } catch {
    return null
  }
}

/** "Reopen a past session's booking" (plan 260818-vnpay-payment-and-email-
 * confirmation's addendum 4, GET /chat/{session_id}/booking-receipt) —
 * deliberately independent of roomHold, which only ever reflects whichever
 * session most recently held/paid (use-room-hold.ts's module doc comment).
 * null covers both "no confirmed booking for this session" (404, the
 * common/expected case for a draft or still-holding session) and any
 * network/auth failure — booking-receipt-modal.tsx shows the same
 * "couldn't load" state either way, matching restoreSession's posture
 * above. */
export async function getBookingReceipt(sessionId: string): Promise<BookingReceipt | null> {
  try {
    const res = await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}/booking-receipt`, {
      headers: await authHeaders(),
    })
    if (res.status === 401) reportSessionExpired()
    if (!res.ok) return null
    return (await res.json()) as BookingReceipt
  } catch {
    return null
  }
}

/** Best-effort: the row is removed from the UI locally regardless of outcome. */
export async function deleteSession(sessionId: string): Promise<void> {
  try {
    await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
  } catch {
    // best-effort
  }
}
