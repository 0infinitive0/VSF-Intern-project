/**
 * use-chat-session.ts — single useReducer managing the entire chat state.
 *
 * Session lifecycle:
 *   - On mount: try to rehydrate session_id from sessionStorage, then ping it.
 *     Only a 404 (the server genuinely lost it) starts a new session silently
 *     — see resolveBootstrapSession for the full decision table.
 *   - startNew(): create a new session, no DELETE — the old one stays persisted
 *     and stays in the history rail (deleting a conversation is a separate,
 *     explicit action against session-client.ts's deleteSession()).
 *   - restore(sessionId): hydrate state from a past session's persisted data.
 *
 * Elapsed timer: started when pending=true, cleared in the finally block.
 */

import { useReducer, useEffect, useRef, useCallback } from 'react'
import {
  changeHotel as changeHotelRequest,
  createSession,
  pingSession,
  selectHotel as selectHotelRequest,
  sendMessage,
} from '../api/chat-client'
import type { CreateSessionResponse, SessionPing } from '../api/chat-client'
import { restoreSession } from '../api/session-client'
import { sendMessageStream, StreamUnsupported } from '../api/stream-client'
import i18n from '../i18n'
import { appendReasoning, applyPhaseToGroups, completeGroups } from '../lib/thinking-groups'
import { thinkingLines, type Translate } from '../lib/thinking-lines'
import type {
  ChatMessage,
  ChatState,
  PlannerChatResponse,
  PhaseFacts,
  PhaseKey,
  SessionRestore,
} from '../types'

/**
 * `thinkingLines` takes the narrow `Translate` shape so it stays a pure function
 * in tests; i18next's own `t` carries far richer overloads than that. Adapting
 * here keeps the cast in one place instead of at every call.
 */
const translate: Translate = (key, params) =>
  i18n.t(key, params as Record<string, unknown>) as string

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
  hotelFilterData: { minPrice: null, maxPrice: null, hotelAmenities: [], allPreferences: [], activePreferences: [] },
  suggestedPlaces: [],
  tripPlan: null,
  intake: null,
  pending: false,
  hotelsLoading: false,
  elapsedMs: 0,
  error: null,
  streamingText: '',
  phases: [], thinking: [],
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
  | { type: 'HOTEL_SELECTION_START'; id: string; text: string; turnId: number }
  | { type: 'HOTEL_SELECTION_SUCCESS'; data: PlannerChatResponse; turnId: number }
  | { type: 'HOTEL_SELECTION_ERROR'; error: string; turnId: number }
  | { type: 'TICK' }
  | { type: 'RESET'; sessionId: string }
  | { type: 'RESTORE'; sessionId: string; data: SessionRestore }
  | { type: 'STREAM_PHASE'; key: PhaseKey; at: number; facts: PhaseFacts; turnId: number }
  | { type: 'STREAM_DELTA'; text: string; turnId: number }
  | { type: 'STREAM_REASONING'; text: string; phaseKey: string; turnId: number }
  // Dedicated hotels/change round-trip (step-navigator.tsx's "đổi khách sạn"
  // action) — never part of the chat turn machinery: no message, no LLM call,
  // just a hotel-list refresh. Own pending flag (`hotelsLoading`) so Composer/
  // elapsed-timer/streaming state never react to it.
  | { type: 'HOTELS_CHANGE_START' }
  | { type: 'HOTELS_CHANGE_SUCCESS'; data: PlannerChatResponse }
  | { type: 'HOTELS_CHANGE_ERROR'; error: string }

