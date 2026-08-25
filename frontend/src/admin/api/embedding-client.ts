/**
 * embedding-client.ts — B7 (Trạng thái embedding) / C4 (Độ phủ embedding)
 * read calls (phase-12-embedding-status.md). The write side (reembed) stays
 * in hotels-client.ts as `reembedHotels` -- it is hotel-scoped even when
 * called from here, per that phase's "một endpoint, không phải bốn".
 */
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

export type EmbeddingSummaryResponse = components['schemas']['EmbeddingSummaryResponse']
export type EmbeddingTableSummary = components['schemas']['EmbeddingTableSummary']
export type EmbeddingMissingResponse = components['schemas']['EmbeddingMissingResponse']
export type EmbeddingMissingItem = components['schemas']['EmbeddingMissingItem']

export type EmbeddedTable = 'hotels' | 'rooms' | 'attractions'

export function getEmbeddingSummary(): Promise<AdminApiResult<EmbeddingSummaryResponse>> {
  return adminFetch<EmbeddingSummaryResponse>('/embedding/summary')
}

export function getEmbeddingMissing(table: EmbeddedTable, limit = 20): Promise<AdminApiResult<EmbeddingMissingResponse>> {
  return adminFetch<EmbeddingMissingResponse>(`/embedding/missing?table=${table}&limit=${limit}`)
}
