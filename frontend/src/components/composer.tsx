import { useRef, useEffect, type KeyboardEvent } from 'react'
import { S } from '../strings'

/**
 * Composer — textarea + send button.
 * Disabled while pending. Auto-grows up to 140px.
 * Enter sends; Shift+Enter inserts a newline.
 */
export default function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void
  disabled: boolean
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!disabled) textareaRef.current?.focus()
  }, [disabled])

  function handleSend() {
    const el = textareaRef.current
    const text = el?.value?.trim()
    if (!el || !text) return
    onSend(text)
    el.value = ''
    el.style.height = 'auto'
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
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
    <footer className="p-4 pr-1 border-t border-border-subtle bg-surface-background shrink-0">
      <div className="relative flex items-end">
        <div className="w-full mr-14 bg-surface-muted rounded-3xl py-3.5 pl-5 pr-2 focus-within:ring-2 focus-within:ring-primary transition-all">
          <textarea
            ref={textareaRef}
            id="message-input"
            className="composer-scrollbar w-full bg-transparent border-none rounded-none text-sm resize-none leading-normal focus:outline-none disabled:opacity-60 placeholder:text-on-surface-variant"
            placeholder={S.composerPlaceholder}
            rows={1}
            disabled={disabled}
            onKeyDown={handleKeyDown}
            onInput={handleInput}
            aria-label={S.composerPlaceholder}
          />
        </div>
        <button
          id="send-btn"
          className="absolute right-2 bottom-2 w-9 h-9 bg-primary text-on-primary hover:opacity-90 disabled:opacity-60 rounded-full flex items-center justify-center transition-opacity"
          disabled={disabled}
          onClick={handleSend}
          type="button"
          aria-label={S.sendBtn}
        >
          <span className="material-symbols-outlined text-[18px]">send</span>
        </button>
      </div>
    </footer>
  )
}
