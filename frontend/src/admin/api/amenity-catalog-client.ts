/**
 * amenity-catalog-client.ts — Danh mục tiện ích & tiện nghi (phase-18-amenity-catalog.md).
 * Same `adminFetch<T>` posture as hotels-client.ts: thin one-liners, typed
 * from wire.generated.ts's `components['schemas'][...]`, escape hatches from
 * `adminFetch` only where a response doesn't fit `AdminApiResult<T>`'s
 * "single JSON body, `detail` on error" assumption (delete's 204, retire's
 * 409 payload carrying extra fields).
 */
import { authHeaders } from '../../api/auth-headers'
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

export type AmenityCatalogRow = components['schemas']['AmenityCatalogRow']
export type AmenityCatalogListResponse = components['schemas']['AmenityCatalogListResponse']
export type CheckDuplicateRequest = components['schemas']['CheckDuplicateRequest']
export type CheckDuplicateResponse = components['schemas']['CheckDuplicateResponse']
export type FlaggedName = components['schemas']['FlaggedName']
export type AmenityMatch = components['schemas']['AmenityMatch']
export type DraftRequest = components['schemas']['DraftRequest']
export type DraftResponse = components['schemas']['DraftResponse']
export type UpdateAmenityRequest = components['schemas']['UpdateAmenityRequest']
export type UpdateAmenityResponse = components['schemas']['UpdateAmenityResponse']
export type ApproveResponse = components['schemas']['ApproveResponse']
export type BulkApproveResponse = components['schemas']['BulkApproveResponse']
export type RetireResponse = components['schemas']['RetireResponse']

export type CatalogScope = 'hotel' | 'room' | 'all'
export type CatalogStatus = 'approved' | 'pending' | 'retired' | 'all'
export type CatalogSortKey = 'name' | 'category' | 'scope' | 'usage' | 'status'
export type CatalogSortDirection = 'asc' | 'desc'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1/admin'

export function listAmenityCatalog(params: {
  scope: CatalogScope
  status: CatalogStatus
  category: string
  q?: string
  sort?: CatalogSortKey
  direction?: CatalogSortDirection
  page: number
  pageSize: number
}): Promise<AdminApiResult<AmenityCatalogListResponse>> {
  const query = new URLSearchParams({
    scope: params.scope,
    status: params.status,
    category: params.category,
    page: String(params.page),
    page_size: String(params.pageSize),
  })
  if (params.q) query.set('q', params.q)
  if (params.sort) query.set('sort', params.sort)
  if (params.direction) query.set('direction', params.direction)
  return adminFetch<AmenityCatalogListResponse>(`/amenity-catalog?${query.toString()}`)
}

export function checkDuplicateAmenities(body: CheckDuplicateRequest): Promise<AdminApiResult<CheckDuplicateResponse>> {
  return adminFetch<CheckDuplicateResponse>('/amenity-catalog/check-duplicate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function draftAmenities(body: DraftRequest): Promise<AdminApiResult<DraftResponse>> {
  return adminFetch<DraftResponse>('/amenity-catalog/draft', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function updateAmenity(id: string, body: UpdateAmenityRequest): Promise<AdminApiResult<UpdateAmenityResponse>> {
  return adminFetch<UpdateAmenityResponse>(`/amenity-catalog/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function approveAmenity(id: string): Promise<AdminApiResult<ApproveResponse>> {
  return adminFetch<ApproveResponse>(`/amenity-catalog/${encodeURIComponent(id)}/approve`, { method: 'POST' })
}

export function bulkApproveAmenities(ids: string[]): Promise<AdminApiResult<BulkApproveResponse>> {
  return adminFetch<BulkApproveResponse>('/amenity-catalog/bulk-approve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
}

/** 204 on success -- bypasses adminFetch, which unconditionally parses a JSON
 * body (same reasoning as hotels-client.ts's deleteRoom). */
export async function deleteAmenity(id: string): Promise<AdminApiResult<null>> {
  let res: Response
  try {
    res = await fetch(`${BASE}/amenity-catalog/${encodeURIComponent(id)}`, { method: 'DELETE', headers: await authHeaders() })
  } catch {
    return { ok: false, status: 0, detail: 'Không thể kết nối tới máy chủ.' }
  }
  if (!res.ok) {
    let detail = `Lỗi máy chủ (${res.status}).`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // No JSON body -- keep the generic detail.
    }
    return { ok: false, status: res.status, detail }
  }
  return { ok: true, data: null }
}

export interface RetireBlockedError {
  detail: 'amenity_in_use' | 'amenity_has_active_children' | 'amenity_not_approved'
  hotel_count: number
  room_count: number
  child_count: number
  children?: { id: string; label_vi: string }[]
}

export type RetireResult = { ok: true; data: RetireResponse } | { ok: false; status: number; detail: string; blocked?: RetireBlockedError }

/** The 409 payload carries `hotel_count`/`room_count`/`child_count`/`children`
 * beyond a plain `detail` string -- adminFetch's AdminApiResult only keeps
 * `detail`, so this reads the body directly (same posture as hotels-client.ts's
 * setHotelActive, which does the same for its bulk-block 409). */
export async function retireAmenity(id: string): Promise<RetireResult> {
  let res: Response
  try {
    res = await fetch(`${BASE}/amenity-catalog/${encodeURIComponent(id)}/retire`, {
      method: 'PATCH',
      headers: await authHeaders(),
    })
  } catch {
    return { ok: false, status: 0, detail: 'Không thể kết nối tới máy chủ.' }
  }
  let body: unknown
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (!res.ok) {
    const parsed = body as RetireBlockedError | { detail?: string } | null
    const detail =
      parsed && typeof (parsed as { detail?: unknown }).detail === 'string' ? (parsed as { detail: string }).detail : `Lỗi máy chủ (${res.status}).`
    const blocked = parsed && 'hotel_count' in (parsed as object) ? (parsed as RetireBlockedError) : undefined
    return { ok: false, status: res.status, detail, blocked }
  }
  return { ok: true, data: body as RetireResponse }
}

export function reactivateAmenity(id: string): Promise<AdminApiResult<RetireResponse>> {
  return adminFetch<RetireResponse>(`/amenity-catalog/${encodeURIComponent(id)}/reactivate`, { method: 'POST' })
}
