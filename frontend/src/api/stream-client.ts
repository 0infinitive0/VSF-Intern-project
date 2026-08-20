/**
 * stream-client.ts — SSE transport for POST /planner_chat/stream
 * (docs/chat_api_contract.md §Streaming; plan 260806-1602-streaming-chat-messages
 * Phase 5). Sibling of chat-client.ts's sendMessage(): no component calls
 * fetch/ReadableStream directly, this file owns it.
 *
 * Not EventSource: the chat turn is a POST with a JSON body, and EventSource
 * only ever issues GET. Frames are parsed by hand from a fetch() body stream.
 */

import type { PlannerChatResponse, Suggestion } from '../types'
import { authHeaders } from './auth-headers'
import { reportSessionExpired } from '../auth/session-expired-bus'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

/**
 * Thrown ONLY when the stream endpoint request fails before the server has
 * accepted it — `fetch()` itself rejecting, a non-2xx status, or the wrong
 * content-type. The caller's only safe recovery is to replay the turn
 * through the plain POST endpoint. Never thrown once a 200 `text/event-stream`
 * response has been received (see sendMessageStream): by then the turn is
 * already running server-side, and replaying would send the same message
 * twice — that holds regardless of whether any frame was actually read
 * afterward.
 */
export class StreamUnsupported extends Error {}

/**
 * Incrementally parse SSE frames out of a fetch() response body.
 *
 * Frames are separated by a blank line; a line starting with ':' is a
 * comment (`: open`, `: heartbeat`) and carries no event/data — skipped.
 * Chunk boundaries from the network never align with frame boundaries, so
 * this keeps a trailing partial frame across reads instead of assuming one
 * `read()` = one frame.
 */
export async function* parseSse(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<{ event: string; data: unknown }> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal.aborted) return
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let sep: number
      // eslint-disable-next-line no-cond-assign
      while ((sep = buffer.indexOf('\n\n')) !== -1) {
        const rawFrame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const frame = parseFrame(rawFrame)
        if (frame) yield frame
      }
    }
    // Final partial frame with no trailing blank line (stream ended right
    // after the last frame's data, no closing \n\n before the socket closed).
    const trailing = parseFrame(buffer)
    if (trailing) yield trailing
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(raw: string): { event: string; data: unknown } | null {
  const lines = raw.split('\n').filter((l) => l.length > 0)
  if (lines.length === 0) return null
  if (lines.every((l) => l.startsWith(':'))) return null // comment-only frame

  let event = ''
  let dataLine = ''
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    else if (line.startsWith('data:')) dataLine = line.slice('data:'.length).trim()
  }
  if (!event || !dataLine) return null

  try {
    return { event, data: JSON.parse(dataLine) }
  } catch {
    return null // malformed frame — drop it, do not crash the stream
  }
}

export interface StreamHandlers {
  onPhase?: (key: string, at: number, extra?: Record<string, unknown>) => void
  onDelta?: (text: string) => void
  /**
   * The model's summary of its own reasoning. Always English, and a valid turn
   * may never call this — see docs/chat_api_contract.md §Streaming.
   */
  onReasoning?: (text: string, phaseKey: string) => void
  /**
   * Fires once, at the `final` frame — the reply itself, before the stream
   * has necessarily closed. Callers that want to stop showing "pending" the
   * moment the reply lands (rather than waiting for the whole stream, which
   * may still carry a `suggestions` frame after this) should hook this
   * instead of the resolved promise.
   */
  onFinal?: (data: PlannerChatResponse) => void
  /**
   * Fires at most once, on the `suggestions` frame that `routes.py` sends
   * AFTER `final` (docs/chat_api_contract.md §Streaming) — never called at
   * all when the turn produced no chips (LLM failure/timeout/empty result,
   * or a turn whose worker isn't gated for suggestions). That absence is a
   * valid, designed state, not something this handler needs to distinguish
   * from "not yet arrived".
   */
  onSuggestions?: (suggestions: Suggestion[]) => void
}

/**
 * Run one chat turn over SSE. Resolves with the `final` payload once the
 * stream closes — which is AFTER any `suggestions` frame that follows
 * `final` (§Streaming's one documented exception to "final/error is the
 * last frame"). Callers that need the reply the moment it lands, without
 * waiting for `suggestions`, should use `onFinal` rather than the resolved
 * value.
 *
 * Throws `StreamUnsupported` ONLY for failures that happen before a valid
 * response is established: `fetch()` itself rejecting (network unreachable),
 * a non-2xx status, or the wrong content-type. `routes.py`'s
 * `planner_chat_stream` submits the turn to its worker pool BEFORE
 * constructing the `StreamingResponse` it returns — so once a 200 with
 * `text/event-stream` has come back, the turn is already running
 * server-side, whether or not any frame has been read yet. Every failure
 * from that point on (including `firstFrameTimeoutMs` firing with zero
 * frames received — e.g. a proxy buffering the whole stream) throws a plain
 * `Error`: the caller must NOT replay the message.
 */
