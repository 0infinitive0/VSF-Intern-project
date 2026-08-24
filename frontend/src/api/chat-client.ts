/**
 * chat-client.ts — owns all fetch calls, JSON parsing and error normalisation.
 * No component calls fetch directly.
 *
 * Base URL: /api/v1 in dev (proxied by Vite to localhost:8000).
 * VITE_API_BASE allows pointing at a remote backend.
 */

import type { PlannerChatResponse, TripPlan } from '../types'
import { authHeaders } from './auth-headers'
import { reportSessionExpired } from '../auth/session-expired-bus'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(BASE + path, opts)
  if (res.status === 401) reportSessionExpired()

  if (res.status === 204) return null as T

  const text = await res.text()
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
  }

  if (!res.ok) {
    const detail =
      (data && typeof data === 'object' && 'detail' in data
        ? (data as { detail?: string }).detail
        : undefined) || text
    throw new Error(detail)
  }

  return data as T
}

export interface CreateSessionResponse {
  session_id: string
  created_at: string
}

/**
 * Create a new chat session on the server.
 */
export async function createSession(): Promise<CreateSessionResponse> {
  return request('POST', '/chat/session')
}

/**
 * Send a chat message.
 * `language` is the UI language of the current turn ("vi" | "en"); the backend
 * uses it to localize the reply and LLM prompt. Wireless value default here to
 * "vi" so existing callers sending only (sessionId, message) keep working.
 */
export async function sendMessage(
  sessionId: string,
  message: string,
  language: string = 'vi',
): Promise<PlannerChatResponse> {
  return request('POST', '/planner_chat', {
    session_id: sessionId,
    message,
    language,
  })
}

/** Select a hotel through the dedicated UI endpoint, never through free chat. */
export async function selectHotel(
  sessionId: string,
  hotelId: string | number,
  selectionMessage: string,
): Promise<PlannerChatResponse> {
  return request('POST', '/hotels/select', {
    session_id: sessionId,
    hotel_id: hotelId,
    selection_message: selectionMessage,
  })
}

/**
 * Fetch the current trip plan for a session.
 * Throws on 404.
 */
export async function getPlan(sessionId: string): Promise<{ trip_plan: TripPlan | null }> {
  return request('GET', `/chat/${encodeURIComponent(sessionId)}/plan`)
}

export type SessionPing = 'alive' | 'gone' | 'unauthorized' | 'unknown'

/**
 * Ping a stored session to find out whether the server still accepts it.
 *
 * Deliberately does NOT throw and deliberately is not `getPlan`: bootstrap has
 * to tell three failure modes apart, and an exception collapses them into one.
 * 404 means the session is genuinely gone (start fresh); 401 means the *token*
 * is stale, which AuthProvider refreshes on its own — so it must never be read
 * as "session gone" or a live conversation gets thrown away for a reason that
 * fixes itself seconds later. Anything else (network down, 5xx) is no evidence
 * either way, so the caller keeps what it has.
 *
 * GET /chat/{id}/plan doubles as the ping — it is already ownership-checked
 * (routes.py `_owned_session_or_404`), so no dedicated endpoint is needed.
 */
export async function pingSession(sessionId: string): Promise<SessionPing> {
  try {
    const res = await fetch(`${BASE}/chat/${encodeURIComponent(sessionId)}/plan`, {
      headers: { ...(await authHeaders()) },
    })
    if (res.status === 401) {
      reportSessionExpired()
      return 'unauthorized'
    }
    if (res.status === 404) return 'gone'
    return res.ok ? 'alive' : 'unknown'
  } catch {
    return 'unknown'
  }
}

/**
 * Rebuild the hotel list for an already-built trip — backs the "đổi khách
 * sạn" step-nav action (step-navigator.tsx). Deliberately NOT `sendMessage`:
 * it carries no user text, so there is nothing for the extractor to read.
 *
 * The backend re-enters its graph directly at the hotel-search step
 * (`routes.py`'s `change_hotel` -> `_rerun_hotel_search`), skipping the
 * extraction/validation pipeline entirely — so this really is LLM-free, which
 * this comment previously claimed while the endpoint was in fact running a
 * full chat turn on a hardcoded Vietnamese string. It still returns a normal
 * PlannerChatResponse, and it can still come back paused if the search needs
 * to ask which landmark to search around.
 */
export async function changeHotel(sessionId: string): Promise<PlannerChatResponse> {
  return request('POST', '/hotels/change', { session_id: sessionId })
}

/** Append the next retained hotel batch without sending a chat message or LLM turn. */
export async function expandHotelOptions(sessionId: string): Promise<PlannerChatResponse> {
  return request('POST', '/hotels/expand', { session_id: sessionId })
}

export async function toggleHotelPreference(
  sessionId: string, amenityId: string, active: boolean,
): Promise<PlannerChatResponse> {
  return request('POST', '/hotels/preferences', { session_id: sessionId, amenity_id: amenityId, active })
}
