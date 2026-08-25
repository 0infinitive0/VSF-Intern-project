import { describe, expect, it } from 'vitest'
import { resolveIdentityTransition } from './identity-transition'

describe('resolveIdentityTransition', () => {
  it('never resets on the first render, and seeds previousUserId either way', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: true,
        previousUserId: null,
        currentUserId: 'anon-1',
        wasSilentRecovery: false,
      }),
    ).toEqual({ nextPreviousUserId: 'anon-1', updatePrevious: true, shouldReset: false })
  })

  it('resets on a real sign-out (real user -> a new anonymous user)', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: false,
        previousUserId: 'real-1',
        currentUserId: 'anon-2',
        wasSilentRecovery: false,
      }),
    ).toEqual({ nextPreviousUserId: 'anon-2', updatePrevious: true, shouldReset: true })
  })

  it('resets on signing into a different, pre-existing account', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: false,
        previousUserId: 'anon-1',
        currentUserId: 'real-2',
        wasSilentRecovery: false,
      }),
    ).toEqual({ nextPreviousUserId: 'real-2', updatePrevious: true, shouldReset: true })
  })

  it('does NOT reset when an anonymous session was silently re-minted', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: false,
        previousUserId: 'anon-1',
        currentUserId: 'anon-2',
        wasSilentRecovery: true,
      }),
    ).toEqual({ nextPreviousUserId: 'anon-2', updatePrevious: true, shouldReset: false })
  })

  it('still tracks the new id after a silent recovery, so a later real switch is detected', () => {
    const afterRecovery = resolveIdentityTransition({
      isFirstRender: false,
      previousUserId: 'anon-1',
      currentUserId: 'anon-2',
      wasSilentRecovery: true,
    })
    expect(afterRecovery.nextPreviousUserId).toBe('anon-2')

    const laterRealSwitch = resolveIdentityTransition({
      isFirstRender: false,
      previousUserId: afterRecovery.nextPreviousUserId,
      currentUserId: 'real-3',
      wasSilentRecovery: false,
    })
    expect(laterRealSwitch.shouldReset).toBe(true)
  })

  it('ignores a transient null id (mid real-sign-out) without resetting or updating', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: false,
        previousUserId: 'real-1',
        currentUserId: null,
        wasSilentRecovery: false,
      }),
    ).toEqual({ nextPreviousUserId: 'real-1', updatePrevious: false, shouldReset: false })
  })

  it('is a no-op when the id has not actually changed', () => {
    expect(
      resolveIdentityTransition({
        isFirstRender: false,
        previousUserId: 'anon-1',
        currentUserId: 'anon-1',
        wasSilentRecovery: false,
      }),
    ).toEqual({ nextPreviousUserId: 'anon-1', updatePrevious: false, shouldReset: false })
  })
})
