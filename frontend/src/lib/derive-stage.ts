/**
 * derive-stage.ts — infers which of the 4 stage views the right-hand panel
 * should render, purely from the existing ChatState. No new store, no new
 * backend field: this is a read-only projection.
 *
 * Priority order matters and is covered by derive-stage.test.ts: hotels must
 * be checked before workspace so a user can still revisit hotel picking after
 * a trip_plan exists, and generating only fires when pending AND nothing is
 * renderable yet, so a mid-conversation turn doesn't blank out the workspace.
 */
import type { ChatState } from '../types'

export type StageView = 'intake' | 'generating' | 'hotels' | 'workspace'

export function deriveStageView(state: ChatState): StageView {
  if (state.pending && state.tripPlan == null && state.hotelOptions.length === 0) {
    return 'generating'
  }
  if (state.hotelOptions.length > 0) return 'hotels'
  if (state.tripPlan != null) return 'workspace'
  return 'intake'
}
