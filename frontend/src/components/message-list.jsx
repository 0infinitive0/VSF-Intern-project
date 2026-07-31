import { useEffect, useRef } from 'react'
import { S } from '../strings.js'
import MessageBubble from './message-bubble.jsx'
import SuggestionChips from './suggestion-chips.jsx'
import HotelOptionCards from './hotel-option-card.jsx'
import ElapsedSpinner from './elapsed-spinner.jsx'

/**
 * MessageList — scrollable thread of all messages.
 * The last AI message's chips / hotel cards are the only live ones.
 * Previously answered chips must not remain clickable (regression from chat.html).
 */
export default function MessageList({
  messages,
  suggestions,
  hotelOptions,
  pending,
  elapsedMs,
  onSelect,
}) {
  const bottomRef = useRef(null)

  // Auto-scroll to bottom whenever messages/pending change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, pending])

  const lastAiIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'ai') return i
    }
    return -1
  })()

  return (
    <div className="message-list" role="log" aria-live="polite">
      {messages.length === 0 && !pending && (
        <div className="bubble-row bubble-row--ai">
          <div className="bubble-col">
            <div className="bubble bubble--ai">{S.greeting}</div>
          </div>
        </div>
      )}

      {messages.map((msg, i) => {
        const isLastAi = i === lastAiIndex && msg.role === 'ai'
        const stage = msg.stage

        return (
          <div key={msg.id}>
            <MessageBubble message={msg} />

            {/* Show cards/chips only on the last AI turn */}
            {isLastAi && !pending && (
              <div className="bubble-row bubble-row--ai">
                <div className="bubble-col">
                  {stage === 'hotel_options' && hotelOptions.length > 0 ? (
                    <HotelOptionCards
                      hotelOptions={hotelOptions}
                      onPick={onSelect}
                      disabled={false}
                    />
                  ) : (
                    <SuggestionChips
                      suggestions={suggestions}
                      onSelect={onSelect}
                      disabled={false}
                    />
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}

      {pending && (
        <div className="bubble-row bubble-row--ai">
          <div className="bubble-col">
            <ElapsedSpinner elapsedMs={elapsedMs} />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
