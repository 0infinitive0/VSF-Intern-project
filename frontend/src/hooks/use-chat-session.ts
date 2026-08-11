/**
 * use-chat-session.ts — single useReducer managing the entire chat state.
 *
 * Session lifecycle:
 *   - On mount: try to rehydrate session_id from sessionStorage.
 *     If none, create a new session.
 *     If found but the server returns 404 (server restarted), silently create a new session (D1).
 *   - startNew(): create a new session, no DELETE — the old one stays persisted
 *     and stays in the history rail (deleting a conversation is a separate,
 *     explicit action against session-client.ts's deleteSession()).
 *   - restore(sessionId): hydrate state from a past session's persisted data.
 *
 * Elapsed timer: started when pending=true, cleared in the finally block.
 */

import { useReducer, useEffect, useRef, useCallback } from 'react'
import { changeHotel as changeHotelRequest, createSession, sendMessage } from '../api/chat-client'
import { restoreSession } from '../api/session-client'
import { sendMessageStream, StreamUnsupported } from '../api/stream-client'
import i18n from '../i18n'
import type { ChatState, PlannerChatResponse, PhaseKey, SessionRestore } from '../types'

const SESSION_KEY = 'vsf_trip_planner_session_id'

// Exported for use-chat-session.test.ts — the RESTORE/turnSessionId-guard
// behavior is pure state-transition logic, tested directly without rendering
// the hook (no React Testing Library in this project; see derive-stage.ts
// for the same pattern).
export const INITIAL_STATE: ChatState = {
  sessionId: null,
  turnId: 0,
  messages: [],
  suggestions: [],
  hotelOptions: [],
  tripPlan: null,
  intake: null,
  pending: false,
  hotelsLoading: false,
  elapsedMs: 0,
  error: null,
  streamingText: '',
  phases: [],
}

// ── Action types ─────────────────────────────────────────────────────────────

export type Action =
  | { type: 'SESSION_READY'; sessionId: string }
  // `displayText`: shows a friendlier label in the user's own bubble than
  // the literal wire payload (e.g. "1") — see stage-hotels.tsx's hotel pick.
  // The backend still receives `text` unchanged; only the bubble differs.
  | { type: 'SEND_START'; id: string; text: string; displayText?: string }
  // `turnId` on these five is state.turnId as it was when send() captured it,
  // before any `await` — the reducer drops the action once turnId has moved
  // on, so a stale in-flight turn can't overwrite freshly-restored state.
  // Deliberately turnId, not sessionId: A→B→A leaves sessionId back at "A",
  // which a plain sessionId comparison can't tell apart from the original
  // "A" episode (ABA); turnId only ever increases (see RESET/RESTORE).
  | { type: 'SEND_SUCCESS'; id: string; data: PlannerChatResponse; turnId: number }
  | { type: 'SEND_ERROR'; id: string; error: string; turnId: number }
  | { type: 'TICK' }
  | { type: 'RESET'; sessionId: string }
  | { type: 'RESTORE'; sessionId: string; data: SessionRestore }
  | { type: 'STREAM_PHASE'; key: PhaseKey; at: number; turnId: number }
  | { type: 'STREAM_DELTA'; text: string; turnId: number }
  | { type: 'STREAM_RESET'; turnId: number }
  // Dedicated hotels/change round-trip (step-navigator.tsx's "đổi khách sạn"
  // action) — never part of the chat turn machinery: no message, no LLM call,
  // just a hotel-list refresh. Own pending flag (`hotelsLoading`) so Composer/
  // elapsed-timer/streaming state never react to it.
  | { type: 'HOTELS_CHANGE_START' }
  | { type: 'HOTELS_CHANGE_SUCCESS'; data: PlannerChatResponse }
  | { type: 'HOTELS_CHANGE_ERROR'; error: string }

// ── Reducer ───────────────────────────────────────────────────────────────────

