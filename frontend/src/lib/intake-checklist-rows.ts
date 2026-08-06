/**
 * intake-checklist-rows.ts — pure derivation of the five "THÔNG TIN AI ĐANG THU
 * THẬP" checklist rows from the frozen IntakeStatus contract (phase-07).
 *
 * Collected state is derived from `intake.missing` exactly as the phase-07 plan
 * specifies ("Trạng thái chưa có suy ra từ intake.missing"). The backend only
 * ever emits the four gated keys — 'destination', 'people', 'start_date',
 * 'duration' (schemas.py IntakeStatus.from_state) — so for those rows `missing`
 * and "value present" are equivalent signals; budget/preferences are NEVER in
 * `missing` (the backend does not gate them, see next-intake-field.ts) and are
 * handled explicitly below.
 *
 * Budget row: always uncollected. The frozen contract carries no "chosen budget
 * tier" field (the chosen tier only exists inside the free-text chat message
 * and, on the real backend, as min_price/max_price — integers that are not part
 * of types.ts / docs/chat_api_contract.md / mock fixtures). Showing a tier name
 * would be inventing data; "—" is the honest render. If the contract later
 * declares a chosen-tier field, this row can light up with no other change.
 */
import { formatTripDateRange } from './format-trip-dates'
import type { IntakeStatus } from '../types'

export type IntakeChecklistRowKey =
  | 'destination'
  | 'people'
  | 'dates'
  | 'budget'
  | 'preferences'

export interface IntakeChecklistRow {
  key: IntakeChecklistRowKey
  collected: boolean
  /** Display string for collected rows; null renders the design's "—" dash. */
  value: string | null
  /** Preference wire keys (canonical PreferenceKey values) — translated by the
   * component via `intake.preferenceOptions.<key>`, kept raw here. */
  preferenceKeys: string[]
}

const MISSING_KEYS: Record<IntakeChecklistRowKey, readonly string[]> = {
  destination: ['destination'],
  people: ['people'],
  dates: ['start_date', 'duration'],
  budget: [],
  preferences: [],
}

export function buildIntakeChecklistRows(
  intake: IntakeStatus | null,
  locale: string,
): IntakeChecklistRow[] {
  const missing = intake?.missing ?? []
  const missingAny = (keys: readonly string[]) => keys.some((key) => missing.includes(key))

  const dateRange = formatTripDateRange(intake?.start_date, intake?.end_date, locale)
  const preferenceKeys = intake?.preferences ?? []

  const destinationCollected = Boolean(intake?.destination) && !missingAny(MISSING_KEYS.destination)
  const peopleCollected = Boolean(intake?.people) && !missingAny(MISSING_KEYS.people)
  const datesCollected = dateRange != null && !missingAny(MISSING_KEYS.dates)

  // Values are gated on `collected` even though the backend never emits a
  // contradictory payload (value present AND key in `missing`) — the gated
  // form makes that invariant self-enforcing here.
  return [
    {
      key: 'destination',
      collected: destinationCollected,
      value: destinationCollected ? (intake?.destination ?? null) : null,
      preferenceKeys: [],
    },
    {
      key: 'people',
      // intake.people is a backend-formatted string ("2 người") — display
      // verbatim, never re-parse (types.ts comment; phase-07 acceptance).
      collected: peopleCollected,
      value: peopleCollected ? (intake?.people ?? null) : null,
      preferenceKeys: [],
    },
    {
      key: 'dates',
      collected: datesCollected,
      value: datesCollected ? dateRange : null,
      preferenceKeys: [],
    },
    {
      // See file header — no chosen-tier signal exists in the frozen contract.
      key: 'budget',
      collected: false,
      value: null,
      preferenceKeys: [],
    },
    {
      // Not gated by `missing`; collected the moment the backend echoes real
      // preference keys (they arrive together with an intake response).
      key: 'preferences',
      collected: preferenceKeys.length > 0,
      value: null,
      preferenceKeys,
    },
  ]
}
