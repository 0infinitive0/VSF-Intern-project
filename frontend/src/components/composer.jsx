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
    <footer className="p-4 border-t border-border-subtle bg-surface-background shrink-0">
      <div className="relative flex items-end">
        <textarea
          ref={textareaRef}
          id="message-input"
          className="w-full bg-surface-muted border border-border-subtle rounded-full py-[10px] pl-4 pr-12 text-sm resize-none leading-normal focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-all disabled:opacity-60"
          placeholder={S.composerPlaceholder}
          rows={1}
          disabled={disabled}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          aria-label={S.composerPlaceholder}
        />
        <button
          id="send-btn"
          className="absolute right-2 bottom-[5px] w-8 h-8 bg-border-subtle hover:bg-primary hover:text-white disabled:opacity-60 disabled:hover:bg-border-subtle disabled:hover:text-inherit rounded-full flex items-center justify-center transition-colors text-text-secondary"
          disabled={disabled}
          onClick={handleSend}
          type="button"
          aria-label={S.sendBtn}
        >
          <span className="material-symbols-outlined text-[16px]">send</span>
        </button>
      </div>
    </footer>
  )
}
