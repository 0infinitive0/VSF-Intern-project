import { describe, expect, it } from 'vitest'
import { decodePolyline } from './polyline'

describe('decodePolyline', () => {
  it('returns an empty array for empty/missing input', () => {
    expect(decodePolyline('')).toEqual([])
  })

  it('decodes the textbook Google Encoded Polyline example (precision 1e5)', () => {
    // https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    // — the canonical worked example: 3 points, hand-verified result.
    const points = decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@')
    expect(points).toHaveLength(3)
    expect(points[0].lat).toBeCloseTo(38.5, 5)
    expect(points[0].lng).toBeCloseTo(-120.2, 5)
    expect(points[1].lat).toBeCloseTo(40.7, 5)
    expect(points[1].lng).toBeCloseTo(-120.95, 5)
    expect(points[2].lat).toBeCloseTo(43.252, 5)
    expect(points[2].lng).toBeCloseTo(-126.453, 5)
  })

  it('decodes a real Mapbox-shaped fixture polyline into the Đà Nẵng area', () => {
    // Lifted verbatim from frontend/mock/server.js's day-1 item→item route
    // (hotel ~16.0544,108.2022 -> Bà Nà Hills ~16.0490,108.2493 leg).
    const points = decodePolyline('_s~`BwflsSvBgc@fO_q@vGo}@kC_jAjHseA')
    expect(points.length).toBeGreaterThan(1)
    for (const p of points) {
      expect(p.lat).toBeGreaterThan(15.5)
      expect(p.lat).toBeLessThan(16.5)
      expect(p.lng).toBeGreaterThan(107.5)
      expect(p.lng).toBeLessThan(108.8)
    }
  })

  it('does not throw on garbage input', () => {
    expect(() => decodePolyline('not a polyline !!! ')).not.toThrow()
  })
})
