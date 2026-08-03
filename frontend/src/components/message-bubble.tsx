import type { ChatMessage } from '../types'

/**
 * MessageBubble — renders one chat turn.
 * Preserves the backend's pre-formatted text (white-space: pre-wrap via CSS).
 * Never re-parses the text to infer options — that is done by the server via suggestions[].
 */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  const { role, text, isError } = message
  const isUser = role === 'user'

  const bubbleClass = isUser
    ? 'bg-primary text-on-primary rounded-2xl rounded-tr-sm'
    : isError
      ? 'bg-error-container text-on-error-container border border-error/30 rounded-2xl rounded-tl-sm'
      : 'bg-surface-container-low text-on-surface rounded-2xl rounded-tl-sm'

  return (
    <div className={`flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`}>
      {!isUser && (
        <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center">
          <span className="material-symbols-outlined text-on-primary text-[14px]" aria-hidden="true">
            auto_awesome
          </span>
        </div>
      )}
      <div className={`px-4 py-3 max-w-[85%] text-sm whitespace-pre-wrap ${bubbleClass}`}>
        {text}
      </div>
    </div>
  )
}
