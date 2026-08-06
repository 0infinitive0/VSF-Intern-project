import { useRef, useEffect, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Composer — pill glass input + round send button (design dc.html:298-301).
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
  const { t } = useTranslation()

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
    <div className="shrink-0 flex items-center gap-2.5 pl-[15px] pr-[5px] py-[5px] rounded-[20px] bg-glass-2 border border-edge shadow-[0_8px_22px_-14px_rgb(var(--shadow-rgb)/0.4)]">
      <textarea
        ref={textareaRef}
        id="message-input"
        className="composer-scrollbar flex-1 bg-transparent border-none rounded-none text-[13.5px] text-on-surface resize-none leading-normal focus:outline-none disabled:opacity-60 placeholder:text-on-surface-faint py-2"
        placeholder={t('composerPlaceholder')}
        rows={1}
        disabled={disabled}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
        aria-label={t('composerPlaceholder')}
      />
      <button
        id="send-btn"
        className="w-[34px] h-[34px] flex-none bg-button text-on-button hover:opacity-90 disabled:opacity-60 rounded-full flex items-center justify-center transition-opacity shadow-[0_8px_18px_-8px_rgb(var(--shadow-rgb)/0.8)]"
        disabled={disabled}
        onClick={handleSend}
        type="button"
        aria-label={t('sendBtn')}
      >
        <span className="material-symbols-outlined text-[15px]">arrow_upward</span>
      </button>
    </div>
  )
}
