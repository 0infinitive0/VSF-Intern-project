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
 * The explicit "no particular preference" answer for `preferences.themes`,
 * worded to match what `build_extract_patch_prompt` teaches the extractor to
 * map to `{path: 'preferences.themes', operation: 'set', value: null}` —
 * NOT_APPLICABLE, a real answer, distinct from never having been asked.
 *
 * Why the widget has to say this out loud: `preferences.themes` is a
 * REQUIRED slot in the backend's SLOT_REGISTRY (skippable, so an opt-out
 * satisfies it). A user who picks no chips and submits sends a sentence with
 * no preference clause at all — silence, which the backend cannot tell from
 * "not asked yet", so it would ask again in chat right after the widget
 * already asked. Stating the opt-out is what keeps that question to one ask.
 */
export const PREFERENCES_SKIP_PHRASE = 'không có gì đặc biệt'

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

export interface ComposeIntakeOptions {
  /**
   * Whether to open with the destination/dates/people sentence. Default true.
   *
   * That sentence exists to carry gated answers the widget rail collected
   * LOCALLY to a backend that has never seen them. Once the backend reports
   * `intake.missing` empty it already holds all three, and restating them is
   * not merely redundant — it contradicts a correction typed in the same
   * breath. "tôi muốn đổi lại đi nha trang" went out as "Tôi muốn đi Hà Nội
   * ... tôi muốn đổi lại đi nha trang", leaving `extract_patch`'s model to
   * adjudicate a conflict the composer invented, and echoing a sentence the
   * user never wrote back into their own chat bubble.
   *
   * Only the free-text composer path passes false; the widget's own submit
   * buttons and the duplicate-trip flow always state the facts in full,
   * because those are exactly the turns that deliver them for the first time.
   */
  includeTripFacts?: boolean
  /**
   * Whether an empty preferences selection should be stated as an explicit
   * opt-out rather than simply omitted. Default false.
   *
   * Only the TERMINAL submit passes true — the button that ends intake and
   * sends everything. Every other caller composes mid-flow (a single-field
   * correction, free text typed while an earlier widget is active), where
   * "no chips picked yet" means the user has not reached that step, not that
   * they have no preference. Emitting the opt-out there would answer a
   * question on the user's behalf before it was ever put to them.
   */
  includePreferencesOptOut?: boolean
  /**
   * Whether to restate preference chips / companions / pace / day-rhythm —
   * each defaults true (every existing caller, including the terminal
   * "preferences" widget submit, states everything it knows). The free-text
   * composer path (chat-panel.tsx's handleComposerSend) is the only caller
   * that passes false for a field the backend has already confirmed: once
   * `intake.companions` (etc.) is set, that field must not keep riding along
   * on every later typed message the way `includeTripFacts` already guards
   * destination/dates/people — see the `includeTripFacts` doc above for the
   * self-contradiction bug this mirrors ("Đi cùng: đi một mình." glued onto
   * a message that only asked to change the date).
   */
  includePreferenceLabels?: boolean
  includeCompanions?: boolean
  includePace?: boolean
  includeDayRhythm?: boolean
}

export function composeIntakeMessage(
  form: IntakeFormState,
  {
    includeTripFacts = true,
    includePreferencesOptOut = false,
    includePreferenceLabels = true,
    includeCompanions = true,
    includePace = true,
    includeDayRhythm = true,
  }: ComposeIntakeOptions = {},
): string {
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
  if (includeTripFacts && form.destination && form.startDate && durationDays > 0 && form.guests > 0) {
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

  const preferenceLabels = includePreferenceLabels
    ? form.preferences.map((key) => PREFERENCE_WIRE_VALUE_VI[key])
    : []
  const freeTextPreference = form.preferencesNotes.trim()
  if (preferenceLabels.length > 0 || freeTextPreference) {
    const allLabels = freeTextPreference ? [...preferenceLabels, freeTextPreference] : preferenceLabels
    sentences.push(`Sở thích: ${allLabels.join(', ')}.`)
  } else if (includePreferencesOptOut) {
    sentences.push(`Sở thích: ${PREFERENCES_SKIP_PHRASE}.`)
  }
  if (includeCompanions && form.companions) {
    sentences.push(`Đi cùng: ${COMPANION_WIRE_VALUE_VI[form.companions]}.`)
  }
  if (includePace && form.pace) {
    sentences.push(`Nhịp độ: ${PACE_WIRE_VALUE_VI[form.pace]}.`)
  }
  if (includeDayRhythm && form.dayRhythm.length > 0) {
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
