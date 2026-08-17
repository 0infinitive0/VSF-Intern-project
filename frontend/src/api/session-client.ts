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
import type { SessionRestore, SessionSummary } from '../types'
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
