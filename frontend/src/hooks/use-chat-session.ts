/**
 * use-chat-session.ts — single useReducer managing the entire chat state.
 *
 * Session lifecycle:
 *   - On mount: try to rehydrate session_id from sessionStorage.
 *     If none, create a new session.
 *     If found but the server returns 404 (server restarted), silently create a new session (D1).
 *   - On reset: DELETE old session, clear everything, create a new session.
 *
 * Elapsed timer: started when pending=true, cleared in the finally block.
 */

import { useReducer, useEffect, useRef, useCallback } from 'react'
import { createSession, sendMessage, resetSession } from '../api/chat-client'
import { sendMessageStream, StreamUnsupported } from '../api/stream-client'
import i18n from '../i18n'
import type { ChatState, PlannerChatResponse, PhaseKey } from '../types'

const SESSION_KEY = 'vsf_trip_planner_session_id'

const INITIAL_STATE: ChatState = {
  sessionId: null,
  messages: [],
  suggestions: [],
  hotelOptions: [],
  tripPlan: null,
  intake: null,
  pending: false,
  elapsedMs: 0,
  error: null,
  streamingText: '',
  phases: [],
}

// ── Action types ─────────────────────────────────────────────────────────────

type Action =
  | { type: 'SESSION_READY'; sessionId: string }
  | { type: 'SEND_START'; id: string; text: string }
  | { type: 'SEND_SUCCESS'; id: string; data: PlannerChatResponse }
  | { type: 'SEND_ERROR'; id: string; error: string }
  | { type: 'TICK' }
  | { type: 'RESET'; sessionId: string }
  | { type: 'STREAM_PHASE'; key: PhaseKey; at: number }
  | { type: 'STREAM_DELTA'; text: string }
  | { type: 'STREAM_RESET' }

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state: ChatState, action: Action): ChatState {
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
          { id: action.id, role: 'user', text: action.text, stage: null, at: new Date().toISOString() },
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
      return { ...INITIAL_STATE, sessionId: action.sessionId }

    case 'STREAM_PHASE':
      return { ...state, phases: [...state.phases, { key: action.key, at: action.at }] }

    case 'STREAM_DELTA':
      return { ...state, streamingText: state.streamingText + action.text }

    // Agent discarded this attempt (textual tool-call JSON / SYSTEM ERROR
    // caught late, or a retry) — drop whatever text was flushed so far. The
    // growing phase list is deliberately left alone: those steps really did
    // happen and stay true regardless of which attempt's prose wins.
    case 'STREAM_RESET':
      return { ...state, streamingText: '' }

    default:
      return state
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChatSession() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE)
  const timerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const idCounter = useRef(0)

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
    async (text: string) => {
      const trimmed = String(text).trim()
      if (!trimmed || state.pending || !state.sessionId) return

      const id = String(++idCounter.current)
      dispatch({ type: 'SEND_START', id, text: trimmed })

      const controller = new AbortController()
      try {
        const data = await sendMessageStream(
          state.sessionId,
          trimmed,
          i18n.language,
          {
            onPhase: (key, at) => dispatch({ type: 'STREAM_PHASE', key: key as PhaseKey, at }),
            onDelta: (deltaText) => dispatch({ type: 'STREAM_DELTA', text: deltaText }),
            onReset: () => dispatch({ type: 'STREAM_RESET' }),
          },
          controller.signal,
        )
        dispatch({ type: 'SEND_SUCCESS', id, data })
      } catch (err) {
        if (err instanceof StreamUnsupported) {
          try {
            const data = await sendMessage(state.sessionId, trimmed, i18n.language)
            dispatch({ type: 'SEND_SUCCESS', id, data })
            return
          } catch (postErr) {
            dispatch({
              type: 'SEND_ERROR',
              id,
              error: i18n.t('errorNetwork', {
                msg: postErr instanceof Error ? postErr.message : String(postErr),
              }),
            })
            return
          }
        }
        dispatch({
          type: 'SEND_ERROR',
          id,
          error: i18n.t('errorNetwork', { msg: err instanceof Error ? err.message : String(err) }),
        })
      }
    },
    [state.pending, state.sessionId],
  )

  // ── reset ─────────────────────────────────────────────────────────────────
  const reset = useCallback(async () => {
    if (state.sessionId) {
      try {
        await resetSession(state.sessionId)
      } catch {
        // Best-effort; proceed regardless
      }
    }
    sessionStorage.removeItem(SESSION_KEY)

    try {
      const data = await createSession()
      sessionStorage.setItem(SESSION_KEY, data.session_id)
      dispatch({ type: 'RESET', sessionId: data.session_id })
    } catch {
      const fallback = crypto.randomUUID()
      sessionStorage.setItem(SESSION_KEY, fallback)
      dispatch({ type: 'RESET', sessionId: fallback })
    }
  }, [state.sessionId])

  return { state, send, reset }
}
