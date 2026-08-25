/**
 * pipelines-client.ts — C1 (Danh sách pipeline, phase-14-pipelines-list.md)
 * API calls. `dag_id` travels through this client (the backend contract
 * carries it) but no admin page may render it -- every screen uses `label`.
 */
import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

export type PipelinesListResponse = components['schemas']['PipelinesListResponse']
export type PipelineItem = components['schemas']['PipelineItem']
export type PipelineLastRun = components['schemas']['PipelineLastRun']
export type PipelineProgress = components['schemas']['PipelineProgress']
export type PipelineRunSummary = components['schemas']['PipelineRunSummary']
export type TriggerRunResponse = components['schemas']['TriggerRunResponse']

export function listPipelines(): Promise<AdminApiResult<PipelinesListResponse>> {
  return adminFetch<PipelinesListResponse>('/pipelines')
}

export function triggerPipelineRun(dagId: string, conf: Record<string, unknown> = {}): Promise<AdminApiResult<TriggerRunResponse>> {
  return adminFetch<TriggerRunResponse>(`/pipelines/${dagId}/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conf }),
  })
}
