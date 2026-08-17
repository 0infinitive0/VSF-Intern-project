import { describe, expect, it } from 'vitest'
import { EMPTY_INTAKE_FORM, mergeIntakeIntoForm } from './use-intake-form'
import type { IntakeStatus } from '../types'
import { intakeStatus } from '../test-fixtures'

const BASE_INTAKE: IntakeStatus = intakeStatus({
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
})

function intake(overrides: Partial<IntakeStatus> = {}): IntakeStatus {
  return { ...BASE_INTAKE, ...overrides }
}

const KNOWN_TRIP = intake({
  destination: 'Đà Nẵng',
  people: '2 người',
  start_date: '2026-08-10',
  end_date: '2026-08-13',
  duration: '4 ngày',
})

describe('mergeIntakeIntoForm', () => {
  it('seeds empty local fields from the server snapshot', () => {
    const merged = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, KNOWN_TRIP, null, null)
    expect(merged.destination).toBe('Đà Nẵng')
    expect(merged.guests).toBe(2)
    expect(merged.startDate).toBe('2026-08-10')
    expect(merged.endDate).toBe('2026-08-13')
  })

  // The distinction the old `intake.start_date || prev.startDate` merge could
  // not make: a slot that has ALWAYS been null is a field the user answered in
  // the widget and hasn't sent yet — keeping it is the whole point of
  // progressive disclosure.
  it('keeps a local answer the server has never been told about', () => {
    const local = { ...EMPTY_INTAKE_FORM, destination: 'Huế', guests: 3 }
    const merged = mergeIntakeIntoForm(local, intake(), intake(), null)
    expect(merged.destination).toBe('Huế')
    expect(merged.guests).toBe(3)
  })

  it('drops the local answer for a slot the server just cleared', () => {
    const local = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, KNOWN_TRIP, null, null)
    const datesReopened = intake({
      destination: 'Đà Nẵng',
      people: '2 người',
      missing: ['start_date', 'duration'],
    })

    const merged = mergeIntakeIntoForm(local, datesReopened, KNOWN_TRIP, null)

    expect(merged.startDate).toBe('')
    expect(merged.endDate).toBe('')
    // Only that field — everything else the server still knows survives.
    expect(merged.destination).toBe('Đà Nẵng')
    expect(merged.guests).toBe(2)
  })

  it('leaves an in-progress edit alone even when the server clears that slot', () => {
    const local = { ...EMPTY_INTAKE_FORM, startDate: '2026-09-01', endDate: '2026-09-05' }
    const datesReopened = intake({ destination: 'Đà Nẵng', missing: ['start_date', 'duration'] })

    const merged = mergeIntakeIntoForm(local, datesReopened, KNOWN_TRIP, 'dates')

    expect(merged.startDate).toBe('2026-09-01')
    expect(merged.endDate).toBe('2026-09-05')
  })

  it('clears a cleared destination without touching an unrelated in-progress edit', () => {
    const local = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, KNOWN_TRIP, null, null)
    const destinationReopened = intake({
      people: '2 người',
      start_date: '2026-08-10',
      end_date: '2026-08-13',
      duration: '4 ngày',
      missing: ['destination'],
    })

    const merged = mergeIntakeIntoForm(local, destinationReopened, KNOWN_TRIP, 'dates')

    expect(merged.destination).toBe('')
    expect(merged.startDate).toBe('2026-08-10')
  })

  it('clears budget answers the server dropped, and keeps ones it never had', () => {
    const withBudget = intake({ min_price: 800_000, max_price: 2_500_000 })
    const seeded = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, withBudget, null, null)
    expect(seeded.budgetMinVnd).toBe(800_000)

    const dropped = mergeIntakeIntoForm(seeded, intake(), withBudget, null)
    expect(dropped.budgetMinVnd).toBeNull()
    expect(dropped.budgetMaxVnd).toBeNull()

    const localOnly = { ...EMPTY_INTAKE_FORM, budgetMinVnd: 500_000, budgetMaxVnd: 900_000 }
    const kept = mergeIntakeIntoForm(localOnly, intake(), intake(), null)
    expect(kept.budgetMinVnd).toBe(500_000)
  })

  it('clears preferences the server dropped', () => {
    const withThemes = intake({ preferences: ['Vui chơi giải trí'] })
    const seeded = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, withThemes, null, null)
    expect(seeded.preferences.length).toBe(1)

    const dropped = mergeIntakeIntoForm(seeded, intake(), withThemes, null)
    expect(dropped.preferences).toEqual([])
  })

  it('is idempotent when the same snapshot arrives twice', () => {
    const once = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, KNOWN_TRIP, null, null)
    const twice = mergeIntakeIntoForm(once, KNOWN_TRIP, KNOWN_TRIP, null)
    expect(twice).toEqual(once)
  })
})
