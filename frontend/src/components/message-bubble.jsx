/**
 * MessageBubble — renders one chat turn.
 * Preserves the backend's pre-formatted text (white-space: pre-wrap via CSS).
 * Never re-parses the text to infer options — that is done by the server via suggestions[].
 */
export default function MessageBubble({ message }) {
  const { role, text, isError } = message
  const isUser = role === 'user'

  const bubbleClass = isUser
    ? 'bg-surface-container text-on-surface rounded-lg rounded-tr-none'
    : isError
      ? 'bg-error-container text-on-error-container border border-error/30 rounded-lg'
      : 'bg-surface-background border border-border-subtle rounded-lg shadow-sm'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className="max-w-[90%]">
        <div className={`p-4 text-sm whitespace-pre-wrap ${bubbleClass}`}>{text}</div>
      </div>
    </div>
  )
}
