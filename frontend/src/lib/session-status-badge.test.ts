import { describe, expect, it } from 'vitest'
import { sessionStatusBadge } from './session-status-badge'

describe('sessionStatusBadge', () => {
  it('returns the draft badge', () => {
    expect(sessionStatusBadge('draft')).toEqual({
      labelKey: 'sidebarStatusDraft',
      bgClass: 'bg-warning-soft',
      inkClass: 'text-warning-ink',
    })
  })

  it('returns the completed badge', () => {
    expect(sessionStatusBadge('completed')).toEqual({
      labelKey: 'sidebarStatusCompleted',
      bgClass: 'bg-success-soft',
      inkClass: 'text-success-ink',
    })
  })

  it('returns the holding badge', () => {
    expect(sessionStatusBadge('holding')).toEqual({
      labelKey: 'sidebarStatusHolding',
      bgClass: 'bg-holding-soft',
      inkClass: 'text-holding-ink',
    })
  })

  it('returns the paid badge', () => {
    expect(sessionStatusBadge('paid')).toEqual({
      labelKey: 'sidebarStatusPaid',
      bgClass: 'bg-paid-soft',
      inkClass: 'text-paid-ink',
    })
  })
})
