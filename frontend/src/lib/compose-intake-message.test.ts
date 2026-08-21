import { describe, expect, it } from 'vitest'
import {
  budgetRangePhrase,
  composeIntakeMessage,
  durationDaysBetween,
  PREFERENCES_SKIP_PHRASE,
  type IntakeFormState,
} from './compose-intake-message'

/**
 * Baseline wire-protocol tests. composeIntakeMessage() is FROZEN for Phase 6 —
 * the chat-panel restyle only changes *where/how* widgets collect the form, never
 * the sentence emitted. These exact-string assertions are the regression guard:
 * if a refactor changes the sentence, the backend intake extraction / budget
 * parser silently stops matching, so these must stay byte-identical.
 */

const MINIMAL: IntakeFormState = {
  destination: 'Đà Nẵng',
  startDate: '2026-08-10',
  endDate: '2026-08-13',
  guests: 2,
  budgetMinVnd: null,
  budgetMaxVnd: null,
  budgetSkipped: false,
  preferences: [],
  companions: '',
  pace: '',
  dayRhythm: [],
  notes: '',
  preferencesNotes: '',
}

function fill(overrides: Partial<IntakeFormState>): IntakeFormState {
  return { ...MINIMAL, ...overrides }
}

describe('durationDaysBetween', () => {
  it('counts whole days between two dates', () => {
    expect(durationDaysBetween('2026-08-10', '2026-08-13')).toBe(3)
  })
  it('returns 0 for missing or invalid dates', () => {
    expect(durationDaysBetween('', '')).toBe(0)
    expect(durationDaysBetween('garbage', '2026-08-13')).toBe(0)
  })
})

describe('budgetRangePhrase', () => {
  it('renders a VND min-max as the range phrase the backend budget parser keeps intact', () => {
    expect(budgetRangePhrase(800_000, 2_500_000)).toBe('từ 0.8 đến 2.5 triệu')
    expect(budgetRangePhrase(1_000_000, 2_000_000)).toBe('từ 1 đến 2 triệu')
  })
})

