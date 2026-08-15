/**
 * place-client.ts — detail payloads for the two focus modes:
 *   GET /hotels/{id}      (Phase 3, hotel detail panel)
 *   GET /attractions/{id} (Phase 3, Phase 9's place detail panel)
 *
 * Same degrade contract as session-client.ts: these endpoints may not exist
 * on the backend yet, so a 404 or network failure returns null and the panel
 * shows its "no details" state — never an error screen. These two are
 * sessionless/unauthenticated in the backend contract (public catalog
 * lookups, see docs/chat_api_contract.md's Authentication section), but the
 * header is still attached for a caller that already has a token — cheap
 * and harmless, and keeps this file consistent with every other client here.
 */
import type { AttractionDetail, HotelDetail } from '../types'
import { authHeaders } from './auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

export async function getHotelDetail(hotelId: string): Promise<HotelDetail | null> {
  try {
    const res = await fetch(`${BASE}/hotels/${encodeURIComponent(hotelId)}`, { headers: await authHeaders() })
    if (!res.ok) return null
    return (await res.json()) as HotelDetail
  } catch {
    return null
  }
}

export async function getAttractionDetail(attractionId: string): Promise<AttractionDetail | null> {
  try {
    const res = await fetch(`${BASE}/attractions/${encodeURIComponent(attractionId)}`, {
      headers: await authHeaders(),
    })
    if (!res.ok) return null
    return (await res.json()) as AttractionDetail
  } catch {
    return null
  }
}
