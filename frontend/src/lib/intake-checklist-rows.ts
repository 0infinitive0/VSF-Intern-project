/**
 * intake-checklist-rows.ts — pure derivation of the five "THÔNG TIN AI ĐANG THU
 * THẬP" checklist rows from the frozen IntakeStatus contract (phase-07), plus
 * the widget form's own in-progress local state (phase — checklist live-update).
 *
 * Server-collected state is derived from `intake.missing` exactly as the
 * phase-07 plan specifies. The backend only ever emits the four gated keys —
 * 'destination', 'people', 'start_date', 'duration' (schemas.py
 * IntakeStatus.from_state) — so for those rows `missing` and "value present"
 * are equivalent signals; budget/preferences are NEVER in `missing` (the
 * backend does not gate them, see next-intake-field.ts) and are handled
 * explicitly below.
 *
 * people/dates/budget also light up from `form` the moment the user answers
 * the widget locally — IntakeParametersForm only round-trips ONE combined
 * message at the very last step, so waiting for server confirmation left
 * these rows stuck on "—" the entire time the user was stepping through them.
 * `isFieldFilled` (next-intake-field.ts) is reused as the single source of
 * truth for "is this field answered locally" — no separate logic invented
 * here. Once the server confirms a row, its formatted value wins (it's the
 * more authoritative string); the local value is just a placeholder for the
 * gap between "user answered" and "backend round-tripped it".
 */
import { formatCurrency } from './format-currency'
import { formatTripDateRange } from './format-trip-dates'
import { isFieldFilled, type IntakeFormShape } from './next-intake-field'
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

/** Translated fragments the pure lib needs but shouldn't own — sourced from
 * i18n by the caller (IntakeChecklist), same reasoning as the `locale` param. */
export interface IntakeChecklistLabels {
  /** "người" / "people" — appended to the local guest count. */
  peopleWord: string
  /** Shown for the budget row when the user picked "Bỏ qua ngân sách". */
  budgetSkipped: string
}

const MISSING_KEYS: Record<'destination' | 'people' | 'dates', readonly string[]> = {
  destination: ['destination'],
  people: ['people'],
  dates: ['start_date', 'duration'],
}

export function buildIntakeChecklistRows(
  intake: IntakeStatus | null,
  locale: string,
  form: IntakeFormShape | null = null,
  labels: IntakeChecklistLabels = { peopleWord: '', budgetSkipped: '' },
): IntakeChecklistRow[] {
  const missing = intake?.missing ?? []
  const missingAny = (keys: readonly string[]) => keys.some((key) => missing.includes(key))

  const serverDateRange = formatTripDateRange(intake?.start_date, intake?.end_date, locale)
  const preferenceKeys = intake?.preferences ?? []

  const destinationCollected = Boolean(intake?.destination) && !missingAny(MISSING_KEYS.destination)

  const peopleServerCollected = Boolean(intake?.people) && !missingAny(MISSING_KEYS.people)
  const peopleLocalCollected = isFieldFilled(form ?? {}, 'people')

  const datesServerCollected = serverDateRange != null && !missingAny(MISSING_KEYS.dates)
  const datesLocalCollected = isFieldFilled(form ?? {}, 'dates')
  const localDateRange = datesLocalCollected
    ? formatTripDateRange(form?.startDate, form?.endDate, locale)
    : null

  const budgetCollected = isFieldFilled(form ?? {}, 'budget')
  const budgetValue = form?.budgetSkipped
    ? labels.budgetSkipped
    : form?.budgetMinVnd != null && form?.budgetMaxVnd != null
      ? `${formatCurrency(form.budgetMinVnd, locale)} – ${formatCurrency(form.budgetMaxVnd, locale)}`
      : null

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
      // Falls back to the local guest count + peopleWord until the backend
      // confirms it.
      collected: peopleServerCollected || peopleLocalCollected,
      value: peopleServerCollected
        ? (intake?.people ?? null)
        : peopleLocalCollected
          ? `${form?.guests} ${labels.peopleWord}`.trim()
          : null,
      preferenceKeys: [],
    },
    {
      key: 'dates',
      collected: datesServerCollected || datesLocalCollected,
      value: datesServerCollected ? serverDateRange : localDateRange,
      preferenceKeys: [],
    },
    {
      // Never gated by the backend (see file header) — local-only signal.
      key: 'budget',
      collected: budgetCollected,
      value: budgetValue,
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
