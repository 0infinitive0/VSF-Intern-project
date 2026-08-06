import { describe, expect, it } from 'vitest'
import {
  budgetPhraseFromLabel,
  composeIntakeMessage,
  durationDaysBetween,
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
  budget: '',
  preferences: [],
  companions: '',
  pace: '',
  dayRhythm: [],
  notes: '',
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

describe('budgetPhraseFromLabel', () => {
  it('maps tier labels to the phrases the backend budget parser recognises', () => {
    expect(budgetPhraseFromLabel('Tiết kiệm ...')).toBe('tiết kiệm')
    expect(budgetPhraseFromLabel('Tầm trung ...')).toBe('tầm trung')
    expect(budgetPhraseFromLabel('Cao cấp ...')).toBe('cao cấp')
  })
  it('maps the skip label to the no-preference phrase', () => {
    expect(budgetPhraseFromLabel('Bỏ qua, không cần lọc theo giá')).toBe('không quan tâm giá khách sạn')
  })
  it('maps unknown/blank to "" (budget omitted entirely, not answered "no")', () => {
    expect(budgetPhraseFromLabel('')).toBe('')
    expect(budgetPhraseFromLabel('whatever')).toBe('')
  })
})

describe('composeIntakeMessage', () => {
  it('emits the exact required-facts sentence', () => {
    expect(composeIntakeMessage(MINIMAL)).toBe(
      'Tôi muốn đi Đà Nẵng trong 3 ngày từ 2026-08-10 cho 2 người.',
    )
  })

  it('adds the budget sentence when a tier is chosen', () => {
    const message = composeIntakeMessage(fill({ budget: 'Khách sạn Tầm trung' }))
    expect(message).toBe(
      'Tôi muốn đi Đà Nẵng trong 3 ngày từ 2026-08-10 cho 2 người. Ngân sách khách sạn: tầm trung.',
    )
  })

  it('adds the budget skip phrase for the "Bỏ qua" label', () => {
    const message = composeIntakeMessage(fill({ budget: 'Bỏ qua, không cần lọc theo giá' }))
    expect(message).toContain('Ngân sách khách sạn: không quan tâm giá khách sạn.')
  })

  it('adds preferences with the exact wire labels, joined by ", "', () => {
    const message = composeIntakeMessage(fill({ preferences: ['beach', 'food'] }))
    expect(message).toContain('Sở thích: biển, ẩm thực.')
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
    expect(message).toContain('Ghi chú: Ưu tiên view biển.')
  })

  it('omits the trip-facts sentence when required fields are incomplete', () => {
    const message = composeIntakeMessage(fill({ destination: '', guests: 0, startDate: '' }))
    expect(message).toBe('')
  })
})
