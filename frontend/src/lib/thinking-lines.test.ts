import { describe, expect, it } from 'vitest'
import { thinkingLines, type Translate } from './thinking-lines'
import en from '../i18n/locales/en.json'
import vi from '../i18n/locales/vi.json'

/** Renders `key(param=value, …)` so a test can assert on both halves. */
const t: Translate = (key, params) => {
  const args = params
    ? Object.entries(params)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(',')
    : ''
  return args ? `${key}(${args})` : key
}

describe('intake_check', () => {
  it('names the intent and the fields the message touched', () => {
    const lines = thinkingLines(t, 'intake_check', {
      intent: 'update_trip',
      fields: ['people', 'budget.target'],
    })

    expect(lines).toEqual([
      'thinkingIntakeIntent(intent=thinkingIntentUpdateTrip)',
      'thinkingIntakeFields(fields=thinkingFieldPeople, thinkingFieldBudget)',
    ])
  })

  it('drops only the missing half when one fact is absent', () => {
    expect(thinkingLines(t, 'intake_check', { intent: 'update_trip' })).toEqual([
      'thinkingIntakeIntent(intent=thinkingIntentUpdateTrip)',
    ])
    expect(thinkingLines(t, 'intake_check', { fields: ['people'] })).toEqual([
      'thinkingIntakeFields(fields=thinkingFieldPeople)',
    ])
  })

  it('never renders a raw field path the frontend has no label for', () => {
    const lines = thinkingLines(t, 'intake_check', {
      fields: ['people', 'some.future.field'],
    })

    expect(lines.join(' ')).not.toContain('some.future.field')
    expect(lines).toEqual(['thinkingIntakeFields(fields=thinkingFieldPeople)'])
  })

  it('produces nothing when every field path is unknown', () => {
    expect(thinkingLines(t, 'intake_check', { fields: ['a.b'] })).toEqual([])
  })
})

describe('routing', () => {
  it('names the worker', () => {
    expect(thinkingLines(t, 'routing', { worker: 'hotel_node' })).toEqual([
      'thinkingRoutingWorker(worker=thinkingWorkerHotel)',
    ])
  })

  it('says nothing about a worker it does not know', () => {
    expect(thinkingLines(t, 'routing', { worker: 'future_node' })).toEqual([])
  })
})

describe('hotel_search', () => {
  it('includes the radius only when the user set one', () => {
    expect(thinkingLines(t, 'hotel_search', { destination: 'Đà Nẵng', radius_km: 5 })).toEqual([
      'thinkingHotelSearchRadius(destination=Đà Nẵng,radius=5)',
    ])
    expect(thinkingLines(t, 'hotel_search', { destination: 'Đà Nẵng' })).toEqual([
      'thinkingHotelSearchWhere(destination=Đà Nẵng)',
    ])
  })

  it('never interpolates undefined into a sentence', () => {
    const lines = thinkingLines(t, 'hotel_search', { destination: 'Huế', kept: 3 })

    expect(lines.join(' ')).not.toContain('undefined')
  })

  it('reports the count kept on a successful search', () => {
    const lines = thinkingLines(t, 'hotel_search', {
      status: 'ok',
      destination: 'Đà Nẵng',
      kept: 8,
    })

    expect(lines).toContain('thinkingHotelKept(count=8)')
  })

  it('says the search came back empty rather than reporting zero kept', () => {
    const lines = thinkingLines(t, 'hotel_search', {
      status: 'no_results',
      destination: 'Đà Nẵng',
      kept: 0,
    })

    expect(lines).toContain('thinkingHotelNoResults')
    expect(lines.join(' ')).not.toContain('thinkingHotelKept')
  })

  it('distinguishes a failed search from an empty one', () => {
    expect(thinkingLines(t, 'hotel_search', { status: 'error' })).toEqual(['thinkingHotelError'])
  })

  it('counts the amenities the user required', () => {
    const lines = thinkingLines(t, 'hotel_search', {
      destination: 'Hội An',
      amenities: ['pool', 'breakfast'],
    })

    expect(lines).toContain('thinkingHotelAmenities(count=2)')
  })
})

describe('routing_legs', () => {
  it('reports the day count', () => {
    expect(thinkingLines(t, 'routing_legs', { days: 4 })).toEqual([
      'thinkingRoutingLegs(days=4)',
    ])
  })
})

describe('when there is nothing to say', () => {
  it('returns no lines for empty facts — not a placeholder sentence', () => {
    for (const key of ['intake_check', 'routing', 'hotel_search', 'routing_legs']) {
      expect(thinkingLines(t, key, {}), `${key} invented a line`).toEqual([])
    }
  })

  it('returns no lines for a phase key that carries no facts at all', () => {
    for (const key of ['compacting_history', 'generating', 'persisting', 'received']) {
      expect(thinkingLines(t, key, {})).toEqual([])
    }
  })

  it('ignores facts it has no sentence for', () => {
    expect(thinkingLines(t, 'routing', { kept: 5, days: 2 } as never)).toEqual([])
  })

  it('defaults facts to empty when the frame carried none', () => {
    expect(thinkingLines(t, 'hotel_search')).toEqual([])
  })
})

describe('translations', () => {
  const usedKeys = (): string[] => {
    const collected = new Set<string>()
    const spy: Translate = (key) => {
      collected.add(key)
      return key
    }
    thinkingLines(spy, 'intake_check', {
      intent: 'update_trip',
      fields: ['destination', 'people', 'dates.start', 'dates.end', 'budget.target', 'preferences'],
    })
    thinkingLines(spy, 'intake_check', { intent: 'general_question' })
    thinkingLines(spy, 'intake_check', { intent: 'rebuild_days' })
    for (const worker of ['hotel_node', 'itinerary_node', 'booking_node', 'qa_node', 'respond']) {
      thinkingLines(spy, 'routing', { worker })
    }
    thinkingLines(spy, 'hotel_search', { destination: 'x', radius_km: 1, amenities: ['a'], kept: 1 })
    for (const status of [
      'no_results', 'no_results_dates', 'no_results_amenities', 'no_results_rating', 'error',
    ]) {
      thinkingLines(spy, 'hotel_search', { status })
    }
    thinkingLines(spy, 'routing_legs', { days: 1 })
    return [...collected]
  }

  it('has every key it can emit in both locales', () => {
    for (const key of usedKeys()) {
      expect(vi, `vi is missing ${key}`).toHaveProperty(key)
      expect(en, `en is missing ${key}`).toHaveProperty(key)
    }
  })
})
