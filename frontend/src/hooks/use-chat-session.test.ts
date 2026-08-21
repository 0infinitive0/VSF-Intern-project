import { beforeAll, describe, expect, it, vi } from 'vitest'
import type {
  chatSessionReducer as ChatSessionReducer,
  INITIAL_STATE as InitialStateType,
  resolveBootstrapSession as ResolveBootstrapSession,
} from './use-chat-session'
import type { ChatState, SessionRestore } from '../types'

// use-chat-session.ts imports ../i18n, which reads localStorage at
// module-load time — this test file runs in vitest's plain Node
// environment (no jsdom in this project), so the module must be imported
// dynamically, after stubbing the minimal API it needs.
let chatSessionReducer: typeof ChatSessionReducer
let INITIAL_STATE: typeof InitialStateType
let resolveBootstrapSession: typeof ResolveBootstrapSession

describe('chatSessionReducer â€” direct hotel selection', () => {
  it('records the named hotel choice and concise completion message', () => {
    const before: ChatState = {
      ...INITIAL_STATE,
      sessionId: 's1',
      messages: [{ id: 'existing', role: 'ai', text: 'Existing itinerary', stage: 'planned' }],
    }
    const started = chatSessionReducer(before, {
      type: 'HOTEL_SELECTION_START', id: 'selection-1', text: 'Chọn khách sạn New hotel', turnId: before.turnId,
    })
    const next = chatSessionReducer(started, {
      type: 'HOTEL_SELECTION_SUCCESS',
      turnId: before.turnId,
      data: {
        session_id: 's1', reply: 'New itinerary is ready', suggestions: [], stage: 'planned', hotel_options: [],
        trip_plan: { status: 'Draft', destination: 'Hồ Chí Minh', duration_days: 2, start_date: null, end_date: null, number_of_adults: 2, hotel: { id: 'hotel-2', name: 'New hotel' }, days: [], adjustments: [] },
      },
    })

    expect(next.pending).toBe(false)
    expect(next.messages.map((message) => message.text)).toEqual([
      'Existing itinerary',
      'Chọn khách sạn New hotel',
      'New itinerary is ready',
    ])
    expect(next.messages[2].stage).toBe('planned')
    expect(next.tripPlan?.hotel?.id).toBe('hotel-2')
  })
})

describe('chatSessionReducer hotel filter API data', () => {
  it('keeps server-provided price bounds and active preferences with hotel options', () => {
    const next = chatSessionReducer(INITIAL_STATE, {
      type: 'SEND_SUCCESS', id: 'filters', turnId: INITIAL_STATE.turnId,
      data: {
        session_id: 's1', reply: 'Hotels found', suggestions: [], stage: 'hotel_options', trip_plan: null,
        hotel_options: [{ index: 1, id: 'hotel-1', name: 'Hotel A', average_nightly_price: 1_200_000 }],
        compound_min_price: 800_000, compound_max_price: 2_000_000,
        all_preferences: [{ id: 'pool', label: 'Pool' }],
        active_preferences: [{ id: 'pool', label: 'Pool', polarity: 'require' }],
      },
    })

    expect(next.hotelFilterData).toEqual({
      minPrice: 800_000, maxPrice: 2_000_000,
      hotelAmenities: [],
      allPreferences: [{ id: 'pool', label: 'Pool' }],
      activePreferences: [{ id: 'pool', label: 'Pool', polarity: 'require' }],
    })
  })
})

beforeAll(async () => {
  globalThis.localStorage ??= {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
    clear: () => {},
    key: () => null,
    length: 0,
  } as Storage
  ;({ chatSessionReducer, INITIAL_STATE, resolveBootstrapSession } = await import('./use-chat-session'))
})

// ── Bootstrap decision table ────────────────────────────────────────────────
// The stored-session ping has four possible outcomes and only ONE of them may
// abandon the stored conversation. 401 in particular is a token problem that
// AuthProvider refreshes within seconds — creating a new session there throws
// away a live conversation for a reason that fixes itself.

