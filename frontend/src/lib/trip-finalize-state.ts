/**
 * trip-finalize-state.ts — pure gate logic for the "Hoàn tất lịch trình"
 * (finalize) control in the workspace header (finalize-action.tsx).
 *
 * Kept as plain functions, no React, mirroring derive-stage.ts / booking-
 * error.ts / session-status-badge.ts: the "must pay before finalizing" rule
 * is testable without a browser, and the button gets one source of truth for
 * its disabled reason instead of re-deriving it inline at the call site.
 *
 * Backend writes `itineraries.status = "Finalized"` (services/
 * trip_finalize.py); `isTripFinalized` is the one place that string is
 * compared against, case-insensitively, so a backend casing change can't
 * silently strand the button in the wrong state.
 */
import type { TripPlan } from '../types'

export function isTripFinalized(tripPlan: TripPlan | null): boolean {
  return (tripPlan?.status ?? '').toLowerCase() === 'finalized'
}

export type FinalizeBlockedReason = 'no-plan' | 'not-paid' | 'already-final' | 'busy' | null

/**
 * `null` means "enabled" — every other value is a reason `finalize-action.tsx`
 * shows the user instead of a bare greyed-out button (design decision: an
 * unexplained disabled control reads as broken, and "not paid yet" is the
 * gate most users will actually hit).
 *
 * Order matters: `already-final` is checked before `not-paid` so a finalized
 * (and therefore always-paid, per this feature's own payment gate) trip shows
 * the DONE badge rather than a stale "book first" reason — `finalize-
 * action.tsx` never reaches this function once `isTripFinalized` is true, but
 * the precedence is asserted here too so the two can't silently drift apart.
 */
export function finalizeBlockedReason(args: {
  tripPlan: TripPlan | null
  sessionBookedFromBackend: boolean
  pending: boolean
}): FinalizeBlockedReason {
  const { tripPlan, sessionBookedFromBackend, pending } = args
  if (tripPlan == null) return 'no-plan'
  if (isTripFinalized(tripPlan)) return 'already-final'
  if (!sessionBookedFromBackend) return 'not-paid'
  if (pending) return 'busy'
  return null
}
