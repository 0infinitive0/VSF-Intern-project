/**
 * use-session-history.ts — history-rail data for App.tsx. Owns fetching and
 * local list edits (delete/optimistic insert); App.tsx owns which session is
 * active (that's just ChatState.sessionId, no second "selected" concept here
 * — see plan.md's "Ai giữ state nào").
 *
 * Refetches on mount and whenever a chat turn finishes (`pending` true→false)
 * — that's the moment the just-active session's title/status/thumbnail may
 * have changed server-side. Does NOT refetch on pending's other edges.
 * App.tsx also calls refresh() directly after a delete, to reconcile the
 * list with the server (and to retry after a failed restore()).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { listSessions } from '../api/session-client'
import { mergeActiveSession } from '../lib/merge-active-session'
import type { SessionSummary } from '../types'

export function useSessionHistory(activeSessionId: string | null, pending: boolean) {
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  // Two independent effects below can each have a listSessions() in flight
  // at once (mount + a turn finishing in quick succession, or a manual
  // refresh() racing one of those). Only the most recently issued request is
  // allowed to apply — otherwise an older, slower response can land after a
  // newer one (or after removeLocal()'s optimistic delete) and silently
  // resurrect a row the user just deleted.
  const seqRef = useRef(0)

  const refresh = useCallback(async () => {
    const seq = ++seqRef.current
    const list = await listSessions()
    if (seq !== seqRef.current) return
    setSessions(list)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const wasPending = useRef(pending)
  useEffect(() => {
    if (wasPending.current && !pending) refresh()
    wasPending.current = pending
  }, [pending, refresh])

  const removeLocal = useCallback((sessionId: string) => {
    setSessions((prev) => (prev ? prev.filter((s) => s.session_id !== sessionId) : prev))
  }, [])

  // Pinned per active session (recomputed only when activeSessionId itself
  // changes, not on every render) rather than a fresh `new Date()` on every
  // call: mergeActiveSession is a pure function of its arguments, so a
  // stable `now` keeps its output (and thus this hook's return value)
  // referentially stable across re-renders that don't actually change
  // anything. Mutating a ref during render like this is the documented
  // React pattern for "cache a value derived from a prop without an Effect".
  const optimisticRowCreatedAtRef = useRef<{ sessionId: string | null; iso: string }>({
    sessionId: activeSessionId,
    iso: new Date().toISOString(),
  })
  if (optimisticRowCreatedAtRef.current.sessionId !== activeSessionId) {
    optimisticRowCreatedAtRef.current = { sessionId: activeSessionId, iso: new Date().toISOString() }
  }

  const mergedSessions = useMemo(
    () =>
      sessions === null ? null : mergeActiveSession(sessions, activeSessionId, optimisticRowCreatedAtRef.current.iso),
    [sessions, activeSessionId],
  )

  return { sessions: mergedSessions, refresh, removeLocal }
}
