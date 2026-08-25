/**
 * overview-client.ts — A3 (Tổng quan vận hành, phase-17-overview-kpi.md)
 * API call. One GET, ghép lại số liệu đã có từ Phase 4/12/14 -- no other
 * client function belongs here.
 */
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

export type OverviewResponse = components['schemas']['OverviewResponse']
export type OverviewOrders = components['schemas']['OverviewOrders']
export type OverviewAttentionOrder = components['schemas']['OverviewAttentionOrder']
export type OverviewExpiringHold = components['schemas']['OverviewExpiringHold']
export type OverviewEmbedding = components['schemas']['OverviewEmbedding']
export type OverviewPipeline = components['schemas']['OverviewPipeline']

export function getOverview(): Promise<AdminApiResult<OverviewResponse>> {
  return adminFetch<OverviewResponse>('/overview')
}
