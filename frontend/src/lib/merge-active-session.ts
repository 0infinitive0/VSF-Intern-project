/**
 * merge-active-session.ts — inserts a synthetic "optimistic" row for the
 * active session into the persisted history list when the backend hasn't
 * persisted it yet (persist_hook runs after the first chat turn completes;
 * registry.create() does not write a row). Without this, hitting
 * "+ New trip" looks like nothing happened until the first reply lands.
 *
 * Merged by session_id so a subsequent refetch (which now includes the real
 * row) replaces the optimistic one instead of duplicating it. The backend
 * already sorts by updated_at desc, so the optimistic row — always the most
 * recently touched — stays first without re-sorting here.
 */
import type { SessionSummary } from '../types'

// `now` is a caller-supplied ISO string rather than `new Date().toISOString()`
// called in here: this function runs inside a render-path useMemo (see
// use-session-history.ts), and a fresh timestamp on every call would make it
// impure — a new array/object identity every render even when nothing
// actually changed, defeating any memoization downstream.
export function mergeActiveSession(
  sessions: SessionSummary[],
  activeSessionId: string | null,
  now: string,
): SessionSummary[] {
  if (!activeSessionId) return sessions
  if (sessions.some((s) => s.session_id === activeSessionId)) return sessions

  const optimisticRow: SessionSummary = {
    session_id: activeSessionId,
    title: undefined,
    destination: null,
    duration_days: null,
    status: 'draft',
    created_at: now,
    updated_at: now,
    thumbnail_url: null,
  }
  return [optimisticRow, ...sessions]
}
