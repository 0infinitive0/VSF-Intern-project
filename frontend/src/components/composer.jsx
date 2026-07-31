import { useRef, useEffect } from 'react'
import { S } from '../strings.js'

/**
 * Composer — textarea + send button.
 * Disabled while pending. Auto-grows up to 140px.
 * Enter sends; Shift+Enter inserts a newline.
 */
export default function Composer({ onSend, disabled }) {
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!disabled) textareaRef.current?.focus()
  }, [disabled])

  function handleSend() {
    const text = textareaRef.current?.value?.trim()
    if (!text) return
    onSend(text)
    textareaRef.current.value = ''
    textareaRef.current.style.height = 'auto'
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function handleInput() {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 140) + 'px'
  }

  return (
    <footer className="composer-footer">
      <div className="composer">
        <textarea
          ref={textareaRef}
          id="message-input"
          className="composer__textarea"
          placeholder={S.composerPlaceholder}
          rows={1}
          disabled={disabled}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          aria-label={S.composerPlaceholder}
        />
        <button
          id="send-btn"
          className="composer__send-btn"
          disabled={disabled}
          onClick={handleSend}
          type="button"
          aria-label={S.sendBtn}
        >
          {S.sendBtn}
        </button>
      </div>
    </footer>
  )
}
