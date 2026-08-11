import { describe, expect, it } from 'vitest'
import { buildDaySegments, buildTripSegments } from './route-segments'
import type { Day } from '../types'

const HOTEL = { coordinates: '16.0544,108.2022' }

// Lifted verbatim from frontend/mock/server.js's TRIP_PLAN.days[0] — covers
// every route_to_next/route_from_hotel state on real Đà Nẵng coordinates:
// same-place hotel leg, a real driving-traffic leg, a real walking leg, a
// null (routing-failed) leg, and the last-item-back-to-hotel return leg.
const DAY_1: Day = {
  day_number: 1,
  theme: 'Khám phá bãi biển Mỹ Khê',
  items: [
    {
      order_index: 1, start_time: '08:00', end_time: '09:30', activity: 'Ăn sáng tại nhà hàng khách sạn', kind: 'breakfast',
      coordinates: '16.0544,108.2022',
      route_from_hotel: { distance_km: 0, duration_mins: 0, polyline: '', profile: null },
      route_to_next: { distance_km: 5.8, duration_mins: 13.4, polyline: '_s~`BwflsSvBgc@fO_q@vGo}@kC_jAjHseA', profile: 'driving-traffic' },
    },
    {
      order_index: 2, start_time: '10:00', end_time: '12:00', activity: 'Tắm biển Mỹ Khê', kind: 'attraction',
      reference_type: 'Attraction', reference_id: 'attraction-my-khe',
      coordinates: '16.0490,108.2493',
      route_to_next: { distance_km: 1.9, duration_mins: 22.0, polyline: 'gq}`BcmusSwLjqB', profile: 'walking' },
    },
    {
      order_index: 3, start_time: '12:30', end_time: '13:30', activity: 'Ăn trưa hải sản tươi Bến Thành Đà Nẵng', kind: 'lunch',
      coordinates: '16.0512,108.2310',
      route_to_next: null,
    },
    {
      order_index: 4, start_time: '15:00', end_time: '17:30', activity: 'Tham quan Bảo tàng Điêu khắc Chăm', kind: 'attraction',
      coordinates: '16.0678,108.2208',
      route_to_next: { distance_km: 2.6, duration_mins: 7.5, polyline: 'wfaaB_{osSfJwLrNoKrN{O', profile: 'driving-traffic' },
    },
    {
      order_index: 5, start_time: '19:00', end_time: '21:00', activity: 'Dạo cầu Rồng, ngắm phun lửa cuối tuần', kind: 'evening',
      coordinates: '16.0610,108.2277',
      route_to_next: { distance_km: 6.1, duration_mins: 15.8, polyline: 'g|_aBcfqsSnKbo@nK~p@jHnd@zEvV', profile: 'driving-traffic' },
    },
  ],
}

// Day 3 in the same fixture: no route_to_next anywhere, route_from_hotel
// explicitly null on the first item — every leg must fall back to a straight
// line, none of them may be silently dropped.
const DAY_3_ALL_FALLBACK: Day = {
  day_number: 3,
  theme: 'Bà Nà Hills & chia tay',
  items: [
    { order_index: 1, start_time: '08:00', end_time: '09:00', activity: 'Ăn sáng, trả phòng', kind: 'breakfast',
      coordinates: '16.0544,108.2022', route_from_hotel: null },
    { order_index: 2, start_time: '09:30', end_time: '15:30', activity: 'Cáp treo Bà Nà Hills', kind: 'attraction',
      reference_type: 'Attraction', reference_id: 'attraction-ba-na', coordinates: '15.9977,107.9967' },
    { order_index: 3, start_time: '16:00', end_time: '17:00', activity: 'Mua quà lưu niệm', kind: 'attraction',
      coordinates: '16.0678,108.2245' },
    { order_index: 4, start_time: '18:00', end_time: '19:30', activity: 'Ăn tối chia tay', kind: 'dinner',
      coordinates: '16.0600,108.2260' },
  ],
}

