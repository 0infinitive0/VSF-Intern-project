import { beforeAll, describe, expect, it } from 'vitest'
import type { chatSessionReducer as ChatSessionReducer, INITIAL_STATE as InitialStateType } from './use-chat-session'
import type { ChatState, SessionRestore } from '../types'

// use-chat-session.ts imports ../i18n, which reads localStorage at
// module-load time — this test file runs in vitest's plain Node
// environment (no jsdom in this project), so the module must be imported
// dynamically, after stubbing the minimal API it needs.
let chatSessionReducer: typeof ChatSessionReducer
let INITIAL_STATE: typeof InitialStateType

beforeAll(async () => {
  globalThis.localStorage ??= {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
    clear: () => {},
    key: () => null,
    length: 0,
  } as Storage
  ;({ chatSessionReducer, INITIAL_STATE } = await import('./use-chat-session'))
})

function restoreDataFor(sessionId: string): SessionRestore {
  return {
    session_id: sessionId,
    messages: [
      { role: 'user', text: 'đi đà nẵng', stage: null, at: '2026-08-01T00:00:00Z' },
      { role: 'assistant', text: 'ok, khi nào đi?', stage: 'intake', at: '2026-08-01T00:00:05Z' },
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