export async function sendMessageStream(
  sessionId: string,
  message: string,
  language: string,
  handlers: StreamHandlers,
  signal: AbortSignal,
  firstFrameTimeoutMs = 5000,
): Promise<PlannerChatResponse> {
  // One controller drives both the outer caller's abort AND the internal
  // first-frame timeout, and is what actually gets passed to fetch() — an
  // AbortSignal aborted mid-body-read does interrupt a pending
  // reader.read() (unlike aborting a signal nothing was ever given to).
  const controller = new AbortController()
  const onOuterAbort = () => controller.abort()
  signal.addEventListener('abort', onOuterAbort)
  let receivedAnyFrame = false
  const firstFrameTimer = setTimeout(() => {
    if (!receivedAnyFrame) controller.abort()
  }, firstFrameTimeoutMs)

  let res: Response
  try {
    res = await fetch(BASE + '/planner_chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
      body: JSON.stringify({ session_id: sessionId, message, language }),
      signal: controller.signal,
    })
  } catch (err) {
    clearTimeout(firstFrameTimer)
    signal.removeEventListener('abort', onOuterAbort)
    throw new StreamUnsupported(err instanceof Error ? err.message : String(err))
  }

  if (res.status === 401) reportSessionExpired()

  if (!res.ok || !res.body || !(res.headers.get('content-type') || '').startsWith('text/event-stream')) {
    clearTimeout(firstFrameTimer)
    signal.removeEventListener('abort', onOuterAbort)
    throw new StreamUnsupported(`stream endpoint unavailable (status ${res.status})`)
  }

  // From here on the server has accepted and already started the turn —
  // every exit below is a plain Error, never StreamUnsupported.
  let finalData: PlannerChatResponse | null = null
  try {
    for await (const frame of parseSse(res.body, controller.signal)) {
      receivedAnyFrame = true
      clearTimeout(firstFrameTimer)

      switch (frame.event) {
        case 'phase': {
          const d = frame.data as { key: string; at: number; [k: string]: unknown }
          handlers.onPhase?.(d.key, d.at, d)
          break
        }
        case 'delta': {
          const d = frame.data as { text: string }
          handlers.onDelta?.(d.text)
          break
        }
        case 'reasoning': {
          const d = frame.data as { text: string; key: string }
          handlers.onReasoning?.(d.text, d.key)
          break
        }
        case 'final':
          // No `return` here (Phase 3, plan
          // 260819-1554-llm-grounded-chat-suggestions): a `suggestions` frame
          // can follow `final`, and stopping the read here would drop it —
          // keep draining until the stream actually closes.
          finalData = frame.data as PlannerChatResponse
          handlers.onFinal?.(finalData)
          break
        case 'suggestions': {
          const d = frame.data as { suggestions: Suggestion[] }
          handlers.onSuggestions?.(d.suggestions)
          break
        }
        case 'error': {
          const d = frame.data as { detail: string }
          throw new Error(d.detail)
        }
        default:
          break // unknown event name — ignore, forward-compatible
      }
    }
  } catch (err) {
    // The reply already landed (`onFinal` already fired) — a failure while
    // draining the trailing `suggestions` frame (network drop, an aborted
    // read from a session switch) must not turn a delivered reply into a
    // user-visible error. The trailing frame is best-effort; the reply is
    // not. A genuine `error` frame is expected strictly BEFORE `final` per
    // contract, so `finalData` is null in that real case and this still
    // rethrows.
    if (finalData) return finalData
    throw err
  } finally {
    clearTimeout(firstFrameTimer)
    signal.removeEventListener('abort', onOuterAbort)
  }

  if (finalData) return finalData

  // Stream ended (body closed, or the first-frame timeout aborted it) without
  // ever sending a terminal frame — this violates the contract (exactly one
  // of final|error), but the turn may still be running/have run
  // server-side, so this must NOT be treated as "safe to retry via POST".
  throw new Error(
    receivedAnyFrame
      ? 'stream ended without a final response'
      : 'stream closed before any frame arrived',
  )
}
