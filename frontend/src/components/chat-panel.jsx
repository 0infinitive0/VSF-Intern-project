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
    <section className="chat-panel" aria-label={S.appTitle}>
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
