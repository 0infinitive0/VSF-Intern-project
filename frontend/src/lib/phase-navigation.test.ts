import { describe, expect, it } from 'vitest'
import { navigationTarget } from './phase-navigation'

describe('navigationTarget', () => {
  it('switches to retained phase data without producing a chat action', () => {
    expect(navigationTarget('hotels', { intakeComplete: true, hotelOptionsAvailable: true, hotelPicked: false })).toBe(
      'hotels',
    )
    expect(navigationTarget('workspace', { intakeComplete: true, hotelOptionsAvailable: true, hotelPicked: true })).toBe(
      'workspace',
    )
  })

  it('keeps unreached phases unavailable', () => {
    expect(navigationTarget('hotels', { intakeComplete: false, hotelOptionsAvailable: false, hotelPicked: false })).toBeNull()
    expect(navigationTarget('workspace', { intakeComplete: true, hotelOptionsAvailable: true, hotelPicked: false })).toBeNull()
  })

})
