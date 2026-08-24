import type { components } from '../../types/wire.generated'
import { adminFetch, type AdminApiResult } from './client'

export type AdminMe = components['schemas']['AdminMeResponse']

export function getAdminMe(): Promise<AdminApiResult<AdminMe>> {
  return adminFetch<AdminMe>('/me')
}
