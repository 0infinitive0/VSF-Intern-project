/**
 * thinking-lines.ts — turns a `phase` frame's facts into sentences.
 *
 * The backend sends keys, counts and schema field paths; every word the user
 * reads is composed here, from i18n templates. That split is the reason a
 * Vietnamese UI can describe an English-named worker without the backend ever
 * knowing what language the user speaks.
 *
 * **A missing fact produces no sentence.** Never a placeholder, never "Đang xử
 * lý…": a line that says nothing is worse than no line, because it looks like
 * information. Each sentence therefore tests for exactly the facts it needs, and
 * an interpolation never receives `undefined`.
 *
 * Unknown values — an intent, worker, or field path added to the backend after
 * this build — are skipped rather than rendered raw. Showing `budget.target` to
 * a user is the same failure as showing a phase key.
 */

import type { PhaseFacts } from '../types'

/** Minimal shape of i18next's `t`, so these stay pure functions in tests. */
export type Translate = (key: string, params?: Record<string, unknown>) => string

const INTENT_I18N_KEY: Record<string, string> = {
  update_trip: 'thinkingIntentUpdateTrip',
  general_question: 'thinkingIntentGeneralQuestion',
  rebuild_days: 'thinkingIntentRebuildDays',
}

const WORKER_I18N_KEY: Record<string, string> = {
  hotel_node: 'thinkingWorkerHotel',
  itinerary_node: 'thinkingWorkerItinerary',
  booking_node: 'thinkingWorkerBooking',
  qa_node: 'thinkingWorkerQa',
  respond: 'thinkingWorkerRespond',
}

const FIELD_I18N_KEY: Record<string, string> = {
  destination: 'thinkingFieldDestination',
  people: 'thinkingFieldPeople',
  'dates.start': 'thinkingFieldDateStart',
  'dates.end': 'thinkingFieldDateEnd',
  'budget.target': 'thinkingFieldBudget',
  preferences: 'thinkingFieldPreferences',
}

/** hotel_search outcomes worth a sentence of their own. */
const EMPTY_RESULT_I18N_KEY: Record<string, string> = {
  no_results: 'thinkingHotelNoResults',
  no_results_dates: 'thinkingHotelNoResultsDates',
  no_results_amenities: 'thinkingHotelNoResultsAmenities',
  no_results_rating: 'thinkingHotelNoResultsRating',
  error: 'thinkingHotelError',
}

function labelled(t: Translate, map: Record<string, string>, value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null
  const key = map[value]
  return key ? t(key) : null
}

function intakeLines(t: Translate, facts: PhaseFacts): string[] {
  const lines: string[] = []

  const intent = labelled(t, INTENT_I18N_KEY, facts.intent)
  if (intent) lines.push(t('thinkingIntakeIntent', { intent }))

  const fields = (facts.fields ?? [])
    .map((path) => labelled(t, FIELD_I18N_KEY, path))
    .filter((label): label is string => label !== null)
  if (fields.length) lines.push(t('thinkingIntakeFields', { fields: fields.join(', ') }))

  return lines
}

function routingLines(t: Translate, facts: PhaseFacts): string[] {
  const worker = labelled(t, WORKER_I18N_KEY, facts.worker)
  return worker ? [t('thinkingRoutingWorker', { worker })] : []
}

function hotelSearchLines(t: Translate, facts: PhaseFacts): string[] {
  const lines: string[] = []

  // Where we looked. The radius half only appears when the user set one, so the
  // sentence never reads "within undefined km".
  if (facts.destination) {
    lines.push(
      typeof facts.radius_km === 'number'
        ? t('thinkingHotelSearchRadius', {
            destination: facts.destination,
            radius: facts.radius_km,
          })
        : t('thinkingHotelSearchWhere', { destination: facts.destination }),
    )
  }

  if (facts.amenities?.length) {
    lines.push(t('thinkingHotelAmenities', { count: facts.amenities.length }))
  }

  const emptyKey = facts.outcome ? EMPTY_RESULT_I18N_KEY[facts.outcome] : undefined
  if (emptyKey) {
    lines.push(t(emptyKey))
  } else if (typeof facts.kept === 'number' && facts.kept > 0) {
    lines.push(t('thinkingHotelKept', { count: facts.kept }))
  }

  return lines
}

function routingLegsLines(t: Translate, facts: PhaseFacts): string[] {
  return typeof facts.days === 'number' ? [t('thinkingRoutingLegs', { days: facts.days })] : []
}

const BUILDERS: Record<string, (t: Translate, facts: PhaseFacts) => string[]> = {
  intake_check: intakeLines,
  routing: routingLines,
  hotel_search: hotelSearchLines,
  routing_legs: routingLegsLines,
}

/**
 * Sentences for one phase frame; `[]` when the step reported nothing usable.
 *
 * An empty result is the normal case for most keys — `compacting_history`,
 * `generating` and `persisting` carry no facts at all — and the caller renders
 * the step with its label alone.
 */
export function thinkingLines(t: Translate, phaseKey: string, facts: PhaseFacts = {}): string[] {
  const build = BUILDERS[phaseKey]
  return build ? build(t, facts) : []
}
