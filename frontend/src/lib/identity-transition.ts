/**
 * identity-transition.ts — the pure decision behind App.tsx's identity-watch
 * effect: given how `auth.user?.id` just changed, should the active trip
 * (tripPlan / hotelOptionsBySession / intake) be wiped for a fresh session?
 *
 * Pulled out of the effect (rather than left as inline if/else) for the same
 * reason use-chat-session.ts's resolveBootstrapSession is pure: this repo has
 * no React Testing Library, so anything worth covering with more than one
 * case needs to be testable without rendering a component.
 *
 * The three real transitions `auth.user?.id` can make after boot, and why
 * only the first two should reset the trip:
 *   1. Real sign-out (auth-context.tsx's signOut()): real user id -> a new
 *      anonymous id. The visitor asked for this — start fresh.
 *   2. Signing into a different, pre-existing account (email/password or
 *      Google): anonymous or real id -> a different real id. Also asked for.
 *   3. An anonymous session silently dying and getting re-minted
 *      (auth-context.tsx's onAuthStateChange, the `wasAnonymous` branch):
 *      anonymous id -> a *different* anonymous id, with no visitor action at
 *      all — typically triggered by the tab sitting backgrounded/idle for a
 *      few hours, long enough that supabase-js's autoRefreshToken timer
 *      missed its window (browsers throttle background-tab timers). From
 *      `user.id` alone this looks identical to case 1/2, but resetting here
 *      is the bug: it silently wipes a guest's fully-valid, still-persisted
 *      trip and locks the Hotels/Itinerary step-navigator tabs, with no
 *      error shown anywhere. `wasSilentRecovery` (sourced from
 *      auth-context.tsx's silentRecoveryRef) is what tells case 3 apart from
 *      1/2 so only 1/2 reset.
 */

export interface IdentityTransitionInput {
  /** True on the very first time this effect runs after mount — normal boot,
   * never a switch. */
  isFirstRender: boolean
  previousUserId: string | null
  currentUserId: string | null
  /** True when `currentUserId` is the result of auth-context.tsx's silent
   * anonymous re-mint (case 3 above), not a real sign-out/sign-in. */
  wasSilentRecovery: boolean
}

export interface IdentityTransitionResult {
  /** What the caller's "previous id" ref should hold after this transition. */
  nextPreviousUserId: string | null
  /** Whether the caller should actually write `nextPreviousUserId` into its
   * ref. False for a still-in-flight null id (real sign-out's brief
   * real-user -> null -> new-anonymous-user window) and for a no-op id, so
   * the ref keeps describing the last id genuinely worth comparing against. */
  updatePrevious: boolean
  /** Whether the caller should reset the active trip. */
  shouldReset: boolean
}

export function resolveIdentityTransition({
  isFirstRender,
  previousUserId,
  currentUserId,
  wasSilentRecovery,
}: IdentityTransitionInput): IdentityTransitionResult {
  if (isFirstRender) {
    return { nextPreviousUserId: currentUserId, updatePrevious: true, shouldReset: false }
  }
  // Skips a null id entirely — see IdentityTransitionInput's doc comment and
  // App.tsx's own comment on why firing here would send a session-creating
  // fetch with no Authorization header.
  if (currentUserId === null) {
    return { nextPreviousUserId: previousUserId, updatePrevious: false, shouldReset: false }
  }
  if (previousUserId === currentUserId) {
    return { nextPreviousUserId: previousUserId, updatePrevious: false, shouldReset: false }
  }
  return {
    nextPreviousUserId: currentUserId,
    updatePrevious: true,
    shouldReset: !wasSilentRecovery,
  }
}
