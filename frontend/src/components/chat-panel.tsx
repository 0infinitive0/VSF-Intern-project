import { S } from '../strings'
import MessageList from './message-list'
import Composer from './composer'
import type { ChatState } from '../types'

/**
 * ChatPanel — the main chat column.
 * Composes the message thread and composer.
 * Passes send() to both the composer and the chip/card click handlers.
 */
export default function ChatPanel({
  state,
  onSend,
  width,
}: {
  state: ChatState
  onSend: (text: string) => void
  width: number
}) {
  const { messages, suggestions, hotelOptions, tripPlan, intake, pending, elapsedMs } = state

  return (
    <section
      className="bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
      style={{ width }}
      aria-label={S.chatPanelTitle}
    >
      <div className="px-6 py-5 flex justify-between items-center bg-surface-background border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-[22px]" aria-hidden="true">
            auto_awesome
          </span>
          <h2 className="font-display text-lg font-bold text-on-surface">{S.chatPanelTitle}</h2>
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            className="p-1.5 text-on-surface-variant opacity-60 cursor-not-allowed rounded-md"
            disabled
            title={S.chatPanelMoreHint}
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
              more_horiz
            </span>
          </button>
          <button
            type="button"
            className="p-1.5 text-on-surface-variant opacity-60 cursor-not-allowed rounded-md"
            disabled
            title={S.chatPanelExpandHint}
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
              open_in_full
            </span>
          </button>
        </div>
      </div>
      <MessageList
        messages={messages}
        suggestions={suggestions}
        hotelOptions={hotelOptions}
        tripPlan={tripPlan}
        intake={intake}
        pending={pending}
        elapsedMs={elapsedMs}
        onSelect={onSend}
      />
      <Composer onSend={onSend} disabled={pending} />
    </section>
  )
}