describe('resolveBootstrapSession', () => {
  const created = { session_id: 'server-new', created_at: '2026-08-16T00:00:00Z' }

  function deps(overrides: Partial<Parameters<typeof resolveBootstrapSession>[0]> = {}) {
    return {
      stored: 'stored-id',
      ping: vi.fn().mockResolvedValue('alive' as const),
      create: vi.fn().mockResolvedValue(created),
      fallbackId: () => 'fallback-id',
      ...overrides,
    }
  }

  it('keeps the stored session when the ping says alive', async () => {
    const d = deps()
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'stored-id', persist: false })
    expect(d.create).not.toHaveBeenCalled()
  })

  it('creates a new session when the server no longer has the stored one (404)', async () => {
    const d = deps({ ping: vi.fn().mockResolvedValue('gone' as const) })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'server-new', persist: true })
    expect(d.create).toHaveBeenCalledOnce()
  })

  it('keeps the stored session on 401 instead of silently starting a new one', async () => {
    const d = deps({ ping: vi.fn().mockResolvedValue('unauthorized' as const) })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'stored-id', persist: false })
    expect(d.create).not.toHaveBeenCalled()
  })

  it('keeps the stored session optimistically when the ping itself fails', async () => {
    const d = deps({ ping: vi.fn().mockResolvedValue('unknown' as const) })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'stored-id', persist: false })
    expect(d.create).not.toHaveBeenCalled()
  })

  it('keeps the stored session when the replacement session cannot be created', async () => {
    const d = deps({
      ping: vi.fn().mockResolvedValue('gone' as const),
      create: vi.fn().mockRejectedValue(new Error('backend down')),
    })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'stored-id', persist: false })
  })

  it('creates a session when nothing is stored, without pinging', async () => {
    const d = deps({ stored: null })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'server-new', persist: true })
    expect(d.ping).not.toHaveBeenCalled()
  })

  it('falls back to a client-side id when nothing is stored and creation fails', async () => {
    const d = deps({ stored: null, create: vi.fn().mockRejectedValue(new Error('backend down')) })
    await expect(resolveBootstrapSession(d)).resolves.toEqual({ sessionId: 'fallback-id', persist: true })
  })
})

function restoreDataFor(sessionId: string): SessionRestore {
  return {
    session_id: sessionId,
    messages: [
      { role: 'user', text: 'đi đà nẵng', stage: null, at: '2026-08-01T00:00:00Z', thinking_trace: null },
      // `null` is the ordinary case: every message written before the column
      // existed carries it, and restore must render those unchanged.
      { role: 'assistant', text: 'ok, khi nào đi?', stage: 'intake', at: '2026-08-01T00:00:05Z', thinking_trace: null },
    ],
    suggestions: [],
    stage: 'intake',
    hotel_options: [],
    trip_plan: null,
    intake: null,
  }
}

