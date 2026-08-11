import { describe, expect, it } from 'vitest'
import { highlightedRouteKeys, hotelMapFields, hotelMapRays } from './map-presentation'
import type { RouteSegment } from './route-segments'

const SEGMENTS = [
  { segKey: 'a', fromKey: 'hotel', toKey: 'place-1' },
  { segKey: 'b', fromKey: 'place-1', toKey: 'place-2' },
  { segKey: 'c', fromKey: 'place-2', toKey: 'hotel' },
] as RouteSegment[]

describe('hotelMapFields', () => {
  it('uses only real price and match data', () => {
    expect(hotelMapFields({ index: 1, name: 'A', average_nightly_price: 1_250_000, match_score: 0.875 }, 'vi')).toEqual({
      priceLabel: '1.250.000 ₫',
      matchLabel: '88%',
    })
    expect(hotelMapFields({ index: 2, name: 'B' }, 'vi')).toEqual({ priceLabel: undefined, matchLabel: undefined })
  })
})

describe('hotelMapRays', () => {
  it('keeps only nearby attractions with valid map data', () => {
    expect(hotelMapRays({
      nearby_attractions: [
        { name: 'Cầu Rồng', coordinates: '16.061,108.227', distance_km: 1.2 },
        { name: 'No coordinate', distance_km: 2 },
        { name: 'No distance', coordinates: '16.06,108.22' },
      ],
    })).toEqual([{ name: 'Cầu Rồng', coordinates: { lat: 16.061, lng: 108.227 }, distanceKm: 1.2 }])
  })
})

describe('highlightedRouteKeys', () => {
  it('highlights the adjacent route for a timeline or marker hover', () => {
    expect([...highlightedRouteKeys(SEGMENTS, 'place-1', null)]).toEqual(['a', 'b'])
  })

  it('uses exactly the legend pill route when one is hovered', () => {
    expect([...highlightedRouteKeys(SEGMENTS, 'place-1', 'c')]).toEqual(['c'])
  })
})
