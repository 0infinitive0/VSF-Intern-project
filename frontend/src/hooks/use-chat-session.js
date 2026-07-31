/**
 * use-chat-session.js — single useReducer managing the entire chat state.
 *
 * State shape:
 *   { sessionId, messages, suggestions, hotelOptions, tripPlan, pending, elapsedMs, error }
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
import { createSession, sendMessage, resetSession } from '../api/chat-client.js'
import { S } from '../strings.js'

const SESSION_KEY = 'vsf_trip_planner_session_id'

// ── State shape ──────────────────────────────────────────────────────────────

const INITIAL_STATE = {
  sessionId: null,
  messages: [],
  suggestions: [],
  hotelOptions: [],
  tripPlan: null,
  pending: false,
  elapsedMs: 0,
  error: null,
}

// ── Action types ─────────────────────────────────────────────────────────────

const A = {
  SESSION_READY: 'SESSION_READY',
  SEND_START: 'SEND_START',
  SEND_SUCCESS: 'SEND_SUCCESS',
  SEND_ERROR: 'SEND_ERROR',
  TICK: 'TICK',
  RESET: 'RESET',
}

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state, action) {
  switch (action.type) {
    case A.SESSION_READY:
      return { ...state, sessionId: action.sessionId }

    case A.SEND_START:
      return {
        ...state,
        pending: true,
        elapsedMs: 0,
        error: null,
        messages: [
          ...state.messages,
          { id: action.id, role: 'user', text: action.text, stage: null },
        ],
        // Freeze chips so they aren't clickable while in-flight
        suggestions: [],
        hotelOptions: [],
      }

    case A.SEND_SUCCESS: {
      const { data } = action
      const isError = data.stage === 'error'
      const newMsg = {
        id: action.id + '_ai',
        role: 'ai',
        text: data.reply,
        stage: data.stage,
        isError,
      }
      return {
        ...state,
        pending: false,
        elapsedMs: 0,
        messages: [...state.messages, newMsg],
        suggestions: data.suggestions || [],
        hotelOptions: data.hotel_options || [],
        tripPlan: data.trip_plan || state.tripPlan,
        error: null,
      }
    }

    case A.SEND_ERROR:
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
          },
        ],
        suggestions: [],
      }

    case A.TICK:
      return { ...state, elapsedMs: state.elapsedMs + 1000 }

    case A.RESET:
      return { ...INITIAL_STATE, sessionId: action.sessionId }

    default:
      return state
  }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useChatSession() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE)
  const timerRef = useRef(null)
  const idCounter = useRef(0)

  // ── Elapsed timer ────────────────────────────────────────────────────────
  useEffect(() => {
    if (state.pending) {
      timerRef.current = setInterval(() => dispatch({ type: A.TICK }), 1000)
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
          const res = await fetch(
            `/api/v1/chat/${encodeURIComponent(stored)}/plan`,
          )
          if (res.status === 404) {
            // Server lost this session — start fresh silently
            const data = await createSession()
            if (cancelled) return
            sessionStorage.setItem(SESSION_KEY, data.session_id)
            dispatch({ type: A.SESSION_READY, sessionId: data.session_id })
          } else {
            // Session still alive
            if (cancelled) return
            dispatch({ type: A.SESSION_READY, sessionId: stored })
          }
        } catch {
          // Network error during ping — still use stored id optimistically
          if (cancelled) return
          dispatch({ type: A.SESSION_READY, sessionId: stored })
        }
      } else {
        try {
          const data = await createSession()
          if (cancelled) return
          sessionStorage.setItem(SESSION_KEY, data.session_id)
          dispatch({ type: A.SESSION_READY, sessionId: data.session_id })
        } catch (err) {
          // If session creation fails, generate a client-side fallback UUID
          if (cancelled) return
          const fallback = crypto.randomUUID()
          sessionStorage.setItem(SESSION_KEY, fallback)
          dispatch({ type: A.SESSION_READY, sessionId: fallback })
        }
      }
    }

    bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  // ── send ─────────────────────────────────────────────────────────────────
  const send = useCallback(
    async (text) => {
      const trimmed = String(text).trim()
      if (!trimmed || state.pending || !state.sessionId) return

      const id = String(++idCounter.current)
      dispatch({ type: A.SEND_START, id, text: trimmed })

      try {
        const data = await sendMessage(state.sessionId, trimmed)
        dispatch({ type: A.SEND_SUCCESS, id, data })
      } catch (err) {
        dispatch({
          type: A.SEND_ERROR,
          id,
          error: S.errorNetwork(err.message),
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
      dispatch({ type: A.RESET, sessionId: data.session_id })
    } catch {
      const fallback = crypto.randomUUID()
      sessionStorage.setItem(SESSION_KEY, fallback)
      dispatch({ type: A.RESET, sessionId: fallback })
    }
  }, [state.sessionId])

  return { state, send, reset }
}
