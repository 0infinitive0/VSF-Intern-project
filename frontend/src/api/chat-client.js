/**
 * chat-client.js — owns all fetch calls, JSON parsing and error normalisation.
 * No component calls fetch directly.
 *
 * Base URL: /api/v1 in dev (proxied by Vite to localhost:8000).
 * VITE_API_BASE allows pointing at a remote backend.
 */

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(BASE + path, opts)

  if (res.status === 204) return null

  const text = await res.text()
  let data
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
  }

  if (!res.ok) {
    const detail = data?.detail || text
    throw new Error(detail)
  }

  return data
}

/**
 * Create a new chat session on the server.
 * Returns { session_id, created_at }.
 */
export async function createSession() {
  return request('POST', '/chat/session')
}

/**
 * Send a chat message.
 * Returns PlannerChatResponse: { session_id, reply, suggestions, stage,
 *   hotel_options, trip_plan, intake }
 */
export async function sendMessage(sessionId, message) {
  return request('POST', '/planner_chat', { session_id: sessionId, message })
}

/**
 * Fetch the current trip plan for a session.
 * Returns { trip_plan } or throws on 404.
 */
export async function getPlan(sessionId) {
  return request('GET', `/chat/${encodeURIComponent(sessionId)}/plan`)
}

/**
 * Delete / reset a session on the server.
 * Returns null on 204.
 */
export async function resetSession(sessionId) {
  return request('DELETE', `/chat/${encodeURIComponent(sessionId)}`)
}
