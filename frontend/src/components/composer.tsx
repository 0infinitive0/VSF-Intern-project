import { useRef, useEffect, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Composer — pill glass input + round send button (design dc.html:298-301).
 * Disabled while pending. Auto-grows up to 140px.
 * Enter sends; Shift+Enter inserts a newline.
 */
const MAX_HEIGHT = 140

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
    resize(el)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Grow with the content and only show the scrollbar once the max height is
  // reached — otherwise a single line renders an empty scrollbar track.
  function resize(el: HTMLTextAreaElement) {
    el.style.height = 'auto'
    const contentHeight = el.scrollHeight
    el.style.height = Math.min(contentHeight, MAX_HEIGHT) + 'px'
    el.style.overflowY = contentHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }

  function handleInput() {
    const el = textareaRef.current
    if (el) resize(el)
  }

  return (
    <div className="shrink-0 flex items-center gap-2.5 pl-[15px] pr-[5px] py-[5px] rounded-[20px] bg-glass-2 border border-edge shadow-[0_8px_22px_-14px_rgb(var(--shadow-rgb)/0.4)]">
      <textarea
        ref={textareaRef}
        id="message-input"
        className="composer-scrollbar flex-1 bg-transparent border-none rounded-none text-[13px] text-on-surface resize-none overflow-y-hidden leading-normal focus:outline-none disabled:opacity-60 placeholder:text-on-surface-faint py-2"
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