describe('composeIntakeMessage', () => {
  it('emits the exact required-facts sentence', () => {
    expect(composeIntakeMessage(MINIMAL)).toBe(
      'Tôi muốn đi Đà Nẵng từ ngày 10/08/2026 đến ngày 13/08/2026 cho 2 người.',
    )
  })

  it('adds the budget sentence when a range is chosen', () => {
    const message = composeIntakeMessage(fill({ budgetMinVnd: 800_000, budgetMaxVnd: 2_500_000 }))
    expect(message).toBe(
      'Tôi muốn đi Đà Nẵng từ ngày 10/08/2026 đến ngày 13/08/2026 cho 2 người. Ngân sách khách sạn: từ 0.8 đến 2.5 triệu.',
    )
  })

  it('adds the budget skip phrase when budget is skipped', () => {
    const message = composeIntakeMessage(fill({ budgetSkipped: true }))
    expect(message).toContain('Ngân sách khách sạn: không giới hạn.')
  })

  it('omits the budget sentence when neither a range nor skip is set', () => {
    const message = composeIntakeMessage(fill({}))
    expect(message).not.toContain('Ngân sách')
  })

  it('adds preferences with the exact wire labels, joined by ", "', () => {
    const message = composeIntakeMessage(fill({ preferences: ['beach', 'food'] }))
    expect(message).toContain('Sở thích: biển, ẩm thực.')
  })

  it('appends free text typed at the preferences step verbatim, unchecked against wire labels', () => {
    const message = composeIntakeMessage(fill({ preferences: ['beach'], preferencesNotes: 'trẻ em' }))
    expect(message).toContain('Sở thích: biển, trẻ em.')
    expect(message).not.toContain('Ghi chú')
  })

  it('emits a Sở thích sentence from free text alone, with no chip selected', () => {
    const message = composeIntakeMessage(fill({ preferencesNotes: 'yên tĩnh' }))
    expect(message).toContain('Sở thích: yên tĩnh.')
  })

  it('adds companions, pace, day rhythm and notes in stable order', () => {
    const message = composeIntakeMessage(
      fill({
        companions: 'family',
        pace: 'relaxed',
        dayRhythm: ['earlyStart'],
        notes: 'Ưu tiên view biển',
      }),
    )
    expect(message).toContain('Đi cùng: đi cùng gia đình.')
    expect(message).toContain('Nhịp độ: thư thái.')
    expect(message).toContain('Nhịp sinh hoạt: bắt đầu sớm.')
    expect(message).toContain('Ưu tiên view biển.')
    expect(message).not.toContain('Ghi chú')
  })

  // Typed free text is echoed back in the user's own chat bubble, so a bare
  // "2 người" must read as itself, not as a labelled note.
  it('emits notes as a plain sentence with no label, adding a period only when missing', () => {
    expect(composeIntakeMessage(fill({ notes: '2 người' }))).toContain('2 người.')
    expect(composeIntakeMessage(fill({ notes: 'Có trẻ nhỏ?' }))).toContain('Có trẻ nhỏ?')
    expect(composeIntakeMessage(fill({ notes: 'Có trẻ nhỏ?' }))).not.toContain('Có trẻ nhỏ?.')
  })

  it('omits the trip-facts sentence when required fields are incomplete', () => {
    const message = composeIntakeMessage(fill({ destination: '', guests: 0, startDate: '' }))
    expect(message).toBe('')
  })

  // The state the form lands in after the backend re-opens the date slot
  // (mergeIntakeIntoForm clears exactly those two fields). The sentence must
  // drop out whole rather than emit a truncated "trong 0 ngày từ " — the user
  // is being asked for new dates, and answering with the old ones would undo
  // the very change they requested.
  it('drops the trip-facts sentence, not just the dates, when dates were cleared', () => {
    const message = composeIntakeMessage(
      fill({ destination: 'Đà Nẵng', guests: 2, startDate: '', endDate: '', budgetSkipped: true }),
    )
    expect(message).not.toContain('Đà Nẵng')
    expect(message).not.toContain('0 ngày')
    expect(message).toContain('Ngân sách khách sạn')
  })

  // Session e773dff7 turn 5: the backend already held destination/dates/people
  // (`intake.missing` empty) and the user typed a correction. Restating the
  // stale destination alongside it produced a message that argued with itself
  // and showed up verbatim as the user's own chat bubble.
  it('omits the trip-facts sentence when the caller says the backend already has them', () => {
    const form = fill({
      destination: 'Hà Nội',
      startDate: '2026-07-01',
      endDate: '2026-07-02',
      guests: 2,
      notes: 'tôi muốn đổi lại đi nha trang',
    })
    expect(composeIntakeMessage(form, { includeTripFacts: false })).toBe(
      'tôi muốn đổi lại đi nha trang',
    )
    // Default stays byte-identical to the frozen wire protocol.
    expect(composeIntakeMessage(form)).toBe(
      'Tôi muốn đi Hà Nội từ ngày 01/07/2026 đến ngày 02/07/2026 cho 2 người. tôi muốn đổi lại đi nha trang',
    )
  })

  // Budget/preferences are never listed in `intake.missing`, so a locally
  // collected budget must still travel with the typed text even when the
  // trip facts are suppressed.
  it('keeps budget and preference sentences when trip facts are suppressed', () => {
    const message = composeIntakeMessage(
      fill({ budgetSkipped: true, notes: 'cho tôi xem khách sạn' }),
      { includeTripFacts: false },
    )
    expect(message).toBe('Ngân sách khách sạn: không giới hạn. cho tôi xem khách sạn')
  })
})

/**
 * `preferences.themes` is a REQUIRED slot in the backend's SLOT_REGISTRY
 * (skippable — an explicit opt-out satisfies it). The terminal submit has to
 * state that opt-out for a user who picked nothing, or the backend cannot
 * tell "no preference" from "not asked yet" and asks the question again in
 * chat right after the widget already asked it.
 *
 * The flag is opt-in and defaults off, so every sentence the FROZEN
 * assertions above pin stays byte-identical.
 */
describe('composeIntakeMessage preferences opt-out', () => {
  it('omits preferences entirely by default, as every mid-flow caller needs', () => {
    expect(composeIntakeMessage(MINIMAL)).not.toContain('Sở thích')
  })

  it('states the opt-out only when the terminal submit asks for it', () => {
    expect(composeIntakeMessage(MINIMAL, { includePreferencesOptOut: true })).toBe(
      `Tôi muốn đi Đà Nẵng từ ngày 10/08/2026 đến ngày 13/08/2026 cho 2 người. Sở thích: ${PREFERENCES_SKIP_PHRASE}.`,
    )
  })

  it('never replaces a real pick with the opt-out', () => {
    const message = composeIntakeMessage(fill({ preferences: ['beach'] }), {
      includePreferencesOptOut: true,
    })

    expect(message).not.toContain(PREFERENCES_SKIP_PHRASE)
    expect(message).toContain('Sở thích: biển.')
  })

  it('treats free text typed at the preferences step as a real answer too', () => {
    const message = composeIntakeMessage(fill({ preferencesNotes: 'thích lặn biển' }), {
      includePreferencesOptOut: true,
    })

    expect(message).not.toContain(PREFERENCES_SKIP_PHRASE)
    expect(message).toContain('Sở thích: thích lặn biển.')
  })
})
