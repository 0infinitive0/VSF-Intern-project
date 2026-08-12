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

/** Phases the backend only emits once it starts the long work behind a plan — the point where a full-panel progress view actually earns its place. */
const HEAVY_WORK_PHASES = new Set(['hotel_search', 'itinerary_build'])

/**
 * @param intakeReady Whether the required intake fields are all answered, so a
 *   pending turn is the real hotel-search request rather than the backend just
 *   replying to one more intake question. Defaults to true, which keeps every
 *   pre-existing single-argument call behaving exactly as before.
 *
 * Answering an intake question used to swap the whole right-hand panel for the
 * generating view, which meant the checklist the user was filling in vanished
 * mid-collection. It now stays put until either the local form is complete or
 * the backend reports (via real `phases`, never a guess) that it has moved on
 * to searching hotels / building the itinerary — the latter covers the user who
 * types every detail in one free-text message and so never fills the form.
 */
export function deriveStageView(state: ChatState, intakeReady = true): StageView {
  if (state.pending && state.tripPlan == null && state.hotelOptions.length === 0) {
    const heavyWorkStarted = state.phases.some((phase) => HEAVY_WORK_PHASES.has(phase.key))
    return intakeReady || heavyWorkStarted ? 'generating' : 'intake'
  }
  if (state.hotelOptions.length > 0) return 'hotels'
  if (state.tripPlan != null) return 'workspace'
  return 'intake'
}
