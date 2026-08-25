import { describe, expect, it } from 'vitest'
import { dateRange, filterWeekendsOnly, repeatFourWeeks } from './expand-dates'

describe('filterWeekendsOnly', () => {
  it('keeps only Saturday and Sunday dates', () => {
    // 2026-08-17 is a Monday, 2026-08-22/23 are Sat/Sun
    const dates = ['2026-08-17', '2026-08-18', '2026-08-22', '2026-08-23', '2026-08-24']
    expect(filterWeekendsOnly(dates)).toEqual(['2026-08-22', '2026-08-23'])
  })

  it('returns empty when no weekend dates are selected', () => {
    expect(filterWeekendsOnly(['2026-08-17', '2026-08-18'])).toEqual([])
  })
})

describe('repeatFourWeeks', () => {
  it('expands each date to 4x with +7/+14/+21 offsets, deduped and sorted', () => {
    const result = repeatFourWeeks(['2026-08-01'], '2026-01-01')
    expect(result).toEqual(['2026-08-01', '2026-08-08', '2026-08-15', '2026-08-22'])
  })

  it('expands 12 widely-spaced selected dates to 48 unique results (no overlap)', () => {
    // 30-day spacing keeps every date's +0/+7/+14/+21 window clear of every
    // other date's window, so this isolates the "N dates x 4" case from the
    // dedup behavior covered by the overlap test below.
    const dates = Array.from({ length: 12 }, (_, i) => new Date(Date.UTC(2026, 0, 1 + i * 30)).toISOString().slice(0, 10))
    const result = repeatFourWeeks(dates, '2026-01-01')
    expect(result.length).toBe(48)
    expect(new Set(result).size).toBe(48)
  })

  it('dedupes when repeated windows from different selected dates overlap', () => {
    // 12 consecutive dates spanning 12 days: the +7 window of day 1
    // overlaps the +0 window of day 8 onward, so the naive 48 candidates
    // collapse to fewer unique dates -- silently double-writing the same
    // night would be a correctness bug PUT's caller must never send.
    const dates = Array.from({ length: 12 }, (_, i) => new Date(Date.UTC(2026, 7, 20 + i)).toISOString().slice(0, 10))
    const result = repeatFourWeeks(dates, '2026-01-01')
    expect(result.length).toBe(new Set(result).size)
    expect(result.length).toBeLessThan(48)
  })

  it('drops any projected date before today', () => {
    const result = repeatFourWeeks(['2026-08-01'], '2026-08-10')
    expect(result).toEqual(['2026-08-15', '2026-08-22'])
  })
})

describe('dateRange', () => {
  it('returns an inclusive ascending range regardless of argument order', () => {
    expect(dateRange('2026-08-05', '2026-08-08')).toEqual(['2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08'])
    expect(dateRange('2026-08-08', '2026-08-05')).toEqual(['2026-08-05', '2026-08-06', '2026-08-07', '2026-08-08'])
  })

  it('returns a single date when both ends are equal', () => {
    expect(dateRange('2026-08-05', '2026-08-05')).toEqual(['2026-08-05'])
  })

  it('crosses a month boundary correctly', () => {
    expect(dateRange('2026-08-30', '2026-09-02')).toEqual(['2026-08-30', '2026-08-31', '2026-09-01', '2026-09-02'])
  })
})
