/**
 * chat-client.ts — owns all fetch calls, JSON parsing and error normalisation.
 * No component calls fetch directly.
 *
 * Base URL: /api/v1 in dev (proxied by Vite to localhost:8000).
 * VITE_API_BASE allows pointing at a remote backend.
 */

import type { PlannerChatResponse, TripPlan } from '../types'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(BASE + path, opts)

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

/**
 * Fetch the current trip plan for a session.
 * Throws on 404.
 */
export async function getPlan(sessionId: string): Promise<{ trip_plan: TripPlan | null }> {
  return request('GET', `/chat/${encodeURIComponent(sessionId)}/plan`)
}
