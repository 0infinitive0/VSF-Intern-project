/**
 * MessageBubble — renders one chat turn.
 * Preserves the backend's pre-formatted text (white-space: pre-wrap via CSS).
 * Never re-parses the text to infer options — that is done by the server via suggestions[].
 */
export default function MessageBubble({ message }) {
  const { role, text, isError } = message

  let bubbleClass = 'bubble'
  if (role === 'user') bubbleClass += ' bubble--user'
  else if (isError)    bubbleClass += ' bubble--ai bubble--error'
  else                 bubbleClass += ' bubble--ai'

  const rowClass = `bubble-row bubble-row--${role === 'user' ? 'user' : 'ai'}`

  return (
    <div className={rowClass}>
      <div className="bubble-col">
        <div className={bubbleClass}>{text}</div>
      </div>
    </div>
  )
}
