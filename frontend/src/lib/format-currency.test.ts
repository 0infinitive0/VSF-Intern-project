import { describe, expect, it } from 'vitest'
import { formatCurrency } from './format-currency'

describe('formatCurrency', () => {
  it('formats vi with a postfix "₫" and dot thousands separator', () => {
    expect(formatCurrency(1500000, 'vi')).toBe('1.500.000 ₫')
  })

  it('formats en with a "VND " prefix and comma thousands separator', () => {
    expect(formatCurrency(1500000, 'en')).toBe('VND 1,500,000')
  })

  it('rounds fractional amounts', () => {
    expect(formatCurrency(1500000.6, 'vi')).toBe('1.500.001 ₫')
    expect(formatCurrency(1500000.4, 'en')).toBe('VND 1,500,000')
  })

  it('returns "" for non-finite values', () => {
    expect(formatCurrency(Number.NaN, 'vi')).toBe('')
    expect(formatCurrency(Number.POSITIVE_INFINITY, 'en')).toBe('')
  })
})