describe('chatSessionReducer — RESTORE', () => {
  it('maps wire role "assistant" to MessageRole "ai" and keeps "user" as-is', () => {
    const next = chatSessionReducer(INITIAL_STATE, { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') })
    expect(next.messages.map((m) => m.role)).toEqual(['user', 'ai'])
  })

  it('clears streamingText, phases, and error from the previous session', () => {
    const dirty: ChatState = {
      ...INITIAL_STATE,
      sessionId: 's1',
      streamingText: 'partial reply...',
      phases: [{ key: 'received', at: 1 }],
      error: 'boom',
      elapsedMs: 4000,
    }
    const next = chatSessionReducer(dirty, { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') })
    expect(next.streamingText).toBe('')
    expect(next.phases).toEqual([])
    expect(next.error).toBeNull()
    expect(next.elapsedMs).toBe(0)
    expect(next.sessionId).toBe('s2')
  })

  it('bumps turnId so any turn in flight before the restore is now stale', () => {
    const before: ChatState = { ...INITIAL_STATE, sessionId: 's1', turnId: 5 }
    const next = chatSessionReducer(before, { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') })
    expect(next.turnId).toBe(6)
  })
})

describe('chatSessionReducer — stale-turn guard', () => {
  it('ignores SEND_SUCCESS tagged with a turnId older than the current one', () => {
    const restored = chatSessionReducer(
      { ...INITIAL_STATE, sessionId: 's1' },
      { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') },
    )
    const staleReply = chatSessionReducer(restored, {
      type: 'SEND_SUCCESS',
      id: '1',
      turnId: 0, // the turnId captured by send() before the RESTORE above
      data: { session_id: 's1', reply: 'stale reply', suggestions: [], stage: null, hotel_options: [], trip_plan: null },
    })
    expect(staleReply).toBe(restored) // unchanged — same reference, not just equal
    expect(staleReply.messages.some((m) => m.text === 'stale reply')).toBe(false)
  })

  it('ignores STREAM_DELTA for a stale turn but applies it for the current one', () => {
    const restored = chatSessionReducer(
      { ...INITIAL_STATE, sessionId: 's1' },
      { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') },
    )
    const staleDelta = chatSessionReducer(restored, { type: 'STREAM_DELTA', text: 'stale', turnId: 0 })
    expect(staleDelta).toBe(restored)

    const currentDelta = chatSessionReducer(restored, { type: 'STREAM_DELTA', text: 'live', turnId: restored.turnId })
    expect(currentDelta.streamingText).toBe('live')
  })

  it('ignores STREAM_SUGGESTIONS for a stale turn but applies it for the current one', () => {
    const restored = chatSessionReducer(
      { ...INITIAL_STATE, sessionId: 's1' },
      { type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2') },
    )
    const chip = { label: 'Lọc theo giá', value: 'Lọc theo giá' }

    const staleSuggestions = chatSessionReducer(restored, {
      type: 'STREAM_SUGGESTIONS',
      suggestions: [chip],
      turnId: 0,
    })
    expect(staleSuggestions).toBe(restored)
    expect(staleSuggestions.suggestions).toEqual(restored.suggestions)

    const currentSuggestions = chatSessionReducer(restored, {
      type: 'STREAM_SUGGESTIONS',
      suggestions: [chip],
      turnId: restored.turnId,
    })
    expect(currentSuggestions.suggestions).toEqual([chip])
  })

  // The scenario the turnId design specifically defends against: sessionId
  // alone can't tell an ABA switch apart from "nothing happened". A→B→A
  // leaves sessionId back at "A", but a reply captured for the FIRST "A"
  // episode must still be recognized as stale during the second one.
  it('drops a stale reply from before an A→B→A round trip even though sessionId matches again', () => {
    const onA = { ...INITIAL_STATE, sessionId: 'A' } // turnId 0 — this is what send() would have captured
    const capturedTurnId = onA.turnId

    const onB = chatSessionReducer(onA, { type: 'RESTORE', sessionId: 'B', data: restoreDataFor('B') })
    const backOnA = chatSessionReducer(onB, { type: 'RESTORE', sessionId: 'A', data: restoreDataFor('A') })
    expect(backOnA.sessionId).toBe('A') // sessionId alone would look identical to onA

    const staleReply = chatSessionReducer(backOnA, {
      type: 'SEND_SUCCESS',
      id: '1',
      turnId: capturedTurnId,
      data: { session_id: 'A', reply: 'stale reply from first A episode', suggestions: [], stage: null, hotel_options: [], trip_plan: null },
    })
    expect(staleReply).toBe(backOnA)
  })
})

describe('chatSessionReducer — thinking groups', () => {
  const withThinking = (): ChatState =>
    chatSessionReducer(
      { ...INITIAL_STATE, pending: true },
      { type: 'STREAM_PHASE', key: 'intake_check', at: 1, facts: { intent: 'update_trip' }, turnId: 0 },
    )

  it('builds a group from a phase frame and its facts', () => {
    const next = withThinking()

    expect(next.thinking).toHaveLength(1)
    expect(next.thinking[0].key).toBe('analyze')
    expect(next.thinking[0].lines).toHaveLength(1)
  })

  it('creates the group even when the frame carried no facts', () => {
    const next = chatSessionReducer(INITIAL_STATE, {
      type: 'STREAM_PHASE', key: 'persisting', at: 1, facts: {}, turnId: 0,
    })

    expect(next.thinking).toHaveLength(1)
    expect(next.thinking[0].lines).toEqual([])
  })

  it('leaves `phases` behaving exactly as before', () => {
    const next = withThinking()

    expect(next.phases).toEqual([{ key: 'intake_check', at: 1 }])
  })

  it('accumulates reasoning onto the running group', () => {
    const next = chatSessionReducer(withThinking(), {
      type: 'STREAM_REASONING', text: 'Checking dates', phaseKey: 'generating', turnId: 0,
    })

    expect(next.thinking.find((g) => g.key === 'reply')?.reasoning).toBe('Checking dates')
  })

  it('ignores frames from a turn that is no longer current', () => {
    const state = withThinking()
    const stale = chatSessionReducer(state, {
      type: 'STREAM_PHASE', key: 'hotel_search', at: 2, facts: {}, turnId: 99,
    })

    expect(stale).toBe(state)
  })

  it.each([
    ['SEND_START', { type: 'SEND_START', id: 'm1', text: 'hi' }],
    ['HOTEL_SELECTION_START', { type: 'HOTEL_SELECTION_START', id: 'h1', text: 'Tôi chọn khách sạn 1', turnId: 0 }],
    ['RESET', { type: 'RESET' }],
    ['SEND_ERROR', { type: 'SEND_ERROR', error: 'boom', turnId: 0 }],
  ])('clears thinking on %s, so it cannot bleed into the next turn', (_label, action) => {
    const dirty = withThinking()
    expect(dirty.thinking).not.toHaveLength(0)

    const next = chatSessionReducer(dirty, action as never)

    expect(next.thinking).toEqual([])
  })

  it('clears thinking when restoring another session', () => {
    const dirty = withThinking()

    const next = chatSessionReducer(dirty, {
      type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2'),
    })

    expect(next.thinking).toEqual([])
  })
})

describe('chatSessionReducer — typewriter flag', () => {
  const reply = (data: Partial<Record<string, unknown>> = {}) => ({
    session_id: 'A', reply: 'Mình tìm được 5 khách sạn phù hợp.', suggestions: [],
    stage: 'hotel_options', hotel_options: [], trip_plan: null, ...data,
  })

  it('marks a reply that never streamed, so it is revealed rather than snapped in', () => {
    const next = chatSessionReducer(
      { ...INITIAL_STATE, pending: true, streamingText: '' },
      { type: 'SEND_SUCCESS', id: 'm1', data: reply() as never, turnId: 0 },
    )

    expect(next.messages.at(-1)?.typewriter).toBe(true)
  })

  it('leaves a streamed reply alone — it already arrived a piece at a time', () => {
    const next = chatSessionReducer(
      { ...INITIAL_STATE, pending: true, streamingText: 'Tháng 7 hay' },
      { type: 'SEND_SUCCESS', id: 'm2', data: reply({ reply: 'Tháng 7 hay mưa.' }) as never, turnId: 0 },
    )

    expect(next.messages.at(-1)?.typewriter).toBe(false)
  })

  it('never marks restored history — replaying old messages on reload is theatre', () => {
    const next = chatSessionReducer(INITIAL_STATE, {
      type: 'RESTORE', sessionId: 's2', data: restoreDataFor('s2'),
    })

    expect(next.messages.every((m) => !m.typewriter)).toBe(true)
  })
})

describe('chatSessionReducer — thinking survives the turn', () => {
  const reply = {
    session_id: 'A', reply: 'Xong rồi.', suggestions: [],
    stage: 'planned', hotel_options: [], trip_plan: null,
  }

  const midTurn = (): ChatState =>
    chatSessionReducer(
      { ...INITIAL_STATE, pending: true },
      { type: 'STREAM_PHASE', key: 'intake_check', at: 1, facts: { status: 'started' }, turnId: 0 },
    )

  it('closes every step when the turn ends', () => {
    const running = midTurn()
    expect(running.thinking.some((g) => !g.done)).toBe(true)

    const next = chatSessionReducer(running, {
      type: 'SEND_SUCCESS', id: 'm1', data: reply as never, turnId: 0,
    })

    expect(next.thinking.every((g) => g.done)).toBe(true)
  })

  it('keeps the trace after the answer arrives, rather than clearing it', () => {
    const next = chatSessionReducer(midTurn(), {
      type: 'SEND_SUCCESS', id: 'm1', data: reply as never, turnId: 0,
    })

    expect(next.thinking).toHaveLength(1)
  })

  it('clears it only when the next turn starts', () => {
    const afterAnswer = chatSessionReducer(midTurn(), {
      type: 'SEND_SUCCESS', id: 'm1', data: reply as never, turnId: 0,
    })

    const nextTurn = chatSessionReducer(afterAnswer, {
      type: 'SEND_START', id: 'm2', text: 'câu tiếp theo',
    } as never)

    expect(nextTurn.thinking).toEqual([])
  })
})

describe('chatSessionReducer — one row per step', () => {
  const phase = (key: string, status: 'started' | 'completed') =>
    ({ type: 'STREAM_PHASE', key, at: 1, facts: { status }, turnId: 0 }) as never

  it('does not list a step twice now that it reports both edges', () => {
    // The right-hand panel renders one row per entry and treats the last as the
    // step in progress; appending both edges listed everything twice.
    let state = chatSessionReducer(INITIAL_STATE, phase('intake_check', 'started'))
    state = chatSessionReducer(state, phase('intake_check', 'completed'))

    expect(state.phases.map((p) => p.key)).toEqual(['intake_check'])
  })

  it('still lists a phase a service emits without an edge', () => {
    // `itinerary_build`, `routing_legs` and `persisting` are announced from
    // inside the work and never report a completion.
    const state = chatSessionReducer(INITIAL_STATE, {
      type: 'STREAM_PHASE', key: 'routing_legs', at: 1, facts: { days: 4 }, turnId: 0,
    })

    expect(state.phases.map((p) => p.key)).toEqual(['routing_legs'])
  })

  it('keeps the completed edge for the thinking block, which needs its facts', () => {
    let state = chatSessionReducer(INITIAL_STATE, phase('intake_check', 'started'))
    state = chatSessionReducer(state, {
      type: 'STREAM_PHASE', key: 'intake_check', at: 1,
      facts: { status: 'completed', intent: 'general_question' }, turnId: 0,
    })

    expect(state.thinking).toHaveLength(1)
    expect(state.thinking[0].lines.length).toBeGreaterThan(0)
    expect(state.thinking[0].done).toBe(true)
  })
})
