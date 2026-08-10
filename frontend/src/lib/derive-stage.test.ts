import { describe, expect, it } from 'vitest'
import { deriveStageView } from './derive-stage'
import type { ChatState } from '../types'

const BASE: ChatState = {
  sessionId: 's1',
  turnId: 0,
  messages: [],
  suggestions: [],
  hotelOptions: [],
  tripPlan: null,
  intake: null,
  pending: false,
  elapsedMs: 0,
  error: null,
  streamingText: '',
  phases: [],
}

const SOME_TRIP_PLAN: ChatState['tripPlan'] = {
  status: 'Draft',
  destination: 'Đà Nẵng',
  duration_days: 3,
  start_date: null,
  end_date: null,
  number_of_adults: 2,
  hotel: null,
  days: [],
  adjustments: [],
}

const SOME_HOTEL_OPTIONS: ChatState['hotelOptions'] = [{ index: 1, name: 'Hotel A' }]

describe('deriveStageView', () => {
  it('defaults to intake when nothing has happened yet', () => {
    expect(deriveStageView(BASE)).toBe('intake')
  })

  it('is generating while pending and nothing to render yet', () => {
    expect(deriveStageView({ ...BASE, pending: true })).toBe('generating')
  })

  it('is not generating once hotel options exist, even while pending (a follow-up turn)', () => {
    expect(deriveStageView({ ...BASE, pending: true, hotelOptions: SOME_HOTEL_OPTIONS })).toBe('hotels')
  })

  it('is not generating once a trip plan exists, even while pending (a follow-up turn)', () => {
    expect(deriveStageView({ ...BASE, pending: true, tripPlan: SOME_TRIP_PLAN })).toBe('workspace')
  })

  it('is hotels when hotel options are present', () => {
    expect(deriveStageView({ ...BASE, hotelOptions: SOME_HOTEL_OPTIONS })).toBe('hotels')
  })

  it('prioritizes hotels over workspace when both are present — user can revisit hotel picking', () => {
    expect(
      deriveStageView({ ...BASE, hotelOptions: SOME_HOTEL_OPTIONS, tripPlan: SOME_TRIP_PLAN }),
    ).toBe('hotels')
  })

  it('is workspace once a trip plan exists and there are no hotel options in flight', () => {
    expect(deriveStageView({ ...BASE, tripPlan: SOME_TRIP_PLAN })).toBe('workspace')
  })
})
