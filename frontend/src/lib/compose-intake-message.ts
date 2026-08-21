/**
 * compose-intake-message.ts — turns the IntakeParametersForm state into ONE
 * Vietnamese sentence that the backend intake extraction (and the guided budget
 * parser) can parse back. Pure and unit-testable in isolation; the form only
 * ever sends this string through the existing chat endpoint.
 *
 * Field phrasing mirrors what the backend actually matches:
 *   - trip facts:        `_llm_extract_intake_facts()` (trip_intake.py:379)
 * Field phrasing mirrors what the backend actually matches:
 *   - trip facts:        `_llm_extract_intake_facts()` (trip_intake.py:379)
 *   - preferences/companions/pace/day_rhythm: the closed-set labels verbatim
 *                        (stored as canonical keys, mapped to wire strings via
 *                        lib/intake-options.ts)
 *   - budget range:      `_parse_free_text_budget()`'s explicit-range branch
 *                        (hotel_selection.py:_PRICE_RANGE_RE), fed by
 *                        budgetRangePhrase — "từ X đến Y triệu" keeps its true
 *                        min/max (not collapsed to a midpoint)
 *   - budget skip:       `_NO_BUDGET_PREFERENCE_PHRASES` (hotel_selection.py:383)
 */

import {
  type CompanionKey,
  type DayRhythmKey,
  type PaceKey,
  type PreferenceKey,
  COMPANION_WIRE_VALUE_VI,
  DAY_RHYTHM_WIRE_VALUE_VI,
  PACE_WIRE_VALUE_VI,
  PREFERENCE_WIRE_VALUE_VI,
} from './intake-options'
import { formatFullDate } from './format-trip-dates'

export interface IntakeFormState {
  destination: string
  startDate: string // YYYY-MM-DD (native date input format)
  endDate: string // YYYY-MM-DD (native date input format)
  guests: number
  budgetMinVnd: number | null // VND/night, from the budget range slider
  budgetMaxVnd: number | null
  budgetSkipped: boolean // "Bỏ qua ngân sách" — a real answer, not unset
  preferences: PreferenceKey[]
  companions: CompanionKey | ''
  pace: PaceKey | ''
  dayRhythm: DayRhythmKey[]
  notes: string
  // Free text typed into the composer while the sở thích (preferences) widget
  // is the active step — appended to the "Sở thích:" sentence verbatim,
  // unlike `notes`, which becomes its own unlabelled sentence. Neither is
  // checked against the closed PreferenceKey label set.
  preferencesNotes: string
}

/**
 * Whole-day count between two YYYY-MM-DD dates. Parsed as UTC midnight so the
 * result can't drift by a day around a DST boundary — native `Date` diffing
 * two local-midnight dates is the classic off-by-one trap this avoids.
 */
export function durationDaysBetween(startDate: string, endDate: string): number {
  if (!startDate || !endDate) return 0
  const start = Date.parse(`${startDate}T00:00:00Z`)
  const end = Date.parse(`${endDate}T00:00:00Z`)
  if (Number.isNaN(start) || Number.isNaN(end)) return 0
  return Math.round((end - start) / 86_400_000)
}

// The exact skip phrase `_NO_BUDGET_PREFERENCE_PHRASES` recognises
// (hotel_selection.py:383) — "no filter", a real answer, not a parse failure.
export const BUDGET_SKIP_PHRASE = 'không giới hạn'

/**
 * Render a VND min–max range (from the budget slider) as the sentence
 * `_parse_free_text_budget()`'s explicit-range branch matches — "từ X đến Y
 * triệu" — which now keeps its true (min, max), not a collapsed midpoint.
 * Source of truth: src/services/hotel_selection.py:_PRICE_RANGE_RE.
 */
export function budgetRangePhrase(minVnd: number, maxVnd: number): string {
  const million = (value: number) => value / 1_000_000
  return `từ ${million(minVnd)} đến ${million(maxVnd)} triệu`
}

export function composeIntakeMessage(form: IntakeFormState): string {
  const sentences: string[] = []

  // States both dates explicitly ("từ ngày X đến ngày Y") rather than a day
  // count ("trong N ngày từ X"): the backend's extract_patch LLM, faced with
  // only a duration, sometimes invents `dates.end` itself (reading "1 ngày"
  // as "leaves same day") instead of leaving it for the deterministic
  // start+N-days derivation — that self-supplied date can collide with the
  // start date and fail `end date must be after start`. Two literal dates
  // leave the model nothing to invent.
  //
  // Rendered `dd/mm/yyyy` (`formatFullDate(..., 'vi')`, same formatter the
  // date-range picker's chips use) rather than the form's raw ISO value:
  // `_parse_date_value` (travel_state.py) reads a bare `D/M/Y` fragment as
  // the Vietnamese DD-MM reading, and this sentence is always Vietnamese
  // regardless of UI language, so the date inside it should read the same
  // way a person would type it here.
  const durationDays = durationDaysBetween(form.startDate, form.endDate)
  if (form.destination && form.startDate && durationDays > 0 && form.guests > 0) {
    const startLabel = formatFullDate(form.startDate, 'vi') ?? form.startDate
    const endLabel = formatFullDate(form.endDate, 'vi') ?? form.endDate
    sentences.push(
      `Tôi muốn đi ${form.destination} từ ngày ${startLabel} đến ngày ${endLabel} cho ${form.guests} người.`,
    )
  }

  if (form.budgetSkipped) {
    sentences.push(`Ngân sách khách sạn: ${BUDGET_SKIP_PHRASE}.`)
  } else if (form.budgetMinVnd != null && form.budgetMaxVnd != null) {
    sentences.push(`Ngân sách khách sạn: ${budgetRangePhrase(form.budgetMinVnd, form.budgetMaxVnd)}.`)
  }

  const preferenceLabels = form.preferences.map((key) => PREFERENCE_WIRE_VALUE_VI[key])
  const freeTextPreference = form.preferencesNotes.trim()
  if (preferenceLabels.length > 0 || freeTextPreference) {
    const allLabels = freeTextPreference ? [...preferenceLabels, freeTextPreference] : preferenceLabels
    sentences.push(`Sở thích: ${allLabels.join(', ')}.`)
  }
  if (form.companions) {
    sentences.push(`Đi cùng: ${COMPANION_WIRE_VALUE_VI[form.companions]}.`)
  }
  if (form.pace) {
    sentences.push(`Nhịp độ: ${PACE_WIRE_VALUE_VI[form.pace]}.`)
  }
  if (form.dayRhythm.length > 0) {
    const labels = form.dayRhythm.map((key) => DAY_RHYTHM_WIRE_VALUE_VI[key])
    sentences.push(`Nhịp sinh hoạt: ${labels.join(', ')}.`)
  }
  // Free text goes in as its own plain sentence, with no "Ghi chú:" label.
  // The label was only ever cosmetic — nothing in the backend matches it —
  // and it showed up verbatim in the user's own chat bubble, so a person who
  // simply typed "2 người" saw their message echoed back as "Ghi chú: 2
  // người.". Ending punctuation is only added when the text lacks it.
  const notes = form.notes.trim()
  if (notes) {
    sentences.push(/[.!?]$/.test(notes) ? notes : `${notes}`)
  }

  return sentences.join(' ')
}
