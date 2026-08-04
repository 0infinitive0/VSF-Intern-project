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
 *   - budget tier:       `_parse_free_text_budget()` qualitative phrases
 *                        (hotel_selection.py:320-378) via budgetPhraseFromLabel
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

export interface IntakeFormState {
  destination: string
  startDate: string // YYYY-MM-DD (native date input format)
  endDate: string // YYYY-MM-DD (native date input format)
  guests: number
  budget: string // one of IntakeStatus.budget_options, '' = unset
  preferences: PreferenceKey[]
  companions: CompanionKey | ''
  pace: PaceKey | ''
  dayRhythm: DayRhythmKey[]
  notes: string
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

/**
 * Map a budget tier label (one of the backend's `budget_option_labels()`) to the
 * qualitative phrase `_parse_free_text_budget()` recognises. The three tier labels'
 * leading tokens map to their tier phrase; the skip option ("Bỏ qua, không cần lọc
 * theo giá") maps to the no-preference phrase; anything else — including an empty
 * unset value — maps to '' so the sentence omits the budget entirely (a blank
 * budget must not become a "no preference" answer that skips the budget question).
 * Source of truth: src/services/hotel_selection.py:509-531.
 */
export function budgetPhraseFromLabel(label: string): string {
  if (/Tiết kiệm/.test(label)) return 'tiết kiệm'
  if (/Tầm trung/.test(label)) return 'tầm trung'
  if (/Cao cấp/.test(label)) return 'cao cấp'
  if (/Bỏ qua/.test(label)) return 'không quan tâm giá khách sạn'
  return ''
}

export function composeIntakeMessage(form: IntakeFormState): string {
  const sentences: string[] = []

  const durationDays = durationDaysBetween(form.startDate, form.endDate)
  if (form.destination && form.startDate && durationDays > 0 && form.guests > 0) {
    sentences.push(
      `Tôi muốn đi ${form.destination} trong ${durationDays} ngày từ ${form.startDate} cho ${form.guests} người.`,
    )
  }

  const budget = budgetPhraseFromLabel(form.budget)
  if (budget) sentences.push(`Ngân sách khách sạn: ${budget}.`)

  if (form.preferences.length > 0) {
    const labels = form.preferences.map((key) => PREFERENCE_WIRE_VALUE_VI[key])
    sentences.push(`Sở thích: ${labels.join(', ')}.`)
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
  const notes = form.notes.trim()
  if (notes) {
    sentences.push(`Ghi chú: ${notes}.`)
  }

  return sentences.join(' ')
}
