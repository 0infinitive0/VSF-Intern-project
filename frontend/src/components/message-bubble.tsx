import { useTranslation } from 'react-i18next'
import type { ChatMessage } from '../types'

function formatTimestamp(at: string | undefined, locale: string): string | null {
  if (!at) return null
  const date = new Date(at)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat(locale === 'vi' ? 'vi-VN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/**
 * MessageBubble — renders one chat turn per the Claude Design glassmorphism
 * export (V-OTA Planner.dc.html:2298-2308):
 *   - asymmetric corners: AI `18px 18px 18px 6px`, user `18px 18px 6px 18px`
 *   - AI: glass-3 surface, on-surface ink, hairline --line border, soft drop shadow
 *   - user: `linear-gradient(145deg,#4F86E8,#2C5FC9)`, near-white ink, blue glow
 *   - 24px "V" avatar on AI turns; timestamp caption beneath the bubble
 *   - bubbles cap at 44ch; the backend's pre-formatted text is preserved
 */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  const { t, i18n } = useTranslation()
  const { role, text, isError, at } = message
  const isUser = role === 'user'
  const timestamp = formatTimestamp(at, i18n.language)

  const radiusClass = isUser ? 'rounded-[18px] rounded-br-[6px]' : 'rounded-[18px] rounded-bl-[6px]'

  const bubbleClass = isUser
    ? 'bg-[linear-gradient(145deg,#4F86E8,#2C5FC9)] text-[#FCFDFE] border border-white/22 shadow-[0_8px_20px_-10px_rgba(44,95,201,0.6)]'
    : isError
      ? 'bg-error-container text-on-error-container border border-error/30 shadow-[0_6px_16px_-12px_rgb(var(--shadow-rgb)/0.7)]'
      : 'bg-glass-3 text-on-surface border border-line shadow-[0_6px_16px_-12px_rgb(var(--shadow-rgb)/0.7)]'

  return (
    <div
      className={`flex gap-2.5 items-end animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both] ${isUser ? 'flex-row-reverse' : ''}`}
    >
      {!isUser && (
        <div className="w-6 h-6 flex-none rounded-[9px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] shadow-[0_4px_12px_-3px_rgba(44,95,201,0.55)] flex items-center justify-center">
          <span className="text-on-primary text-[11px] font-semibold">V</span>
        </div>
      )}
      <div className={`flex flex-col gap-1 max-w-[84%] min-w-0 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`max-w-[44ch] px-3.5 py-2.5 text-[14px] leading-[1.58] tracking-[-0.08px] whitespace-pre-wrap ${radiusClass} ${bubbleClass}`}
        >
          {text}
        </div>
        {timestamp && (
          <div
            className="text-[9.5px] font-medium tracking-[0.04em] text-on-surface-muted px-1"
            aria-label={t('messageTimestampLabel', { time: timestamp })}
          >
            {timestamp}
          </div>
        )}
      </div>
    </div>
  )
}
