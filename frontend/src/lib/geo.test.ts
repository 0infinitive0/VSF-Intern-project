import { describe, expect, it } from 'vitest'
import { haversineKm, parseCoordinates } from './geo'

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
