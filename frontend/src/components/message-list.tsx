import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import MessageBubble from './message-bubble'
import ElapsedSpinner from './elapsed-spinner'
import ThinkingBlock from './thinking-block'
import { groupsFromTrace } from '../lib/thinking-groups'
import { thinkingLines } from '../lib/thinking-lines'
import type { ChatMessage, ThinkingGroup } from '../types'

// Auto-scroll throttle ceiling — token-by-token streaming can dispatch many
// times a second; scrollIntoView on every one of them looks like jitter, not
// a smooth follow.
const SCROLL_THROTTLE_MS = 100

/**
 * MessageList — the scrollable thread of messages. Thread-only (phase-06): the
 * intake widgets / chips / hotel cards live in a fixed rail above the composer,
 * not inside this scroll. Renders the greeting, the bubbles, the in-flow
 * progress indicator while pending (a live streaming bubble once `delta` text
 * starts flowing, or the plain elapsed spinner otherwise), and the trailing
 * intake question that goes with whatever widget the rail is showing.
 *
 * Both frontend-authored bubbles — the greeting and `intakeQuestion` — are the
 * design's own p0..p4 intake prompts, which its ask(step) pushes into the
 * message thread and leaves there permanently. They render here, in the
 * thread, and never inside the widget rail.
 *
 * The greeting is deliberately NOT gated on an empty thread: it is the
 * conversation's opening line, so hiding it the moment the user replies (the
 * old `messages.length === 0` condition) made the first thing the assistant
 * ever said vanish for good.
 *
 * The step-by-step `phase` tick list lives ONLY in stage-generating.tsx's
 * right-hand panel (design reference: data/trip_planner/trip_planner_components)
 * — showing it here too would duplicate the same progress in two places.
 */
export default function MessageList({
  messages,
  pending,
  streamingText,
  thinking = [],
  intakeQuestion = null,
}: {
  messages: ChatMessage[]
  pending: boolean
  streamingText: string
  /** Grouped narration of the running turn. Empty until the first `phase`
   * frame lands, which is the window `ElapsedSpinner` still covers. */
  thinking?: ThinkingGroup[]
  /** Question for the currently-open intake widget, when the backend's own last
   * reply didn't already ask it (see lib/next-intake-field.ts's
   * locallyAdvancedField). Null renders nothing. */
  intakeQuestion?: string | null
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastScrollAt = useRef(0)
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const { t } = useTranslation()

  // Where the trace belongs: directly above the reply it produced, once that
  // reply exists. `thinking` only ever describes the newest turn, so that is
  // the last message when it is an AI one; until then the trace trails the
  // thread instead.
  const lastIndex = messages.length - 1
  const traceIndex =
    thinking.length > 0 && messages[lastIndex]?.role === 'ai' ? lastIndex : -1

  // Auto-scroll to bottom whenever the thread's content grows — messages, reply
  // tokens, or the thinking block gaining a step. `thinking` is in here because
  // the block is part of the thread's height: leaving it out let the block grow
  // downward past the fold while the view stayed put.
  //
  // Throttled to SCROLL_THROTTLE_MS so per-token deltas don't cause jitter.
  useEffect(() => {
    const scroll = () => {
      lastScrollAt.current = Date.now()
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    const elapsed = Date.now() - lastScrollAt.current
    clearTimeout(scrollTimer.current)
    if (elapsed >= SCROLL_THROTTLE_MS) {
      scroll()
    } else {
      scrollTimer.current = setTimeout(scroll, SCROLL_THROTTLE_MS - elapsed)
    }
    return () => clearTimeout(scrollTimer.current)
  }, [messages, pending, streamingText, thinking, intakeQuestion])

  return (
    <div
      className="flex-1 overflow-y-auto custom-scrollbar px-4 pt-4 pb-2 flex flex-col gap-3"
      role="log"
      aria-live="polite"
    >
      <MessageBubble
        message={{ id: '__greeting__', role: 'ai', text: t('greeting'), stage: 'intake' }}
      />

      {messages.map((msg, i) => (
        <div key={msg.id} className="flex flex-col gap-3">
          {/* The trace goes ABOVE the reply it produced — it is what happened
              before that answer, so reading downward follows the order things
              occurred. Rendering it after the list put it under the reply,
              which read as a footnote to an answer already given. */}
          {i === traceIndex ? (
            <ThinkingBlock groups={thinking} />
          ) : (
            <RestoredTrace message={msg} />
          )}
          <MessageBubble message={msg} />
        </div>
      ))}

      {/* No reply yet, so the trace is the last thing in the thread. */}
      {traceIndex === -1 && thinking.length > 0 && <ThinkingBlock groups={thinking} />}

      {pending && streamingText && (
        <div className="flex justify-start">
          <MessageBubble
            message={{ id: '__streaming__', role: 'ai', text: streamingText, stage: null }}
            streaming
          />
        </div>
      )}

      {/* Only until the first step lands; after that the block above says more
          than three dots can. */}
      {pending && !streamingText && thinking.length === 0 && (
        <div className="flex justify-start">
          <ElapsedSpinner />
        </div>
      )}

      {/* Trailing intake prompt — the question for the widget currently open in
          the rail. Only ever set while idle (the rail itself is hidden during
          `pending`), so it can't compete with the spinner above. */}
      {intakeQuestion && (
        <MessageBubble
          message={{ id: '__intake_question__', role: 'ai', text: intakeQuestion, stage: 'intake' }}
        />
      )}

      <div ref={bottomRef} />
    </div>
  )
}

/**
 * The block for a reply loaded from history.
 *
 * Sentences are rebuilt from the stored facts on every render rather than read
 * back as text, so a conversation held months ago reads in the language the
 * user is in today. Renders nothing for the messages that carry no trace —
 * every one written before the column existed, which is most of them.
 */
function RestoredTrace({ message }: { message: ChatMessage }) {
  const { t } = useTranslation()
  const groups = useMemo(
    () => groupsFromTrace(message.thinkingTrace, (key, facts) => thinkingLines(t, key, facts)),
    [message.thinkingTrace, t],
  )

  if (groups.length === 0) return null
  return <ThinkingBlock groups={groups} />
}
