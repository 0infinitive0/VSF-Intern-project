/**
 * client.ts — the one fetch wrapper every src/admin/api/*.ts call goes
 * through, same shape as the chat app's api/*-client.ts files. Reuses
 * ../../api/auth-headers (the only chat-app file this portal imports from)
 * so both bundles read the bearer token from the same Supabase SDK session.
 */
import { authHeaders } from '../../api/auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1/admin'

// The backend's Supabase client is a single process-wide HTTP/2 connection
// (get_supabase_client(), @lru_cache'd) shared across FastAPI's threadpool
// workers -- two admin requests landing at the same instant (e.g. the
// sidebar's badge fetch racing a page's own list fetch, both firing on
// mount) can corrupt that shared connection and 500 one or both (repro'd
// live: httpx.RemoteProtocolError / a raw Cloudflare 400 postgrest can't
// parse). Serializing every call through this one queue -- so no two
// requests are ever in flight to the backend at once -- is the fix that
// stays on the frontend instead of touching that shared backend hub.
let requestQueue: Promise<unknown> = Promise.resolve()

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const result = requestQueue.then(task, task)
  requestQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}

export type AdminApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; detail: string }

/** FastAPI's 422 body is `{"detail": [{loc, msg, type}, ...]}`, not a plain
 * string -- without this, every server-side validation failure rendered as
 * a content-free "Lỗi máy chủ (422)." with no indication of which field. */
function detailFromValidationErrors(body: unknown): string | null {
  const errors = (body as { detail?: unknown } | null)?.detail
  if (!Array.isArray(errors) || errors.length === 0) return null
  const messages = errors.map((err) => {
    const loc = Array.isArray(err?.loc) ? err.loc.filter((p: unknown) => p !== 'body').join('.') : null
    const msg = typeof err?.msg === 'string' ? err.msg : 'Giá trị không hợp lệ'
    return loc ? `${loc}: ${msg}` : msg
  })
  return messages.join('; ')
}

export async function adminFetch<T>(path: string, init?: RequestInit): Promise<AdminApiResult<T>> {
  let res: Response
  try {
    const headers = { ...(await authHeaders()), ...init?.headers }
    res = await enqueue(() => fetch(`${BASE}${path}`, { ...init, headers }))
  } catch {
    return { ok: false, status: 0, detail: 'Không thể kết nối tới máy chủ.' }
  }
  if (!res.ok) {
    let detail = `Lỗi máy chủ (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else {
        const fieldErrors = detailFromValidationErrors(body)
        if (fieldErrors) detail = fieldErrors
      }
    } catch {
      // Response had no JSON body -- keep the generic detail above.
    }
    return { ok: false, status: res.status, detail }
  }
  return { ok: true, data: (await res.json()) as T }
}
