/**
 * trip-client.ts — wraps the finalize-itinerary API (backend/src/api/
 * routes.py's POST /chat/{session_id}/finalize — plan
 * 260819-finalize-itinerary). Mirrors payment-client.ts/booking-client.ts's
 * request<T>() error handling: a failed finalize call is something the
 * caller must surface, never something that silently degrades — there is
 * deliberately no shared fetch wrapper in this codebase, each client
 * redeclares its own.
 */
import type { FinalizeTripResult } from '../types'
import { authHeaders } from './auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
    }
  }

  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? (data as { detail?: unknown }).detail
        : undefined
    throw new Error(typeof detail === 'string' ? detail : detail != null ? JSON.stringify(detail) : text)
  }

  return data as T
}

/** Locks the session's itinerary and saves it as a reusable, embedded
 * template. Throws (never returns a "failed" shape) on a 409 — no trip
 * plan yet, no confirmed booking, or already finalized — so callers
 * (finalize-action.tsx) surface the backend's own detail message rather
 * than guessing which precondition failed. */
export async function finalizeTrip(sessionId: string): Promise<FinalizeTripResult> {
  return request('POST', `/chat/${encodeURIComponent(sessionId)}/finalize`)
}
