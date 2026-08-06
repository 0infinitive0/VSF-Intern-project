import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import MessageBubble from './message-bubble'
import ElapsedSpinner from './elapsed-spinner'
import type { ChatMessage } from '../types'

/**
 * MessageList — the scrollable thread of messages. Thread-only (phase-06): the
 * intake widgets / chips / hotel cards live in a fixed rail above the composer,
 * not inside this scroll. Renders bubbles, the greeting before the first turn,
 * and the in-flow thinking indicator while pending.
 */
export default function MessageList({
  messages,
  pending,
  elapsedMs,
}: {
  messages: ChatMessage[]
  pending: boolean
  elapsedMs: number
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  // Auto-scroll to bottom whenever messages/pending change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  return (
    <div
      className="flex-1 overflow-y-auto custom-scrollbar px-4 pt-4 pb-2 flex flex-col gap-3"
      role="log"
      aria-live="polite"
    >
      {messages.length === 0 && !pending && (
        <div className="flex gap-2.5 items-end">
          <div className="w-6 h-6 flex-none rounded-[9px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] shadow-[0_4px_12px_-3px_rgba(44,95,201,0.55)] flex items-center justify-center">
            <span className="text-on-primary text-[11px] font-semibold">V</span>
          </div>
          <div className="max-w-[84%] bg-glass-3 text-on-surface border border-line rounded-[18px] rounded-bl-[6px] shadow-[0_6px_16px_-12px_rgb(var(--shadow-rgb)/0.7)] px-3.5 py-2.5 text-sm">
            {t('greeting')}
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <div key={msg.id}>
          <MessageBubble message={msg} />
        </div>
      ))}

      {pending && (
        <div className="flex justify-start">
          <ElapsedSpinner elapsedMs={elapsedMs} />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
