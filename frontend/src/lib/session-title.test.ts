import { describe, expect, it } from 'vitest'
import { composeSessionTitle } from './session-title'

const labels = { daysSuffix: 'N', nightsSuffix: 'Đ' }

describe('composeSessionTitle', () => {
  it('composes destination + days/nights suffix when both fields are present', () => {
    expect(composeSessionTitle({ destination: 'Đà Nẵng', duration_days: 4, title: undefined }, labels)).toBe(
      'Đà Nẵng 4N3Đ',
    )
  })

  it('floors nights at 1 for a 1-day trip instead of "1N0Đ"', () => {
    expect(composeSessionTitle({ destination: 'Đà Nẵng', duration_days: 1, title: undefined }, labels)).toBe(
      'Đà Nẵng 1N1Đ',
    )
  })

  it('falls back to destination alone when duration_days is missing', () => {
    expect(composeSessionTitle({ destination: 'Đà Nẵng', duration_days: null, title: undefined }, labels)).toBe(
      'Đà Nẵng',
    )
  })

  it('falls back to the raw user title when destination is missing', () => {
    expect(
      composeSessionTitle(
        { destination: null, duration_days: null, title: 'cho tôi đi đà nẵng 4 ngày' },
        labels,
      ),
    ).toBe('cho tôi đi đà nẵng 4 ngày')
  })

  it('returns null when nothing is available', () => {
    expect(composeSessionTitle({ destination: null, duration_days: null, title: undefined }, labels)).toBeNull()
  })

  it('does not further truncate an already-long title (backend already truncates)', () => {
    const long = 'a'.repeat(120)
    expect(composeSessionTitle({ destination: null, duration_days: null, title: long }, labels)).toBe(long)
  })
})
