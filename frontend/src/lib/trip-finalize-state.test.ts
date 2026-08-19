import { describe, expect, it } from 'vitest'
import { finalizeBlockedReason, isTripFinalized } from './trip-finalize-state'
import type { TripPlan } from '../types'

const BASE_TRIP_PLAN: TripPlan = {
  status: 'Draft',
  destination: 'Đà Nẵng',
  duration_days: 3,
  start_date: null,
  end_date: null,
  number_of_adults: 2,
  budget: null,
  budget_currency: 'VND',
  hotel: null,
  days: [],
  adjustments: [],
}

describe('isTripFinalized', () => {
  it('is false for null', () => {
    expect(isTripFinalized(null)).toBe(false)
  })

  it('is false for a draft', () => {
    expect(isTripFinalized(BASE_TRIP_PLAN)).toBe(false)
  })

  it('is true for the backend\'s exact "Finalized" casing', () => {
    expect(isTripFinalized({ ...BASE_TRIP_PLAN, status: 'Finalized' })).toBe(true)
  })

  it('is case-insensitive', () => {
    expect(isTripFinalized({ ...BASE_TRIP_PLAN, status: 'finalized' })).toBe(true)
    expect(isTripFinalized({ ...BASE_TRIP_PLAN, status: 'FINALIZED' })).toBe(true)
  })
})

describe('finalizeBlockedReason', () => {
  const paid = { sessionBookedFromBackend: true, pending: false }

  it('is no-plan when there is nothing to finalize yet', () => {
    expect(finalizeBlockedReason({ tripPlan: null, ...paid })).toBe('no-plan')
  })

  it('is already-final once the trip is finalized, even if somehow reported unpaid', () => {
    // Should never happen in practice (payment is required first) — the
    // precedence itself is what's under test here, not the scenario.
    expect(
      finalizeBlockedReason({
        tripPlan: { ...BASE_TRIP_PLAN, status: 'Finalized' },
        sessionBookedFromBackend: false,
        pending: false,
      }),
    ).toBe('already-final')
  })

  it('is not-paid for a draft trip with no confirmed booking', () => {
    expect(
      finalizeBlockedReason({ tripPlan: BASE_TRIP_PLAN, sessionBookedFromBackend: false, pending: false }),
    ).toBe('not-paid')
  })

  it('is busy while a request is already in flight', () => {
    expect(finalizeBlockedReason({ tripPlan: BASE_TRIP_PLAN, ...paid, pending: true })).toBe('busy')
  })

  it('is null (enabled) for a paid draft with nothing in flight', () => {
    expect(finalizeBlockedReason({ tripPlan: BASE_TRIP_PLAN, ...paid })).toBe(null)
  })
})
