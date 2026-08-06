import { describe, expect, it } from 'vitest'
import {
  INTAKE_FIELD_ORDER,
  currentIntakeField,
  isFieldMissing,
  nextIntakeField,
  type IntakeField,
} from './next-intake-field'
import type { IntakeStatus } from '../types'

const BASE_INTAKE: IntakeStatus = {
  destination: null,
  duration: null,
  start_date: null,
  end_date: null,
  people: null,
  preferences: [],
  companions: null,
  pace: null,
  day_rhythm: [],
  notes: '',
  available_destinations: ['Đà Nẵng'],
  budget_options: [],
  missing: [],
}

function intakeWith(missing: string[], overrides: Partial<IntakeStatus> = {}): IntakeStatus {
  return { ...BASE_INTAKE, missing, budget_options: ['Khách sạn 4 sao'], ...overrides }
}

function form(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    destination: '',
    startDate: '',
    endDate: '',
    guests: 0,
    budget: '',
    preferences: [],
    ...overrides,
  }
}

describe('isFieldMissing', () => {
  it('maps only the real backend missing keys onto the widget fields', () => {
    const intake = intakeWith(['destination', 'start_date', 'duration', 'people'])
    expect(isFieldMissing(intake, 'destination')).toBe(true)
    expect(isFieldMissing(intake, 'people')).toBe(true)
    expect(isFieldMissing(intake, 'dates')).toBe(true)
    expect(isFieldMissing(intake, 'budget')).toBe(false)
    expect(isFieldMissing(intake, 'preferences')).toBe(false)
  })

  it('treats start_date and duration as one "dates" field', () => {
    expect(isFieldMissing(intakeWith(['start_date']), 'dates')).toBe(true)
    expect(isFieldMissing(intakeWith(['duration']), 'dates')).toBe(true)
  })

  it('returns false for a null intake', () => {
    expect(isFieldMissing(null, 'destination')).toBe(false)
  })
})

describe('nextIntakeField', () => {
  it('returns null when nothing is missing', () => {
    expect(nextIntakeField(intakeWith([]))).toBeNull()
  })

  it('returns the first missing field in widget order', () => {
    expect(nextIntakeField(intakeWith(['people', 'destination']))).toBe('destination')
  })

  it('never surfaces budget/preferences as server-required', () => {
    expect(nextIntakeField(intakeWith(['budget']))).toBeNull()
    expect(nextIntakeField(intakeWith(['preferences']))).toBeNull()
  })
})

describe('currentIntakeField', () => {
  it('returns null for null intake', () => {
    expect(currentIntakeField(null, form())).toBeNull()
  })

  it('walks required fields first, in order, until one is missing', () => {
    const intake = intakeWith(['destination', 'people', 'start_date', 'duration'])
    expect(currentIntakeField(intake, form())).toBe('destination')
    expect(
      currentIntakeField(intake, form({ destination: 'Đà Nẵng' })),
    ).toBe('people')
    expect(
      currentIntakeField(intake, form({ destination: 'Đà Nẵng', guests: 2 })),
    ).toBe('dates')
    expect(
      currentIntakeField(
        intake,
        form({ destination: 'Đà Nẵng', guests: 2, startDate: '2026-08-10', endDate: '2026-08-13' }),
      ),
    ).toBe('budget')
  })

  it('treats an end date earlier than start as not filled', () => {
    const intake = intakeWith(['start_date', 'duration'])
    const f = form({ destination: 'Đà Nẵng', startDate: '2026-08-13', endDate: '2026-08-10' })
    expect(currentIntakeField(intake, f)).toBe('dates')
  })

  it('surfaces optional budget once required fields are filled and options exist', () => {
    const intake = intakeWith([])
    const filled = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, filled)).toBe('budget')
  })

  it('skips budget when the backend offered no budget_options', () => {
    const intake = intakeWith([], { budget_options: [] })
    const filled = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b' })
    expect(currentIntakeField(intake, filled)).toBe('preferences')
  })

  it('surfaces preferences only after budget is answered', () => {
    const intake = intakeWith([])
    const f = form({ destination: 'Đà Nẵng', guests: 2, startDate: 'a', endDate: 'b', budget: 'X' })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('keeps preferences active once toggled — it is terminal, not a gate', () => {
    const intake = intakeWith([])
    const f = form({
      destination: 'Đà Nẵng',
      guests: 2,
      startDate: 'a',
      endDate: 'b',
      budget: 'X',
      preferences: ['amusement'],
    })
    expect(currentIntakeField(intake, f)).toBe('preferences')
  })

  it('keeps required fields in front of optional ones even when optional are pre-filled', () => {
    const intake = intakeWith(['destination'])
    const f = form({ budget: 'X', preferences: ['amusement'], startDate: 'a', endDate: 'b', guests: 2 })
    expect(currentIntakeField(intake, f)).toBe('destination')
  })
})

describe('INTAKE_FIELD_ORDER', () => {
  it('is the canonical widget order: destination → people → dates → budget → preferences', () => {
    const order: IntakeField[] = ['destination', 'people', 'dates', 'budget', 'preferences']
    expect([...INTAKE_FIELD_ORDER]).toEqual(order)
  })
})
