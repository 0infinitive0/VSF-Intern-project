import { describe, expect, it } from 'vitest'
import { mergeActiveSession } from './merge-active-session'
import type { SessionSummary } from '../types'

const persisted: SessionSummary = {
  session_id: 'a',
  title: 'trip a',
  destination: 'Đà Nẵng',
  duration_days: 4,
  status: 'draft',
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  thumbnail_url: null,
}

const NOW = '2026-08-10T00:00:00Z'

describe('mergeActiveSession', () => {
  it('returns the list unchanged when there is no active session', () => {
    expect(mergeActiveSession([persisted], null, NOW)).toEqual([persisted])
  })

  it('returns the list unchanged when the active session is already persisted', () => {
    expect(mergeActiveSession([persisted], 'a', NOW)).toEqual([persisted])
  })

  it('prepends a draft optimistic row when the active session is not yet persisted', () => {
    const result = mergeActiveSession([persisted], 'b', NOW)
    expect(result).toHaveLength(2)
    expect(result[0]).toMatchObject({
      session_id: 'b',
      status: 'draft',
      title: undefined,
      destination: null,
      created_at: NOW,
      updated_at: NOW,
    })
    expect(result[1]).toBe(persisted)
  })

  it('does not duplicate the optimistic row after the real one appears in a refetch', () => {
    const withReal = [{ ...persisted, session_id: 'b' }, persisted]
    const result = mergeActiveSession(withReal, 'b', NOW)
    expect(result).toHaveLength(2)
    expect(result.filter((s) => s.session_id === 'b')).toHaveLength(1)
  })
})
