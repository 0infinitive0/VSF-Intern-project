import { describe, expect, it } from 'vitest'
import { formatDurationVi } from './format-duration-vi'

describe('formatDurationVi', () => {
  it('drops the "phút" clause under a minute', () => {
    expect(formatDurationVi(45)).toBe('45 giây')
  })

  it('drops the "giây" clause on an exact minute', () => {
    expect(formatDurationVi(180)).toBe('3 phút')
  })

  it('includes both clauses otherwise', () => {
    expect(formatDurationVi(200)).toBe('3 phút 20 giây')
  })

  it('rounds to the nearest second and never goes negative', () => {
    expect(formatDurationVi(0)).toBe('0 giây')
    expect(formatDurationVi(-5)).toBe('0 giây')
    expect(formatDurationVi(59.6)).toBe('1 phút')
  })

  it('never rolls minutes over into hours', () => {
    expect(formatDurationVi(3600)).toBe('60 phút')
  })
})
