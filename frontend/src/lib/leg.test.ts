import { describe, expect, it } from 'vitest'
import { dayRouteMetrics, legBetween, tripRouteMetrics } from './leg'
import type { DayItem } from '../types'

function item(overrides: Partial<DayItem>): DayItem {
  return {
    order_index: 1,
    start_time: null,
    end_time: null,
    activity: 'x',
    ...overrides,
  }
}

describe('legBetween — the four-state contract', () => {
  it('is "none" when there is no next item', () => {
    expect(legBetween(item({}), null)).toEqual({ kind: 'none' })
    expect(legBetween(item({}), undefined)).toEqual({ kind: 'none' })
  })

  it('is "route" with vehicle + distance + duration for a real route_to_next', () => {
    const a = item({ route_to_next: { distance_km: 5.8, duration_mins: 13.4, polyline: 'abc', profile: 'driving-traffic' } })
    const b = item({})
    expect(legBetween(a, b)).toEqual({
      kind: 'route',
      distanceKm: 5.8,
      durationMins: 13.4,
      profile: 'driving-traffic',
    })
  })

  it('is "same-place" for the identical-coordinates marker {0,0,"",null} — never a "0 km" route', () => {
    const a = item({ route_to_next: { distance_km: 0, duration_mins: 0, polyline: '', profile: null } })
    const b = item({})
    expect(legBetween(a, b)).toEqual({ kind: 'same-place' })
  })

  it('is "crow-fly" (distance only) when route_to_next is null but both coordinates parse', () => {
    const a = item({ coordinates: '16.0512,108.2310', route_to_next: null })
    const b = item({ coordinates: '16.0678,108.2208' })
    const leg = legBetween(a, b)
    expect(leg.kind).toBe('crow-fly')
    if (leg.kind === 'crow-fly') {
      expect(leg.distanceKm).toBeGreaterThan(0)
    }
  })

  it('is "none" when route_to_next is null and coordinates are missing/unparseable', () => {
    expect(legBetween(item({ route_to_next: null }), item({}))).toEqual({ kind: 'none' })
    expect(
      legBetween(item({ coordinates: 'garbage', route_to_next: null }), item({ coordinates: '16.05,108.2' })),
    ).toEqual({ kind: 'none' })
  })

  it('does not treat a real zero-distance route (non-empty polyline) as same-place', () => {
    const a = item({ route_to_next: { distance_km: 0, duration_mins: 0, polyline: 'realpolyline', profile: 'walking' } })
    expect(legBetween(a, item({}))).toEqual({
      kind: 'route',
      distanceKm: 0,
      durationMins: 0,
      profile: 'walking',
    })
  })
})

describe('dayRouteMetrics / tripRouteMetrics', () => {
  it('sums real routes without marking the total approximate', () => {
    const items = [
      item({ route_to_next: { distance_km: 5, duration_mins: 10, polyline: 'a', profile: 'driving-traffic' } }),
      item({ route_to_next: { distance_km: 3, duration_mins: 6, polyline: 'b', profile: 'walking' } }),
      item({}),
    ]
    expect(dayRouteMetrics(items)).toEqual({ distanceKm: 8, durationMins: 16, approximate: false })
  })

  it('marks the total approximate when any leg falls back to crow-fly, and omits its duration', () => {
    const items = [
      item({ coordinates: '16.0512,108.2310', route_to_next: null }),
      item({ coordinates: '16.0678,108.2208' }),
    ]
    const m = dayRouteMetrics(items)
    expect(m.approximate).toBe(true)
    expect(m.durationMins).toBe(0)
    expect(m.distanceKm).toBeGreaterThan(0)
  })

  it('ignores same-place and none legs entirely (no distance, no duration)', () => {
    const items = [
      item({ route_to_next: { distance_km: 0, duration_mins: 0, polyline: '', profile: null } }),
      item({ route_to_next: null }),
    ]
    expect(dayRouteMetrics(items)).toEqual({ distanceKm: 0, durationMins: 0, approximate: false })
  })

  it('tripRouteMetrics sums across days and propagates the approximate flag', () => {
    const dayReal = {
      items: [item({ route_to_next: { distance_km: 5, duration_mins: 10, polyline: 'a', profile: 'driving-traffic' } }), item({})],
    }
    const dayFallback = {
      items: [item({ coordinates: '16.0512,108.2310', route_to_next: null }), item({ coordinates: '16.0678,108.2208' })],
    }
    const m = tripRouteMetrics([dayReal, dayFallback])
    expect(m.approximate).toBe(true)
    expect(m.distanceKm).toBeGreaterThan(5)
    expect(m.durationMins).toBe(10)
  })
})