export function chatSessionReducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case 'SESSION_READY':
      return { ...state, sessionId: action.sessionId }

    case 'SEND_START':
      return {
        ...state,
        pending: true,
        elapsedMs: 0,
        error: null,
        messages: [
          ...state.messages,
          {
            id: action.id,
            role: 'user',
            text: action.displayText ?? action.text,
            stage: null,
            at: new Date().toISOString(),
          },
        ],
        // Freeze chips so they aren't clickable while in-flight
        suggestions: [],
        hotelOptions: [],
        streamingText: '',
        phases: [],
      }

    // Unchanged shape on purpose: `final` (stream) and the plain POST body
    // are the exact same PlannerChatResponse dict (contract §Streaming), so
    // both paths dispatch this one action and everything downstream —
    // hotelOptions, tripPlan, intake, suggestions — behaves identically
    // whether the reply streamed or not. Also the point where transient
    // streaming state is cleared.
    case 'SEND_SUCCESS': {
      if (action.turnId !== state.turnId) return state
      const { data } = action
      const isError = data.stage === 'error'
      const newMsg = {
        id: action.id + '_ai',
        role: 'ai' as const,
        text: data.reply,
        stage: data.stage,
        isError,
        at: new Date().toISOString(),
      }
      return {
        ...state,
        pending: false,
        elapsedMs: 0,
        messages: [...state.messages, newMsg],
        suggestions: data.suggestions || [],
        hotelOptions: data.hotel_options || [],
        tripPlan: data.trip_plan || state.tripPlan,
        intake: data.intake || state.intake,
        error: null,
        streamingText: '',
        phases: [],
      }
    }

    case 'SEND_ERROR':
      if (action.turnId !== state.turnId) return state
      return {
        ...state,
        pending: false,
        elapsedMs: 0,
        error: action.error,
        messages: [
          ...state.messages,
          {
            id: action.id + '_err',
            role: 'ai',
            text: action.error,
            stage: 'error',
            isError: true,
            at: new Date().toISOString(),
          },
        ],
        suggestions: [],
        streamingText: '',
        phases: [],
      }

    case 'TICK':
      return { ...state, elapsedMs: state.elapsedMs + 1000 }

    case 'RESET':
      return { ...INITIAL_STATE, sessionId: action.sessionId, turnId: state.turnId + 1 }

    // Starts fresh from INITIAL_STATE rather than spreading `state`: it clears
    // streamingText/phases/error/elapsedMs from whatever session was open
    // before, same reasoning as RESET. `data.stage` is unused on purpose —
    // deriveStageView (lib/derive-stage.ts) re-infers the stage from this
    // state so there is exactly one source of truth for it.
    case 'RESTORE': {
      const { data } = action
      return {
        ...INITIAL_STATE,
        sessionId: action.sessionId,
        turnId: state.turnId + 1,
        messages: (data.messages ?? []).map((m, i) => ({
          id: `${action.sessionId}_r${i}`,
          role: m.role === 'assistant' ? ('ai' as const) : ('user' as const),
          text: m.text,
          stage: m.stage,
          isError: m.stage === 'error',
          at: m.at || undefined,
        })),
        suggestions: data.suggestions || [],
        hotelOptions: data.hotel_options || [],
        tripPlan: data.trip_plan ?? null,
        intake: data.intake ?? null,
      }
    }

    case 'STREAM_PHASE':
      if (action.turnId !== state.turnId) return state
      return { ...state, phases: [...state.phases, { key: action.key, at: action.at }] }

    case 'STREAM_DELTA':
      if (action.turnId !== state.turnId) return state
      return { ...state, streamingText: state.streamingText + action.text }

    // Agent discarded this attempt (textual tool-call JSON / SYSTEM ERROR
    // caught late, or a retry) — drop whatever text was flushed so far. The
    // growing phase list is deliberately left alone: those steps really did
    // happen and stay true regardless of which attempt's prose wins.
    case 'STREAM_RESET':
      if (action.turnId !== state.turnId) return state
      return { ...state, streamingText: '' }

    case 'HOTELS_CHANGE_START':
      return { ...state, hotelsLoading: true, error: null }

    case 'HOTELS_CHANGE_SUCCESS': {
      const { data } = action
      return {
        ...state,
        hotelsLoading: false,
        hotelOptions: data.hotel_options || [],
        tripPlan: data.trip_plan || state.tripPlan,
        intake: data.intake || state.intake,
        error: null,
      }
    }

    case 'HOTELS_CHANGE_ERROR':
      return { ...state, hotelsLoading: false, error: action.error }

    default:
      return state
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChatSession() {
  const [state, dispatch] = useReducer(chatSessionReducer, INITIAL_STATE)
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const idCounter = useRef(0)
  // The in-flight turn's AbortController — startNew()/restore() abort it so
  // an abandoned turn's response can't keep running against a session the
  // user has already left (it would otherwise still pass the turnId guard
  // below if the user later switches back to the same session).
  const abortRef = useRef<AbortController | null>(null)
  // startNew()/restore() both mutate session identity; share one flag so a
  // double-click (either button, or one of each) can't fire two RESET/
  // RESTORE dispatches — the second would silently orphan a session server-side.
  const switchingRef = useRef(false)

  // ── Elapsed timer ────────────────────────────────────────────────────────
  useEffect(() => {
    if (state.pending) {
      timerRef.current = setInterval(() => dispatch({ type: 'TICK' }), 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [state.pending])

  // ── Bootstrap session on mount ───────────────────────────────────────────
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      const stored = sessionStorage.getItem(SESSION_KEY)

      if (stored) {
        // Validate stored session — server may have restarted (D1)
        try {
          const res = await fetch(`/api/v1/chat/${encodeURIComponent(stored)}/plan`)
          if (res.status === 404) {
            // Server lost this session — start fresh silently
            const data = await createSession()
            if (cancelled) return
            sessionStorage.setItem(SESSION_KEY, data.session_id)
            dispatch({ type: 'SESSION_READY', sessionId: data.session_id })
          } else {
            // Session still alive
            if (cancelled) return
            dispatch({ type: 'SESSION_READY', sessionId: stored })
          }
        } catch {
          // Network error during ping — still use stored id optimistically
          if (cancelled) return
          dispatch({ type: 'SESSION_READY', sessionId: stored })
        }
      } else {
        try {
          const data = await createSession()
          if (cancelled) return
          sessionStorage.setItem(SESSION_KEY, data.session_id)
          dispatch({ type: 'SESSION_READY', sessionId: data.session_id })
        } catch {
          // If session creation fails, generate a client-side fallback UUID
          if (cancelled) return
          const fallback = crypto.randomUUID()
          sessionStorage.setItem(SESSION_KEY, fallback)
          dispatch({ type: 'SESSION_READY', sessionId: fallback })
        }
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  // ── send ─────────────────────────────────────────────────────────────────
  // Streams by default (POST /planner_chat/stream); downgrades to the plain
  // POST endpoint ONLY when the stream request itself never succeeded
  // (StreamUnsupported — network failure, 404/415, wrong content-type). Once
  // the server has returned a 200 text/event-stream response, the turn is
  // already running server-side regardless of whether any frame was actually
  // read — replaying via POST would send the same message twice, so any
  // later failure (including a first-frame timeout) surfaces as a plain
  // network error instead of retrying. See stream-client.ts's StreamUnsupported.
  const send = useCallback(
    async (text: string, options?: { displayText?: string }) => {
      const trimmed = String(text).trim()
      if (!trimmed || state.pending || !state.sessionId) return

      const id = String(++idCounter.current)
      // Captured before any `await` so a session switch mid-turn can't
      // retarget it — the reducer drops any dispatch tagged with a turnId
      // that's no longer current (see the Action type's comment on why this
      // is turnId, not sessionId).
      const turnId = state.turnId
      dispatch({ type: 'SEND_START', id, text: trimmed, displayText: options?.displayText })

      const controller = new AbortController()
      abortRef.current = controller
      try {
        const data = await sendMessageStream(
          state.sessionId,
          trimmed,
          i18n.language,
          {
            onPhase: (key, at) => dispatch({ type: 'STREAM_PHASE', key: key as PhaseKey, at, turnId }),
            onDelta: (deltaText) => dispatch({ type: 'STREAM_DELTA', text: deltaText, turnId }),
            onReset: () => dispatch({ type: 'STREAM_RESET', turnId }),
          },
          controller.signal,
        )
        dispatch({ type: 'SEND_SUCCESS', id, data, turnId })
      } catch (err) {
        if (err instanceof StreamUnsupported) {
          try {
            const data = await sendMessage(state.sessionId, trimmed, i18n.language)
            dispatch({ type: 'SEND_SUCCESS', id, data, turnId })
            return
          } catch (postErr) {
            dispatch({
              type: 'SEND_ERROR',
              id,
              error: i18n.t('errorNetwork', {
                msg: postErr instanceof Error ? postErr.message : String(postErr),
              }),
              turnId,
            })
            return
          }
        }
        dispatch({
          type: 'SEND_ERROR',
          id,
          error: i18n.t('errorNetwork', { msg: err instanceof Error ? err.message : String(err) }),
          turnId,
        })
      }
    },
    [state.pending, state.sessionId, state.turnId],
  )

  // ── changeHotel ──────────────────────────────────────────────────────────
  // Backs the "đổi khách sạn" step-nav action (step-navigator.tsx). Hits the
  // dedicated deterministic /hotels/change endpoint directly — no LLM call,
  // no chat message — so it's kept entirely separate from `send()`/the chat
  // turn machinery: own pending flag (`hotelsLoading`), no turnId guard
  // needed (nothing here can race a session switch the way a slow chat
  // reply can, since it never touches `messages`).
  const changeHotel = useCallback(async () => {
    if (state.hotelsLoading || !state.sessionId) return
    dispatch({ type: 'HOTELS_CHANGE_START' })
    try {
      const data = await changeHotelRequest(state.sessionId)
      dispatch({ type: 'HOTELS_CHANGE_SUCCESS', data })
    } catch (err) {
      dispatch({
        type: 'HOTELS_CHANGE_ERROR',
        error: i18n.t('errorNetwork', { msg: err instanceof Error ? err.message : String(err) }),
      })
    }
  }, [state.hotelsLoading, state.sessionId])

  // ── startNew ─────────────────────────────────────────────────────────────
  // Deliberately no DELETE: the previous session stays persisted and stays
  // visible in the history rail. Deleting a conversation is the separate,
  // explicit ✕-button action (session-client.ts's deleteSession()).
  const startNew = useCallback(async () => {
    if (switchingRef.current) return
    switchingRef.current = true
    abortRef.current?.abort()
    sessionStorage.removeItem(SESSION_KEY)

    try {
      const data = await createSession()
      sessionStorage.setItem(SESSION_KEY, data.session_id)
      dispatch({ type: 'RESET', sessionId: data.session_id })
    } catch {
      const fallback = crypto.randomUUID()
      sessionStorage.setItem(SESSION_KEY, fallback)
      dispatch({ type: 'RESET', sessionId: fallback })
    } finally {
      switchingRef.current = false
    }
  }, [])

  // ── restore ──────────────────────────────────────────────────────────────
  // Hydrates state from a past session. Returns whether it actually applied
  // — false when the session is gone server-side (TTL eviction, persistence
  // disabled) or a switch was already in flight, so callers (App.tsx) can
  // fall back to startNew() instead of leaving state pointed at nothing.
  const restore = useCallback(async (sessionId: string): Promise<boolean> => {
    if (switchingRef.current) return false
    switchingRef.current = true
    abortRef.current?.abort()
    try {
      const data = await restoreSession(sessionId)
      if (!data) return false
      sessionStorage.setItem(SESSION_KEY, sessionId)
      dispatch({ type: 'RESTORE', sessionId, data })
      return true
    } finally {
      switchingRef.current = false
    }
  }, [])

  return { state, send, startNew, restore, changeHotel }
}
