import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatSessionDate } from './session-date'

describe('formatSessionDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-10T15:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns the today label for a timestamp on the same local day (with Z suffix)', () => {
    expect(formatSessionDate('2026-08-10T02:00:00Z', 'vi-VN', 'Hôm nay')).toBe('Hôm nay')
  })

  it('returns the today label for a timestamp on the same local day (no Z suffix)', () => {
    expect(formatSessionDate('2026-08-10T02:00:00', 'vi-VN', 'Hôm nay')).toBe('Hôm nay')
  })

  it('formats a past date as dd/mm/yyyy for vi locale', () => {
    expect(formatSessionDate('2026-07-28T00:00:00Z', 'vi-VN', 'Hôm nay')).toBe('28/07/2026')
  })

  it('formats a past date as "Mon d, yyyy" for en locale', () => {
    const result = formatSessionDate('2026-07-28T00:00:00Z', 'en-US', 'Today')
    expect(result).toMatch(/2026/)
    expect(result).toMatch(/28/)
    expect(result).not.toBe('Today')
  })

  it('produces different output for vi vs en locales on the same date', () => {
    const vi_ = formatSessionDate('2026-07-28T00:00:00Z', 'vi-VN', 'Hôm nay')
    const en = formatSessionDate('2026-07-28T00:00:00Z', 'en-US', 'Today')
    expect(vi_).not.toBe(en)
  })

  it('returns the raw string unchanged when parsing fails', () => {
    expect(formatSessionDate('not-a-date', 'vi-VN', 'Hôm nay')).toBe('not-a-date')
  })
})