function applyPlannerResponse(state: ChatState, data: PlannerChatResponse, message?: ChatMessage): ChatState {
  return {
    ...state,
    pending: false,
    elapsedMs: 0,
    // The turn is over, so nothing can still be running. Without this the last
    // step kept its spinner forever, under a header reading "finished".
    thinking: completeGroups(state.thinking),
    messages: message ? [...state.messages, message] : state.messages,
    suggestions: data.suggestions || [],
    hotelOptions: data.hotel_options || [],
    suggestedPlaces: data.suggested_places || [],
    hotelFilterData: {
      minPrice: data.compound_min_price ?? null,
      maxPrice: data.compound_max_price ?? null,
      hotelAmenities: data.hotel_amenities ?? [],
      allPreferences: data.all_preferences ?? [],
      activePreferences: data.active_preferences ?? [],
    },
    tripPlan: data.trip_plan || state.tripPlan,
    intake: data.intake || state.intake,
    error: null,
    streamingText: '',
    // `phases` clears — the right-hand panel is a live progress strip and has
    // nothing to show between turns. `thinking` does NOT: it stays with the
    // answer it produced, and is cleared when the next turn starts instead.
    phases: [],
  }
}

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
        suggestedPlaces: [],
        hotelFilterData: INITIAL_STATE.hotelFilterData,
        streamingText: '',
        phases: [], thinking: [],
      }

    case 'HOTEL_SELECTION_START':
      if (action.turnId !== state.turnId) return state
      return {
        ...state,
        pending: true,
        elapsedMs: 0,
        error: null,
        messages: [
          ...state.messages,
          { id: action.id, role: 'user', text: action.text, stage: 'planned', at: new Date().toISOString() },
        ],
        suggestions: [],
        hotelOptions: [],
        suggestedPlaces: [],
        hotelFilterData: INITIAL_STATE.hotelFilterData,
        streamingText: '',
        phases: [], thinking: [],
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
        // Nothing streamed for this turn, so the reply arrived whole. Reveal it
        // progressively rather than letting it snap in, which made deterministic
        // answers feel like a different assistant from the streamed ones.
        typewriter: !state.streamingText,
        at: new Date().toISOString(),
      }
      return applyPlannerResponse(state, data, newMsg)
    }

    case 'HOTEL_SELECTION_SUCCESS': {
      if (action.turnId !== state.turnId) return state
      const { data } = action
      const newMsg = {
        id: `${state.messages[state.messages.length - 1]?.id ?? 'hotel_selection'}_ai`,
        role: 'ai' as const,
        text: data.reply,
        stage: data.stage,
        isError: data.stage === 'error',
        at: new Date().toISOString(),
      }
      return applyPlannerResponse(state, data, newMsg)
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
        phases: [], thinking: [],
      }

    case 'HOTEL_SELECTION_ERROR':
      if (action.turnId !== state.turnId) return state
      return { ...state, pending: false, elapsedMs: 0, error: action.error, streamingText: '', phases: [], thinking: [] }

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
          // Carried through as facts; the sentences are rebuilt at render time
          // in whatever language the reader is in now.
          thinkingTrace: (m.thinking_trace ?? undefined) as ChatMessage['thinkingTrace'],
          // Known limitation, not an oversight: a restored bubble can never be
          // marked as an error today, because `chat_messages` has no `stage`
          // column (backend/scripts/database_schema.sql) and
          // `session_store.restored_messages` therefore hardcodes "intake" for
          // every row. A live turn does get error styling (its `stage` comes
          // straight off the response). Storing the real stage needs a
          // migration; this line is already correct for the day that lands.
          isError: m.stage === 'error',
          at: m.at || undefined,
        })),
        suggestions: data.suggestions || [],
        hotelOptions: data.hotel_options || [],
        hotelFilterData: {
          ...INITIAL_STATE.hotelFilterData,
          hotelAmenities: data.hotel_amenities ?? [],
        },
        tripPlan: data.trip_plan ?? null,
        intake: data.intake ?? null,
      }
    }

    case 'STREAM_PHASE': {
      if (action.turnId !== state.turnId) return state
      // `phases` stays exactly as it was — the right-hand progress panel reads
      // it and is not part of this change. `thinking` is a parallel view of the
      // same frames, grouped for the chat column.
      const lines = thinkingLines(translate, action.key, action.facts)
      // A step now reports twice — it started, then it finished. The
      // right-hand panel lists one row per entry and treats the last as the one
      // in progress, so appending both listed every step twice. The opening
      // edge is the one that matches what that panel means by a row.
      const opensAStep = action.facts.status !== 'completed'
      return {
        ...state,
        phases: opensAStep ? [...state.phases, { key: action.key, at: action.at }] : state.phases,
        thinking: applyPhaseToGroups(state.thinking, action.key, lines, action.facts.status),
      }
    }

    case 'STREAM_DELTA':
      if (action.turnId !== state.turnId) return state
      return { ...state, streamingText: state.streamingText + action.text }

    case 'STREAM_REASONING':
      if (action.turnId !== state.turnId) return state
      return { ...state, thinking: appendReasoning(state.thinking, action.phaseKey, action.text) }

    case 'HOTELS_CHANGE_START':
      return { ...state, hotelsLoading: true, error: null }

    case 'HOTELS_CHANGE_SUCCESS': {
      const { data } = action
      return {
        ...state,
        hotelsLoading: false,
        hotelOptions: data.hotel_options || [],
        hotelFilterData: {
          ...state.hotelFilterData,
          hotelAmenities: data.hotel_amenities ?? [],
          allPreferences: data.all_preferences ?? [],
          activePreferences: data.active_preferences ?? [],
        },
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

// ── Bootstrap ─────────────────────────────────────────────────────────────────

export interface BootstrapDeps {
  stored: string | null
  ping: (sessionId: string) => Promise<SessionPing>
  create: () => Promise<CreateSessionResponse>
  fallbackId: () => string
}

/**
 * Decides which session id the app starts on. Pure apart from its injected
 * dependencies, so all four ping outcomes are unit-testable without rendering
 * the hook (no React Testing Library in this project — see INITIAL_STATE).
 *
 * Only ONE outcome may abandon the stored conversation: `gone`, the server
 * saying it has no such session. `unauthorized` is a token problem
 * AuthProvider refreshes on its own (pingSession has already alerted the
 * session-expired bus by then), and `unknown` is no evidence at all — both
 * keep the stored id rather than discarding a live conversation.
 *
 * `persist: true` means the returned id is new and the caller must write it to
 * sessionStorage; storage stays with the caller so this function has no
 * side effects of its own.
 */
export async function resolveBootstrapSession({
  stored,
  ping,
  create,
  fallbackId,
}: BootstrapDeps): Promise<{ sessionId: string; persist: boolean }> {
  if (stored) {
    if ((await ping(stored)) !== 'gone') return { sessionId: stored, persist: false }
    try {
      return { sessionId: (await create()).session_id, persist: true }
    } catch {
      // The replacement could not be created — keep the stored id rather than
      // leaving the app with none; the next turn will 404 loudly if it really
      // is gone.
      return { sessionId: stored, persist: false }
    }
  }

  try {
    return { sessionId: (await create()).session_id, persist: true }
  } catch {
    // Backend unreachable on a first visit: a client-side id still lets the UI
    // mount, and the server adopts it on the first successful turn.
    return { sessionId: fallbackId(), persist: true }
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
  // Bootstrap (createSession()) is async, so there's a window right after
  // mount where sessionId is still null — e.g. the empty-conversation quick
  // suggestion chips are clickable in that window. send() awaits this so a
  // tap/type during that window still reaches the backend once the session
  // resolves, instead of silently no-op'ing on the `!state.sessionId` guard.
  const sessionReadyRef = useRef<Promise<string> | null>(null)
  const resolveSessionReadyRef = useRef<((sessionId: string) => void) | null>(null)
  if (!sessionReadyRef.current) {
    sessionReadyRef.current = new Promise<string>((resolve) => {
      resolveSessionReadyRef.current = resolve
    })
  }

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
  // Rehydrates from sessionStorage when possible — see resolveBootstrapSession
  // for the full decision table on when a stored id is trusted vs. discarded.
  // `persist: false` means we're resuming a session that already has
  // conversation history server-side — SESSION_READY alone only sets
  // state.sessionId, it never re-populates messages/tripPlan/intake (those
  // live only in React state, wiped by the reload itself), so without this
  // RESTORE call every reload looked like a brand new draft even though the
  // backend kept the same session_id. A genuinely new session (persist: true)
  // has nothing to restore, so it stays on plain SESSION_READY.
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      const { sessionId, persist } = await resolveBootstrapSession({
        stored: sessionStorage.getItem(SESSION_KEY),
        ping: pingSession,
        create: createSession,
        fallbackId: () => crypto.randomUUID(),
      })
      if (cancelled) return
      if (persist) {
        sessionStorage.setItem(SESSION_KEY, sessionId)
        dispatch({ type: 'SESSION_READY', sessionId })
      } else {
        const data = await restoreSession(sessionId)
        if (cancelled) return
        if (data) {
          dispatch({ type: 'RESTORE', sessionId, data })
        } else {
          // Restore failed (network blip, or the session died between the
          // ping and this call) — still surface the id so the app can work,
          // just without prior history.
          dispatch({ type: 'SESSION_READY', sessionId })
        }
      }
      resolveSessionReadyRef.current?.(sessionId)
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
      if (!trimmed || state.pending) return

      // Bootstrap may still be in flight (sessionId null) — wait for it
      // rather than dropping the send, see sessionReadyRef's comment above.
      // Non-null: sessionReadyRef.current is populated synchronously on the
      // hook's first render, before send() can ever be invoked.
      const sessionId = state.sessionId ?? (await sessionReadyRef.current!)

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
          sessionId,
          trimmed,
          i18n.language,
          {
            onPhase: (key, at, facts) =>
              dispatch({ type: 'STREAM_PHASE', key: key as PhaseKey, at, facts: (facts ?? {}) as PhaseFacts, turnId }),
            onDelta: (deltaText) => dispatch({ type: 'STREAM_DELTA', text: deltaText, turnId }),
            onReasoning: (text, phaseKey) =>
              dispatch({ type: 'STREAM_REASONING', text, phaseKey, turnId }),
          },
          controller.signal,
        )
        dispatch({ type: 'SEND_SUCCESS', id, data, turnId })
      } catch (err) {
        if (err instanceof StreamUnsupported) {
          try {
            const data = await sendMessage(sessionId, trimmed, i18n.language)
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
  const selectHotel = useCallback(
    async (hotelId: string | number, selectionMessage: string) => {
      if (state.pending || !state.sessionId) return

      const turnId = state.turnId
      const id = `hotel_selection_${++idCounter.current}`
      dispatch({ type: 'HOTEL_SELECTION_START', id, text: selectionMessage, turnId })
      try {
        const data = await selectHotelRequest(state.sessionId, hotelId, selectionMessage)
        dispatch({ type: 'HOTEL_SELECTION_SUCCESS', data, turnId })
      } catch (error) {
        dispatch({
          type: 'HOTEL_SELECTION_ERROR',
          error: i18n.t('errorNetwork', { msg: error instanceof Error ? error.message : String(error) }),
          turnId,
        })
      }
    },
    [state.pending, state.sessionId, state.turnId],
  )

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

  return { state, send, selectHotel, startNew, restore, changeHotel }
}
