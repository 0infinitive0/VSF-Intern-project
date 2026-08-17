import { describe, expect, it } from 'vitest'
import { highlightedRouteKeys, hotelMapFields, hotelMapRays } from './map-presentation'
import type { RouteSegment } from './route-segments'
import { hotelDetail, hotelOption } from '../test-fixtures'

const SEGMENTS = [
  { segKey: 'a', fromKey: 'hotel', toKey: 'place-1' },
  { segKey: 'b', fromKey: 'place-1', toKey: 'place-2' },
  { segKey: 'c', fromKey: 'place-2', toKey: 'hotel' },
] as RouteSegment[]

describe('hotelMapFields', () => {
  it('uses only real price and match data', () => {
    expect(hotelMapFields(hotelOption({ index: 1, name: 'A', average_nightly_price: 1_250_000, match_score: 0.875 }), 'vi')).toEqual({
      priceLabel: '1.250.000 ₫',
      matchLabel: '88%',
    })
    expect(hotelMapFields(hotelOption({ index: 2, name: 'B' }), 'vi')).toEqual({ priceLabel: undefined, matchLabel: undefined })
  })
})

describe('hotelMapRays', () => {
  it('keeps only nearby attractions with valid map data', () => {
    expect(hotelMapRays(hotelDetail({
      nearby_attractions: [
        { name: 'Cầu Rồng', category: null, coordinates: '16.061,108.227', distance_km: 1.2, distance_text: null },
        { name: 'No coordinate', category: null, coordinates: null, distance_km: 2, distance_text: null },
        { name: 'No distance', category: null, coordinates: '16.06,108.22', distance_km: null, distance_text: null },
      ],
    }))).toEqual([{ name: 'Cầu Rồng', coordinates: { lat: 16.061, lng: 108.227 }, distanceKm: 1.2 }])
  })
})

describe('highlightedRouteKeys', () => {
  it('highlights the adjacent route for a timeline or marker hover', () => {
    expect([...highlightedRouteKeys(SEGMENTS, 'place-1', null)]).toEqual(['a', 'b'])
  })

  it('uses exactly the legend pill route when one is hovered', () => {
    expect([...highlightedRouteKeys(SEGMENTS, 'place-1', 'c')]).toEqual(['c'])
  })

  // map_implementation_spec.md §2 "Double-Leg Highlight": activating ONE
  // place must light the leg arriving at it AND the leg leaving it, while
  // every leg further down the chain stays unlit (the map dims those). A
  // 4-place chain is the smallest fixture where "leaves the rest out" is a
  // real assertion rather than a side effect of the chain being too short.
  it('lights both the arriving and the departing leg of one place, and nothing beyond them', () => {
    const chain = [
      { segKey: 'h1', fromKey: 'hotel', toKey: 'place-1' },
      { segKey: 's12', fromKey: 'place-1', toKey: 'place-2' },
      { segKey: 's23', fromKey: 'place-2', toKey: 'place-3' },
      { segKey: 's3h', fromKey: 'place-3', toKey: 'hotel' },
    ] as RouteSegment[]
    expect([...highlightedRouteKeys(chain, 'place-2', null)]).toEqual(['s12', 's23'])
  })

  it('lights the single adjacent leg when a place sits at the end of the chain', () => {
    expect([...highlightedRouteKeys(SEGMENTS, 'place-2', null)]).toEqual(['b', 'c'])
    expect([...highlightedRouteKeys(SEGMENTS, 'unknown-place', null)]).toEqual([])
  })
})