describe('buildDaySegments', () => {
  it('skips the hotel->item[0] segment for the same-place marker, builds the rest', () => {
    const segments = buildDaySegments(DAY_1, HOTEL)
    // legIndex 0 (hotel->item0) is skipped: same-place. legIndex 1-4 between
    // items, legIndex 5 is the last-item->hotel return. 5 segments total.
    expect(segments.map((s) => s.legIndex)).toEqual([1, 2, 3, 4, 5])
    expect(segments.every((s) => s.dayNumber === 1)).toBe(true)
  })

  it('marks a real polyline leg as non-fallback with its profile', () => {
    const segments = buildDaySegments(DAY_1, HOTEL)
    const leg1 = segments.find((s) => s.legIndex === 1)! // item0 -> item1, driving-traffic
    expect(leg1.isFallback).toBe(false)
    expect(leg1.profile).toBe('driving-traffic')
    expect(leg1.points.length).toBeGreaterThan(1)
    expect(leg1.fromKey).toBe('day-1-item-0')
    expect(leg1.toKey).toBe('attraction-my-khe') // real reference_id, not a synthetic key
    // Real metrics carried straight from route_to_next — never recomputed.
    expect(leg1.distanceKm).toBe(5.8)
    expect(leg1.durationMins).toBe(13.4)

    const leg2 = segments.find((s) => s.legIndex === 2)! // item1 -> item2, walking
    expect(leg2.isFallback).toBe(false)
    expect(leg2.profile).toBe('walking')
    expect(leg2.distanceKm).toBe(1.9)
    expect(leg2.durationMins).toBe(22.0)
  })

  it('falls back to a straight 2-point line when route_to_next is null, with no invented duration', () => {
    const segments = buildDaySegments(DAY_1, HOTEL)
    const leg3 = segments.find((s) => s.legIndex === 3)! // item2 -> item3, route_to_next: null
    expect(leg3.isFallback).toBe(true)
    expect(leg3.points).toHaveLength(2)
    expect(leg3.profile).toBeNull()
    // crow-fly: distanceKm is a real haversine figure, durationMins is null —
    // never guessed from a straight-line distance (mirrors leg.ts's Leg
    // 'crow-fly' variant, which also has no durationMins field at all).
    expect(leg3.durationMins).toBeNull()
    expect(leg3.distanceKm).toBeGreaterThan(0)
  })

  it('builds the last-item -> hotel return segment from the last item\'s route_to_next', () => {
    const segments = buildDaySegments(DAY_1, HOTEL)
    const returnLeg = segments.find((s) => s.legIndex === 5)!
    expect(returnLeg.isFallback).toBe(false)
    expect(returnLeg.profile).toBe('driving-traffic')
    expect(returnLeg.toKey).toBe('hotel')
  })

  it('produces an all-fallback day when no route data exists anywhere, without dropping any leg', () => {
    const segments = buildDaySegments(DAY_3_ALL_FALLBACK, HOTEL)
    // hotel->item0 (route_from_hotel: null, not same-place) + 3 between-item
    // legs + return leg = 5 segments, all fallback straight lines.
    expect(segments).toHaveLength(5)
    expect(segments.every((s) => s.isFallback)).toBe(true)
    expect(segments.every((s) => s.points.length === 2)).toBe(true)
    // route was null (not just polyline-less) for every one of these, so
    // durationMins is null across the board too.
    expect(segments.every((s) => s.durationMins === null)).toBe(true)
  })

  it('keeps real distance/duration on a fallback segment whose polyline failed to decode (isFallback is about geometry, not metrics)', () => {
    const day: Day = {
      day_number: 1,
      theme: 't',
      items: [
        {
          order_index: 1, start_time: null, end_time: null, activity: 'a', coordinates: '16.0544,108.2022',
          // A real route exists (distance/duration/profile), but the polyline
          // string decodes to a single point (verified directly against
          // decodePolyline — '!' is one minimal-varint pair) — pointsFor()
          // must fall back to a straight line (isFallback: true) while
          // metricsFor() still carries the real numbers through untouched.
          route_to_next: { distance_km: 3.3, duration_mins: 9.1, polyline: '!', profile: 'driving-traffic' },
        },
        { order_index: 2, start_time: null, end_time: null, activity: 'b', coordinates: '16.0678,108.2208' },
      ],
    }
    const segments = buildDaySegments(day, null)
    expect(segments).toHaveLength(1)
    expect(segments[0].isFallback).toBe(true)
    expect(segments[0].points).toHaveLength(2)
    expect(segments[0].distanceKm).toBe(3.3)
    expect(segments[0].durationMins).toBe(9.1)
  })

  it('never bridges across an item with unparseable/missing coordinates', () => {
    const day: Day = {
      day_number: 1,
      theme: 't',
      items: [
        { order_index: 1, start_time: null, end_time: null, activity: 'a', coordinates: '16.05,108.20' },
        { order_index: 2, start_time: null, end_time: null, activity: 'b', coordinates: null }, // gap
        { order_index: 3, start_time: null, end_time: null, activity: 'c', coordinates: '16.06,108.22' },
      ],
    }
    const segments = buildDaySegments(day, null)
    // No leg connects item0 directly to item2 — the gap is real, not bridged.
    expect(segments.some((s) => s.fromKey === 'day-1-item-0' && s.toKey === 'day-1-item-2')).toBe(false)
    expect(segments).toHaveLength(0) // both legs touching item1 are dropped; no hotel to anchor either end
  })

  it('produces no segments for a day with fewer than 2 parseable points', () => {
    const day: Day = {
      day_number: 1,
      theme: 't',
      items: [{ order_index: 1, start_time: null, end_time: null, activity: 'a', coordinates: null }],
    }
    expect(buildDaySegments(day, null)).toHaveLength(0)
  })

  it('drops the hotel-anchored segments entirely when the hotel has no parseable coordinates', () => {
    const segments = buildDaySegments(DAY_1, { coordinates: null })
    expect(segments.some((s) => s.fromKey === 'hotel' || s.toKey === 'hotel')).toBe(false)
  })
})

describe('buildTripSegments', () => {
  it('flat-maps every day, keeping segKey unique across days', () => {
    const segments = buildTripSegments([DAY_1, DAY_3_ALL_FALLBACK], HOTEL)
    const keys = segments.map((s) => s.segKey)
    expect(new Set(keys).size).toBe(keys.length)
    expect(segments.some((s) => s.dayNumber === 1)).toBe(true)
    expect(segments.some((s) => s.dayNumber === 3)).toBe(true)
  })
})
