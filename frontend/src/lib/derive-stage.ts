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
 *
 * @param hotelsEverFound Whether a hotel search has produced options at any
 *   point this session (App.tsx's retained per-session list). `state.hotelOptions`
 *   only carries the CURRENT turn's options, and the backend legitimately
 *   returns none on any turn that didn't re-run the search — a qa_node answer,
 *   a hotel selection. Without this, such a turn fell through every branch
 *   below to `'intake'` and threw the user back to step 1 with the hotel list
 *   gone. Checked AFTER `tripPlan` so a built itinerary still opens the
 *   workspace; the user reaches hotels again through the step navigator's
 *   client-side view override.
 *
 * A trip that already exists can ALSO swap to 'generating' mid-turn — a
 * hotel/destination change rebuilds the whole itinerary (a real Mapbox
 * routing pass, several seconds), and showing the same full progress screen
 * the first build gets (rather than leaving the stale plan on screen with no
 * feedback) is what the guest actually asked for. This only fires once
 * `heavyWorkStarted` is real backend-confirmed work, never a bare `pending`
 * guess — an unrelated QA question never emits `hotel_search`/
 * `itinerary_build`, so it still leaves the itinerary/map exactly where they
 * were (stage-workspace.tsx's own lighter-weight overlay covers that case,
 * and the brief window before the first phase event streams in).
 */
export function deriveStageView(
  state: ChatState,
  intakeReady = true,
  hotelsEverFound = false,
): StageView {
  if (state.pending && state.hotelOptions.length === 0) {
    const heavyWorkStarted = state.phases.some((phase) => HEAVY_WORK_PHASES.has(phase.key))
    if (state.tripPlan == null) {
      return intakeReady || heavyWorkStarted ? 'generating' : 'intake'
    }
    if (heavyWorkStarted) return 'generating'
  }
  if (state.hotelOptions.length > 0) return 'hotels'
  if (state.tripPlan != null) return 'workspace'
  if (hotelsEverFound) return 'hotels'
  return 'intake'
}
