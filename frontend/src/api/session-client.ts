/**
 * session-client.ts — history rail data calls: list / restore / delete.
 * Kept separate from chat-client.ts (which owns the live chat contract) since
 * this hits Phase 4 endpoints that don't exist on every backend yet.
 *
 * A 404 from GET /chat/sessions means "this backend hasn't shipped session
 * persistence" (Phase 4), not an error — callers get an empty list, same as
 * a genuinely empty history. Network failures degrade the same way so the
 * sidebar never shows an error state for an optional feature.
 */
import type { SessionRestore, SessionSummary } from '../types'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

export async function listSessions(): Promise<SessionSummary[]> {
  try {
    const res = await fetch(`${BASE}/chat/sessions`)
    if (!res.ok) return []
    const data = (await res.json()) as { sessions: SessionSummary[] }
    return data.sessions || []
  } catch {
    return []
  }
}

export async function restoreSession(sessionId: string): Promise<SessionRestore | null> {
  try {
    const res = await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}/restore`)
    if (!res.ok) return null
    return (await res.json()) as SessionRestore
  } catch {
    return null
  }
}

/** Best-effort: the row is removed from the UI locally regardless of outcome. */
export async function deleteSession(sessionId: string): Promise<void> {
  try {
    await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  } catch {
    // best-effort
  }
}
