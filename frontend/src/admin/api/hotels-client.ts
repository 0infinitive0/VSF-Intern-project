/**
 * hotels-client.ts — B1 (Danh sách khách sạn) API calls.
 *
 * CSV export can't go through `adminFetch` (client.ts): that helper always
 * parses the response as JSON. It reuses the same bearer-token header
 * instead, since a plain `<a href>` navigation to the CSV URL would not
 * carry the Authorization header at all.
 */
import { authHeaders } from '../../api/auth-headers'
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1/admin'

export type HotelRow = components['schemas']['HotelRow']
export type HotelListResponse = components['schemas']['HotelListResponse']
export type HotelActiveResponse = components['schemas']['HotelActiveResponse']
export type BulkActiveResponse = components['schemas']['BulkActiveResponse']
export type CreateHotelRequest = components['schemas']['CreateHotelRequest']
export type CreateHotelResponse = components['schemas']['CreateHotelResponse']
export type DestinationOption = components['schemas']['DestinationOption']
export type HotelDetailResponse = components['schemas']['HotelDetailResponse']
export type UpdateHotelRequest = components['schemas']['UpdateHotelRequest']
export type UpdateHotelResponse = components['schemas']['UpdateHotelResponse']
export type ReembedResponse = components['schemas']['ReembedResponse']
export type AmenityOption = components['schemas']['AmenityOption']
export type UploadImageResponse = components['schemas']['UploadImageResponse']

export type SourceFilter = 'all' | 'manual' | 'pipeline'
export type EmbeddingFilter = 'all' | 'embedded' | 'missing'

export interface HotelListParams {
  q?: string
  source?: SourceFilter
  isActive?: boolean
  embedding?: EmbeddingFilter
  page: number
  pageSize: number
}

function buildQuery(params: HotelListParams): URLSearchParams {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.source && params.source !== 'all') search.set('source', params.source)
  if (params.isActive !== undefined) search.set('is_active', String(params.isActive))
  if (params.embedding && params.embedding !== 'all') search.set('embedding', params.embedding)
  search.set('page', String(params.page))
  search.set('page_size', String(params.pageSize))
  return search
}

export function listHotels(params: HotelListParams): Promise<AdminApiResult<HotelListResponse>> {
  return adminFetch<HotelListResponse>(`/hotels?${buildQuery(params)}`)
}

export interface HotelBlockedBooking {
  booking_id: string
  check_in_date: string
  room_name: string
}

export type SetHotelActiveResult =
  | { ok: true; data: HotelActiveResponse }
  | { ok: false; detail: string; count?: number; bookings?: HotelBlockedBooking[] }

/** Not routed through `adminFetch`: the 409 body carries `count`/`bookings`
 * alongside `detail` (the blocked-bookings banner needs them), and
 * `adminFetch`'s AdminApiResult only ever keeps the `detail` string. */
export async function setHotelActive(hotelId: string, isActive: boolean): Promise<SetHotelActiveResult> {
  let res: Response
  try {
    res = await fetch(`${BASE}/hotels/${hotelId}/active`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
      body: JSON.stringify({ is_active: isActive }),
    })
  } catch {
    return { ok: false, detail: 'Không thể kết nối tới máy chủ.' }
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // No JSON body -- fall through to the generic detail below.
  }
  const record = (body ?? {}) as Record<string, unknown>
  if (!res.ok) {
    return {
      ok: false,
      detail: typeof record.detail === 'string' ? record.detail : `Lỗi máy chủ (${res.status}).`,
      count: typeof record.count === 'number' ? record.count : undefined,
      bookings: Array.isArray(record.bookings) ? (record.bookings as HotelBlockedBooking[]) : undefined,
    }
  }
  return { ok: true, data: body as HotelActiveResponse }
}

export function bulkSetHotelActive(hotelIds: string[], isActive: boolean): Promise<AdminApiResult<BulkActiveResponse>> {
  return adminFetch<BulkActiveResponse>('/hotels/bulk-active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hotel_ids: hotelIds, is_active: isActive }),
  })
}

export function createHotel(body: CreateHotelRequest): Promise<AdminApiResult<CreateHotelResponse>> {
  return adminFetch<CreateHotelResponse>('/hotels', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function listDestinations(): Promise<AdminApiResult<DestinationOption[]>> {
  return adminFetch<DestinationOption[]>('/destinations')
}

export function listAccommodationTypes(): Promise<AdminApiResult<string[]>> {
  return adminFetch<string[]>('/hotels/accommodation-types')
}

export function getHotel(hotelId: string): Promise<AdminApiResult<HotelDetailResponse>> {
  return adminFetch<HotelDetailResponse>(`/hotels/${hotelId}`)
}

export function updateHotel(hotelId: string, body: UpdateHotelRequest): Promise<AdminApiResult<UpdateHotelResponse>> {
  return adminFetch<UpdateHotelResponse>(`/hotels/${hotelId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** 503 (`airflow_unavailable`) is an expected outcome until Phase 13 (Airflow
 * client) exists, not a failure to alarm about -- reembed-dialog.tsx treats
 * it as "queue this for later" rather than an error banner. */
export function reembedHotel(hotelId: string): Promise<AdminApiResult<ReembedResponse>> {
  return adminFetch<ReembedResponse>(`/hotels/${hotelId}/reembed`, { method: 'POST' })
}

export function listAmenities(): Promise<AdminApiResult<AmenityOption[]>> {
  return adminFetch<AmenityOption[]>('/amenities?scope=hotel')
}

/** No `Content-Type` header set here on purpose -- `fetch` derives the
 * `multipart/form-data; boundary=...` header itself from the FormData body,
 * and overriding it (the way every other write in this file explicitly
 * sets `application/json`) would drop the boundary and break the upload. */
export function uploadHotelImage(hotelId: string, file: File): Promise<AdminApiResult<UploadImageResponse>> {
  const form = new FormData()
  form.append('file', file)
  return adminFetch<UploadImageResponse>(`/hotels/${hotelId}/images/upload`, { method: 'POST', body: form })
}

export async function exportHotelsCsv(params: HotelListParams): Promise<{ ok: true } | { ok: false; detail: string }> {
  const query = buildQuery(params)
  query.set('format', 'csv')
  let res: Response
  try {
    res = await fetch(`${BASE}/hotels?${query}`, { headers: await authHeaders() })
  } catch {
    return { ok: false, detail: 'Không thể kết nối tới máy chủ.' }
  }
  if (!res.ok) return { ok: false, detail: `Lỗi máy chủ (${res.status}).` }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'khach-san.csv'
  link.click()
  URL.revokeObjectURL(url)
  return { ok: true }
}
