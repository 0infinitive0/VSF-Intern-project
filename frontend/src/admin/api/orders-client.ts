/**
 * orders-client.ts — D1 (Danh sách đơn hàng) API calls (phase-04-orders-
 * list.md). One endpoint (`GET /orders?tab=paid|unpaid`) serves both tabs;
 * `listOrders`/`listUnpaidBookings` are typed wrappers over it since each
 * tab's response shape differs. CSV export reuses the same header-based
 * fetch as hotels-client.ts's `exportHotelsCsv` -- a plain `<a href>` can't
 * carry the bearer token.
 */
import { authHeaders } from '../../api/auth-headers'
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1/admin'

export type OrderRow = components['schemas']['OrderRow']
export type OrderListResponse = components['schemas']['OrderListResponse']
export type UnpaidBookingRow = components['schemas']['UnpaidBookingRow']
export type UnpaidBookingListResponse = components['schemas']['UnpaidBookingListResponse']
export type ReleaseExpiredResponse = components['schemas']['ReleaseExpiredResponse']
export type OrderStatsResponse = components['schemas']['OrderStatsResponse']
export type OrderDetailResponse = components['schemas']['OrderDetailResponse']
export type OrderRoomLine = components['schemas']['OrderRoomLine']
export type OrderTimelineEvent = components['schemas']['OrderTimelineEvent']

export type OrdersTab = 'paid' | 'unpaid'

export interface OrdersListParams {
  tab: OrdersTab
  bookingStatus?: string
  paymentStatus?: string
  from?: string
  to?: string
  hotelId?: string
  q?: string
  needsAttention?: boolean
  page: number
  pageSize: number
}

function buildQuery(params: OrdersListParams): URLSearchParams {
  const search = new URLSearchParams()
  search.set('tab', params.tab)
  if (params.bookingStatus) search.set('booking_status', params.bookingStatus)
  if (params.paymentStatus) search.set('payment_status', params.paymentStatus)
  if (params.from) search.set('from', params.from)
  if (params.to) search.set('to', params.to)
  if (params.hotelId) search.set('hotel_id', params.hotelId)
  if (params.q) search.set('q', params.q)
  if (params.needsAttention !== undefined) search.set('needs_attention', String(params.needsAttention))
  search.set('page', String(params.page))
  search.set('page_size', String(params.pageSize))
  return search
}

export function listOrders(params: OrdersListParams): Promise<AdminApiResult<OrderListResponse>> {
  return adminFetch<OrderListResponse>(`/orders?${buildQuery(params)}`)
}

export function listUnpaidBookings(params: OrdersListParams): Promise<AdminApiResult<UnpaidBookingListResponse>> {
  return adminFetch<UnpaidBookingListResponse>(`/orders?${buildQuery(params)}`)
}

export function getOrderStats(): Promise<AdminApiResult<OrderStatsResponse>> {
  return adminFetch<OrderStatsResponse>('/orders/stats')
}

export function getOrderDetail(paymentId: string): Promise<AdminApiResult<OrderDetailResponse>> {
  return adminFetch<OrderDetailResponse>(`/orders/${paymentId}`)
}

export function releaseExpiredHolds(): Promise<AdminApiResult<ReleaseExpiredResponse>> {
  return adminFetch<ReleaseExpiredResponse>('/orders/holds/release-expired', { method: 'POST' })
}

export async function exportOrdersCsv(params: OrdersListParams): Promise<{ ok: true } | { ok: false; detail: string }> {
  const query = buildQuery(params)
  query.set('format', 'csv')
  let res: Response
  try {
    res = await fetch(`${BASE}/orders?${query}`, { headers: await authHeaders() })
  } catch {
    return { ok: false, detail: 'Không thể kết nối tới máy chủ.' }
  }
  if (!res.ok) return { ok: false, detail: `Lỗi máy chủ (${res.status}).` }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = params.tab === 'unpaid' ? 'giu-cho-chua-thanh-toan.csv' : 'don-hang.csv'
  link.click()
  URL.revokeObjectURL(url)
  return { ok: true }
}
