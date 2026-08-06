import { describe, expect, it } from 'vitest'
import { formatFullDate, formatTripDateRange } from './format-trip-dates'

describe('formatTripDateRange', () => {
  it('formats an ISO datetime pair into a short range', () => {
    expect(formatTripDateRange('2026-08-10T00:00:00Z', '2026-08-18T00:00:00Z', 'en-US')).toBe(
      'Aug 10 - Aug 18',
    )
  })

  it('formats in the vi locale', () => {
    const result = formatTripDateRange('2026-08-10T00:00:00Z', '2026-08-18T00:00:00Z', 'vi-VN')
    expect(result).toMatch(/10/)
    expect(result).toMatch(/18/)
  })

  it('returns null when either date is missing or invalid', () => {
    expect(formatTripDateRange(null, '2026-08-18T00:00:00Z', 'en-US')).toBeNull()
    expect(formatTripDateRange('nope', '2026-08-18T00:00:00Z', 'en-US')).toBeNull()
    expect(formatTripDateRange('2026-08-10', '', 'en-US')).toBeNull()
  })
})

describe('formatFullDate', () => {
  it('formats vi as d/m/yyyy with zero-padded month', () => {
    expect(formatFullDate('2026-08-15T00:00:00Z', 'vi')).toBe('15/08/2026')
  })

  it('formats en as "Aug 15, 2026"', () => {
    expect(formatFullDate('2026-08-15T00:00:00Z', 'en-US')).toBe('Aug 15, 2026')
  })

  it('returns null for missing or invalid values', () => {
    expect(formatFullDate(null, 'en-US')).toBeNull()
    expect(formatFullDate('garbage', 'en-US')).toBeNull()
  })
})
