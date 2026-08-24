import { describe, expect, it } from 'vitest'
import { bearingDegrees, boundsOf, haversineKm, parseCoordinates, pointsAlongPolyline, toLngLat } from './geo'

describe('parseCoordinates', () => {
  it('parses "lat,lng" (the real backend format)', () => {
    expect(parseCoordinates('16.0544,108.2022')).toEqual({ lat: 16.0544, lng: 108.2022 })
  })

  it('tolerates surrounding whitespace', () => {
    expect(parseCoordinates(' 16.0544, 108.2022 ')).toEqual({ lat: 16.0544, lng: 108.2022 })
  })

  it('parses WKT POINT(lng lat) defensively', () => {
    expect(parseCoordinates('POINT(108.2022 16.0544)')).toEqual({ lat: 16.0544, lng: 108.2022 })
  })

  it('returns null for missing, empty, or unparseable values', () => {
    expect(parseCoordinates(null)).toBeNull()
    expect(parseCoordinates(undefined)).toBeNull()
    expect(parseCoordinates('')).toBeNull()
    expect(parseCoordinates('not-a-coordinate')).toBeNull()
    expect(parseCoordinates('16.0544')).toBeNull()
    expect(parseCoordinates('abc,def')).toBeNull()
  })
})

describe('haversineKm', () => {
  it('is 0 for identical points', () => {
    expect(haversineKm({ lat: 16.0544, lng: 108.2022 }, { lat: 16.0544, lng: 108.2022 })).toBe(0)
  })

  it('matches the known Mỹ Khê ↔ Bà Nà Hills great-circle distance', () => {
    // 16.0490,108.2493 -> 15.9977,107.9967, ~26km straight-line.
    const km = haversineKm({ lat: 16.049, lng: 108.2493 }, { lat: 15.9977, lng: 107.9967 })
    expect(km).toBeGreaterThan(24)
    expect(km).toBeLessThan(28)
  })
})

describe('toLngLat', () => {
  it('swaps to Mapbox GL JS [lng,lat] order — the opposite of this file\'s {lat,lng}', () => {
    expect(toLngLat({ lat: 16.0544, lng: 108.2022 })).toEqual([108.2022, 16.0544])
  })
})

describe('bearingDegrees', () => {
  it('is ~0 (north) for due-north travel', () => {
    const deg = bearingDegrees({ lat: 16.0, lng: 108.2 }, { lat: 16.01, lng: 108.2 })
    expect(deg).toBeGreaterThanOrEqual(0)
    expect(deg).toBeLessThan(1)
  })

  it('is ~90 (east) for due-east travel', () => {
    const deg = bearingDegrees({ lat: 16.0, lng: 108.2 }, { lat: 16.0, lng: 108.21 })
    expect(deg).toBeGreaterThan(89)
    expect(deg).toBeLessThan(91)
  })

  it('is ~180 (south) for due-south travel', () => {
    const deg = bearingDegrees({ lat: 16.01, lng: 108.2 }, { lat: 16.0, lng: 108.2 })
    expect(deg).toBeGreaterThan(179)
    expect(deg).toBeLessThan(181)
  })

  it('stays within [0, 360)', () => {
    const deg = bearingDegrees({ lat: 16.0, lng: 108.2 }, { lat: 15.99, lng: 108.19 })
    expect(deg).toBeGreaterThanOrEqual(0)
    expect(deg).toBeLessThan(360)
  })
})

describe('pointsAlongPolyline', () => {
  // A straight ~222m north-south line (0.002 deg lat ~= 222m), so exact
  // spacing math is easy to check against.
  const line = [
    { lat: 16.0, lng: 108.2 },
    { lat: 16.002, lng: 108.2 },
  ]

  it('returns no points for a degenerate (<2 point, or zero-length) line', () => {
    expect(pointsAlongPolyline([], 20, 0)).toEqual([])
    expect(pointsAlongPolyline([{ lat: 16, lng: 108 }], 20, 0)).toEqual([])
    expect(pointsAlongPolyline([{ lat: 16, lng: 108 }, { lat: 16, lng: 108 }], 20, 0)).toEqual([])
  })

  it('returns no points for a non-positive spacing', () => {
    expect(pointsAlongPolyline(line, 0, 0)).toEqual([])
    expect(pointsAlongPolyline(line, -5, 0)).toEqual([])
  })

  it('places points spacingMeters apart, starting at phase*spacing', () => {
    const points = pointsAlongPolyline(line, 50, 0)
    // ~222m line, 50m spacing, phase 0 -> targets at 0,50,100,150,200 (5 points).
    expect(points.length).toBe(5)
    // Each point should sit essentially on the line (same longitude).
    for (const p of points) expect(p.lng).toBeCloseTo(108.2, 6)
  })

  it('shifts the whole train forward by spacing*phase, wrapping the same way each cycle', () => {
    const atZero = pointsAlongPolyline(line, 50, 0)
    const atHalf = pointsAlongPolyline(line, 50, 0.5)
    // phase 0.5 -> first target at 25m instead of 0m -> first point is
    // further along the line (larger lat) than phase 0's first point.
    expect(atHalf[0].lat).toBeGreaterThan(atZero[0].lat)
  })

  it('carries the bearing of the segment each point lands on', () => {
    const points = pointsAlongPolyline(line, 50, 0)
    for (const p of points) expect(p.bearingDeg).toBeCloseTo(0, 0) // due north
  })
})

describe('boundsOf', () => {
  it('returns null for an empty list', () => {
    expect(boundsOf([])).toBeNull()
  })

  it('returns a degenerate box (sw === ne) for a single point', () => {
    const p = { lat: 16.0544, lng: 108.2022 }
    expect(boundsOf([p])).toEqual({ sw: p, ne: p })
  })

  it('finds the min/max corners across several points', () => {
    const points = [
      { lat: 16.0544, lng: 108.2022 },
      { lat: 15.8794, lng: 108.335 },
      { lat: 16.0678, lng: 107.9967 },
    ]
    expect(boundsOf(points)).toEqual({
      sw: { lat: 15.8794, lng: 107.9967 },
      ne: { lat: 16.0678, lng: 108.335 },
    })
  })
})
