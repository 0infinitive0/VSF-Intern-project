import { describe, expect, it } from 'vitest'
import { deriveStageView } from './derive-stage'
import type { ChatState } from '../types'

const BASE: ChatState = {
  sessionId: 's1',
  turnId: 0,
  messages: [],
  suggestions: [],
  hotelOptions: [],
  hotelFilterData: { minPrice: null, maxPrice: null, hotelAmenities: [], allPreferences: [], activePreferences: [] },
  suggestedPlaces: [],
  tripPlan: null,
  intake: null,
  pending: false,
  hotelsLoading: false,
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

  it('stays on intake while pending if the required intake fields are not all answered', () => {
    // Answering one more intake question must not swap the checklist the user
    // is filling in for a full-panel progress view.
    expect(deriveStageView({ ...BASE, pending: true }, false)).toBe('intake')
  })

  it('is generating while pending once the required intake fields are answered', () => {
    expect(deriveStageView({ ...BASE, pending: true }, true)).toBe('generating')
  })

  it('is generating while pending as soon as the backend reports heavy work, even with an unfilled form', () => {
    // The free-text path: everything typed in one message, so the local form
    // is empty — the real `phases` are what say the search actually started.
    expect(
      deriveStageView({ ...BASE, pending: true, phases: [{ key: 'hotel_search', at: 0 }] }, false),
    ).toBe('generating')
  })

  it('ignores phases that are not the heavy work', () => {
    expect(
      deriveStageView({ ...BASE, pending: true, phases: [{ key: 'intake_check', at: 0 }] }, false),
    ).toBe('intake')
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

  // A turn that didn't re-run the hotel search (a qa_node answer, a hotel
  // selection) legitimately comes back with no hotel_options at all. Without
  // the retained flag every branch fell through to 'intake', so asking a
  // question about the hotels on screen threw the user back to step 1 and
  // took the hotel list with it.
  it('stays on hotels when this turn carried no options but the session already found some', () => {
    expect(deriveStageView(BASE, true, true)).toBe('hotels')
  })

  it('still reaches intake when no hotels have ever been found', () => {
    expect(deriveStageView(BASE, true, false)).toBe('intake')
  })

  it('prefers workspace over retained hotels once a trip plan exists', () => {
    // The step navigator's client-side override is how the user revisits
    // hotel picking from here — the derived stage must not pin them to it.
    expect(deriveStageView({ ...BASE, tripPlan: SOME_TRIP_PLAN }, true, true)).toBe('workspace')
  })
})
