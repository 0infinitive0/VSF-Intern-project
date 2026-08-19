import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import MessageBubble from './message-bubble'
import ElapsedSpinner from './elapsed-spinner'
import ThinkingBlock from './thinking-block'
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

  // Auto-scroll to bottom whenever messages/pending/streaming content change,
  // throttled to SCROLL_THROTTLE_MS so per-token deltas don't cause jitter.
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
  }, [messages, pending, streamingText, intakeQuestion])

  return (
    <div
      className="flex-1 overflow-y-auto custom-scrollbar px-4 pt-4 pb-2 flex flex-col gap-3"
      role="log"
      aria-live="polite"
    >
      <MessageBubble
        message={{ id: '__greeting__', role: 'ai', text: t('greeting'), stage: 'intake' }}
      />

      {messages.map((msg) => (
        <div key={msg.id}>
          <MessageBubble message={msg} />
        </div>
      ))}

      {pending && streamingText && (
        <div className="flex justify-start">
          <MessageBubble
            message={{ id: '__streaming__', role: 'ai', text: streamingText, stage: null }}
            streaming
          />
        </div>
      )}

      {/* One indicator at a time. Once reply text starts flowing the bubble
          below takes over and the thinking block steps aside, so the two never
          compete for the same spot. */}
      {pending && !streamingText && (
        <div className="flex justify-start">
          {thinking.length > 0 ? <ThinkingBlock groups={thinking} /> : <ElapsedSpinner />}
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
