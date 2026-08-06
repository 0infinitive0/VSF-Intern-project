import { describe, expect, it } from 'vitest'
import { buildMatchReasonLines } from './match-reason-lines'
import type { MatchReason } from '../types'

describe('buildMatchReasonLines', () => {
  it('returns an empty list for missing/empty input', () => {
    expect(buildMatchReasonLines(undefined)).toEqual([])
    expect(buildMatchReasonLines(null)).toEqual([])
    expect(buildMatchReasonLines([])).toEqual([])
  })

  it('keeps every known code with its raw value', () => {
    const reasons: MatchReason[] = [
      { code: 'high_rating', value: 8.9 },
      { code: 'amenity_match', value: 'Hồ bơi vô cực' },
      { code: 'star_rating', value: 5 },
      { code: 'strong_similarity', value: '' },
      { code: 'near_center', value: 'Sơn Trà' },
    ]
    expect(buildMatchReasonLines(reasons)).toEqual([
      { code: 'high_rating', value: 8.9 },
      { code: 'amenity_match', value: 'Hồ bơi vô cực' },
      { code: 'star_rating', value: 5 },
      { code: 'strong_similarity', value: '' },
      { code: 'near_center', value: 'Sơn Trà' },
    ])
  })

  it('silently skips unknown codes so newer backends cannot leak raw strings', () => {
    const reasons: MatchReason[] = [
      { code: 'brand_new_code', value: 'whatever' },
      { code: 'high_rating', value: 9.2 },
    ]
    expect(buildMatchReasonLines(reasons)).toEqual([{ code: 'high_rating', value: 9.2 }])
  })

  it('converts budget_fit fractions (0..1) to rounded percents', () => {
    expect(buildMatchReasonLines([{ code: 'budget_fit', value: 0.39 }])).toEqual([
      { code: 'budget_fit', value: 39 },
    ])
    expect(buildMatchReasonLines([{ code: 'budget_fit', value: 0.823 }])).toEqual([
      { code: 'budget_fit', value: 82 },
    ])
  })

  it('tolerates budget_fit arriving already as a percent number', () => {
    expect(buildMatchReasonLines([{ code: 'budget_fit', value: 82 }])).toEqual([
      { code: 'budget_fit', value: 82 },
    ])
  })

  it('leaves non-numeric budget_fit values untouched', () => {
    expect(buildMatchReasonLines([{ code: 'budget_fit', value: 'vừa túi tiền' }])).toEqual([
      { code: 'budget_fit', value: 'vừa túi tiền' },
    ])
  })
})
