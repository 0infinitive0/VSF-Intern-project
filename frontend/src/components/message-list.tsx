import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import MessageBubble from './message-bubble'
import SuggestionChips from './suggestion-chips'
import HotelOptionCards from './hotel-option-card'
import TripParametersCard from './trip-parameters-card'
import IntakeParametersForm from './intake-parameters-form'
import ElapsedSpinner from './elapsed-spinner'
import type { ChatMessage, HotelOption, IntakeStatus, Suggestion, TripPlan } from '../types'

/**
 * MessageList — scrollable thread of all messages.
 * The last AI message's chips / hotel cards are the only live ones.
 * Previously answered chips must not remain clickable (regression from chat.html).
 */
export default function MessageList({
  messages,
  suggestions,
  hotelOptions,
  tripPlan,
  intake,
  pending,
  elapsedMs,
  onSelect,
}: {
  messages: ChatMessage[]
  suggestions: Suggestion[]
  hotelOptions: HotelOption[]
  tripPlan: TripPlan | null
  intake: IntakeStatus | null
  pending: boolean
  elapsedMs: number
  onSelect: (value: string) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

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
    <div
      className="flex-1 overflow-y-auto custom-scrollbar p-4 flex flex-col gap-4"
      role="log"
      aria-live="polite"
    >
      {messages.length === 0 && !pending && (
        <div className="flex flex-col items-start gap-1">
          <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center">
            <span className="material-symbols-outlined text-on-primary text-[14px]" aria-hidden="true">
              auto_awesome
            </span>
          </div>
          <div className="bg-surface-container-low text-on-surface rounded-2xl rounded-tl-sm px-4 py-3 max-w-[90%] text-sm">
            {t('greeting')}
          </div>
        </div>
      )}

      {messages.map((msg, i) => {
        const isLastAi = i === lastAiIndex && msg.role === 'ai'
        const stage = msg.stage

        return (
          <div key={msg.id} className="flex flex-col gap-3">
            <MessageBubble message={msg} />

            {/* Show cards/chips only on the last AI turn */}
            {isLastAi && !pending && (
              <div className="flex justify-start">
                <div className="max-w-[90%] w-full">
                  {stage === 'hotel_options' && hotelOptions.length > 0 ? (
                    <>
                      <TripParametersCard tripPlan={tripPlan} intake={intake} />
                      <HotelOptionCards
                        hotelOptions={hotelOptions}
                        onPick={onSelect}
                        disabled={false}
                      />
                    </>
                  ) : (
                    <>
                      {stage === 'intake' && intake ? (
                        <IntakeParametersForm
                          intake={intake}
                          onSubmit={onSelect}
                          disabled={pending}
                        />
                      ) : (
                        <>
                          {stage === 'intake' && (
                            <TripParametersCard tripPlan={tripPlan} intake={intake} />
                          )}
                          <SuggestionChips
                            suggestions={suggestions}
                            onSelect={onSelect}
                            disabled={false}
                          />
                        </>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}

      {pending && (
        <div className="flex justify-start">
          <ElapsedSpinner elapsedMs={elapsedMs} />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}
