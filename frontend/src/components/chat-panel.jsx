import { S } from '../strings.js'
import MessageList from './message-list.jsx'
import Composer from './composer.jsx'

/**
 * ChatPanel — the main chat column.
 * Composes the message thread and composer.
 * Passes send() to both the composer and the chip/card click handlers.
 */
export default function ChatPanel({ state, onSend }) {
  const { messages, suggestions, hotelOptions, pending, elapsedMs } = state

  return (
    <section
      className="w-[380px] bg-surface-background border-r border-border-subtle flex flex-col shrink-0"
      aria-label={S.appTitle}
    >
      <div className="p-4 flex justify-between items-center border-b border-border-subtle shrink-0">
        <div className="flex items-center gap-2 text-text-primary font-display font-semibold text-lg">
          <span className="material-symbols-outlined text-primary">temp_preferences_custom</span>
          {S.appTitle}
        </div>
      </div>
      <MessageList
        messages={messages}
        suggestions={suggestions}
        hotelOptions={hotelOptions}
        pending={pending}
        elapsedMs={elapsedMs}
        onSelect={onSend}
      />
      <Composer onSend={onSend} disabled={pending} />
    </section>
  )
}
