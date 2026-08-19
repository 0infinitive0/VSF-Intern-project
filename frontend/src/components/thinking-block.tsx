import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ThinkingGroup } from '../types'

/**
 * ThinkingBlock — what the chat column shows while a turn runs, in place of
 * three blinking dots.
 *
 * Each group is one user-facing step: a spinner while it runs, a tick once a
 * later step starts, and beneath it the sentences built from what that step
 * actually did. A step with no facts renders its title alone — never an empty
 * text area, and never a filler sentence. Empty is the honest state and it is
 * common (`compacting_history` and `generating` report nothing at all).
 *
 * `ElapsedSpinner` stays the fallback for the window before the first phase
 * frame arrives; the caller picks between them.
 */
export default function ThinkingBlock({ groups }: { groups: ThinkingGroup[] }) {
  const { t } = useTranslation()
  const scrollRef = useRef<HTMLDivElement | null>(null)
  // Null until the user touches the toggle. After that their choice wins for
  // the rest of the turn — auto-collapse must never fight someone reading.
  const [manualOpen, setManualOpen] = useState<boolean | null>(null)
  const [stickToBottom, setStickToBottom] = useState(true)
  const [hasMoreBelow, setHasMoreBelow] = useState(false)

  const allDone = groups.length > 0 && groups.every((g) => g.done)
  const open = manualOpen ?? !allDone

  const syncOverflow = () => {
    const el = scrollRef.current
    if (!el) return
    setHasMoreBelow(el.scrollHeight - el.scrollTop - el.clientHeight > 4)
  }

  // Follow new lines, but only while the user is already at the bottom —
  // yanking the view back while they are reading an earlier step is worse than
  // letting the newest line sit out of sight.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (stickToBottom) el.scrollTop = el.scrollHeight
    syncOverflow()
  }, [groups, open, stickToBottom])

  useEffect(() => {
    syncOverflow()
  }, [])

  if (groups.length === 0) return null

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    setStickToBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 8)
    syncOverflow()
  }

  // Deliberately NOT the running group's label: that row is rendered right
  // below, and repeating it read as the block having exactly one step.
  const done = groups.filter((g) => g.done).length
  const headerLabel = allDone
    ? t('thinkingHeaderDone')
    : t('thinkingHeaderRunning', { done, total: groups.length })

  return (
    <div className="flex gap-2.5 items-start" aria-live="polite" aria-busy={!allDone}>
      <div className="w-6 h-6 flex-none rounded-[9px] bg-[linear-gradient(145deg,#5C93EE,#2C5FC9)] flex items-center justify-center">
        <span className="text-on-primary text-[11px] font-[590]">V</span>
      </div>

      <div className="min-w-0 max-w-full rounded-[18px] bg-glass-3 border border-line overflow-hidden">
        <button
          type="button"
          onClick={() => setManualOpen(!open)}
          aria-expanded={open}
          className="w-full flex items-center gap-2 px-[15px] py-[11px] text-left text-[13.5px] text-on-surface"
        >
          {allDone ? (
            <span
              className="w-4 h-4 flex-none rounded-full bg-success/15 text-success flex items-center justify-center text-[10px] font-bold"
              aria-hidden="true"
            >
              ✓
            </span>
          ) : (
            <span
              className="w-4 h-4 flex-none rounded-full border-2 border-primary border-t-transparent animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
          )}
          <span className="min-w-0 truncate">{headerLabel}</span>
          <span
            className={`ml-auto flex-none text-on-surface/50 transition-transform motion-reduce:transition-none ${
              open ? 'rotate-90' : ''
            }`}
            aria-hidden="true"
          >
            ›
          </span>
        </button>

        {open && (
          <div className="relative">
            <div
              ref={scrollRef}
              onScroll={onScroll}
              className="max-h-[10.5rem] overflow-y-auto px-[15px] pb-[13px] flex flex-col gap-2.5"
            >
              {groups.map((group) => (
                <Step key={group.key} group={group} t={t} />
              ))}
            </div>
            {/* Only drawn when something is actually below the fold, so it
                never implies scrollable content that isn't there. */}
            {hasMoreBelow && (
              <div
                className="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-glass-3 to-transparent"
                aria-hidden="true"
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Step({
  group,
  t,
}: {
  group: ThinkingGroup
  t: (key: string) => string
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2.5 text-[13.5px] text-on-surface">
        {group.done ? (
          <span
            className="w-4 h-4 flex-none rounded-full bg-success/15 text-success flex items-center justify-center text-[10px] font-bold"
            aria-hidden="true"
          >
            ✓
          </span>
        ) : (
          <span
            className="w-4 h-4 flex-none rounded-full border-2 border-primary border-t-transparent animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
        )}
        <span className="min-w-0">{t(group.labelKey)}</span>
      </div>

      {group.lines.map((line) => (
        <p
          key={line}
          className="pl-[26px] text-[12.5px] leading-relaxed text-on-surface/70 motion-safe:animate-[vRise_.26s_ease-out]"
        >
          {line}
        </p>
      ))}

      {/* The model's own words, kept visibly apart from the product's. Always
          English (see docs/chat_api_contract.md), so it is labelled rather than
          translated, and it only appears when the model produced any. */}
      {group.reasoning && (
        <div className="pl-[26px] flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wide text-on-surface/40">
            {t('thinkingModelReasoning')}
          </span>
          <p className="text-[12.5px] leading-relaxed text-on-surface/50 italic whitespace-pre-wrap">
            {group.reasoning}
          </p>
        </div>
      )}
    </div>
  )
}
