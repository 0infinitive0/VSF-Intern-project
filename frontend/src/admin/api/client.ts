/**
 * client.ts — the one fetch wrapper every src/admin/api/*.ts call goes
 * through, same shape as the chat app's api/*-client.ts files. Reuses
 * ../../api/auth-headers (the only chat-app file this portal imports from)
 * so both bundles read the bearer token from the same Supabase SDK session.
 */
import { authHeaders } from '../../api/auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1/admin'

export type AdminApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; detail: string }

export async function adminFetch<T>(path: string, init?: RequestInit): Promise<AdminApiResult<T>> {
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { ...(await authHeaders()), ...init?.headers },
    })
  } catch {
    return { ok: false, status: 0, detail: 'Không thể kết nối tới máy chủ.' }
  }
  if (!res.ok) {
    let detail = `Lỗi máy chủ (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Response had no JSON body -- keep the generic detail above.
    }
    return { ok: false, status: res.status, detail }
  }
  return { ok: true, data: (await res.json()) as T }
}
