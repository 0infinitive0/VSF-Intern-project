import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * IntakePeopleStepper — segmented 1..4 picker plus an editable last cell
 * (Claude Design "Segmented Count Selector.dc.html", project
 * ae422180-387a-45c9-902a-b018230aad3c): tapping the last cell selects it like
 * any other segment; tapping it again while already selected opens an inline
 * number input (min 5) so groups larger than 5 can enter an exact headcount
 * instead of a vague "5+". Enter/blur commits the typed value and relabels the
 * cell with it; Escape cancels back to the last committed value. The "confirm"
 * button still owns advancing the flow — selecting or editing the last cell
 * only updates `pending`.
 */
export default function IntakePeopleStepper({
  value,
  onCommit,
  disabled,
}: {
  value: number
  onCommit: (n: number) => void
  disabled: boolean
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState(value || 2)
  const [lastValue, setLastValue] = useState(() => (value >= 5 ? value : 5))
  const [isEditing, setIsEditing] = useState(false)
  const [draft, setDraft] = useState(() => String(value >= 5 ? value : 5))
  const inputRef = useRef<HTMLInputElement>(null)
  const options = [1, 2, 3, 4]

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus()
      inputRef.current?.select()
    }
  }, [isEditing])

  const selectOption = (n: number) => {
    setPending(n)
    setIsEditing(false)
  }

  const selectLast = () => {
    if (pending === lastValue) {
      setDraft(String(lastValue))
      setIsEditing(true)
    } else {
      setPending(lastValue)
    }
  }

  const commitDraft = () => {
    let n = parseInt(draft, 10)
    if (Number.isNaN(n) || n < 5) n = 5
    setLastValue(n)
    setPending(n)
    setIsEditing(false)
    setDraft(String(n))
  }

  const cancelDraft = () => {
    setIsEditing(false)
    setDraft(String(lastValue))
  }

  const step = (delta: number) => {
    const current = parseInt(draft, 10)
    const base = Number.isNaN(current) ? lastValue : current
    const n = Math.max(5, base + delta)
    setDraft(String(n))
    setLastValue(n)
    setPending(n)
  }

  const lastSelected = pending === lastValue && !isEditing
  const draftNum = Number.isNaN(parseInt(draft, 10)) ? lastValue : parseInt(draft, 10)

  return (
    <div className="glass-card p-3.5 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      <div className="text-[10px] font-semibold tracking-[0.1em] uppercase text-on-surface-muted mb-2.5">
        {t('intakePeopleLabel')}
      </div>
      <div
        className="flex p-0.5 rounded-[13px] bg-fill gap-0.5"
        role="group"
        aria-label={t('intakePeopleLabel')}
      >
        {options.map((n) => {
          const isSelected = pending === n && !isEditing
          return (
            <button
              key={n}
              type="button"
              aria-pressed={isSelected}
              disabled={disabled}
              onClick={() => selectOption(n)}
              className={`flex-1 py-2 rounded-[10px] text-[13px] transition-all disabled:opacity-60 ${
                isSelected
                  ? 'bg-glass-3 text-on-surface font-semibold shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]'
                  : 'bg-transparent text-on-surface-variant font-normal'
              }`}
            >
              {n}
            </button>
          )
        })}

        {isEditing ? (
          <div className="flex-[1.3] flex items-center justify-center gap-1 py-1 px-1 rounded-[10px] bg-glass-3 shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]">
            <button
              type="button"
              aria-label={t('intakeDecreaseGuests')}
              disabled={disabled || draftNum <= 5}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => step(-1)}
              className="w-5 h-5 flex-none flex items-center justify-center rounded-full text-on-surface-variant text-[13px] leading-none hover:bg-fill disabled:opacity-40"
            >
              −
            </button>
            <input
              ref={inputRef}
              type="number"
              min={5}
              inputMode="numeric"
              aria-label={t('intakePeopleLabel')}
              disabled={disabled}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitDraft}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitDraft()
                else if (e.key === 'Escape') cancelDraft()
              }}
              className="w-full max-w-[28px] text-center text-[13px] font-semibold text-on-surface bg-transparent border-none outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
            <button
              type="button"
              aria-label={t('intakeIncreaseGuests')}
              disabled={disabled}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => step(1)}
              className="w-5 h-5 flex-none flex items-center justify-center rounded-full text-on-surface-variant text-[13px] leading-none hover:bg-fill disabled:opacity-40"
            >
              +
            </button>
          </div>
        ) : (
          <button
            type="button"
            aria-pressed={lastSelected}
            disabled={disabled}
            onClick={selectLast}
            className={`flex-[1.3] flex items-center justify-center gap-1 py-2 rounded-[10px] text-[13px] transition-all disabled:opacity-60 ${
              lastSelected
                ? 'bg-glass-3 text-on-surface font-semibold shadow-[0_4px_12px_-6px_rgb(var(--shadow-rgb)/0.6)]'
                : 'bg-transparent text-on-surface-variant font-normal'
            }`}
          >
            <span>{lastValue}</span>
            <svg
              width="11"
              height="11"
              viewBox="0 0 24 24"
              fill="none"
              className="flex-none text-on-surface-variant/70"
              aria-hidden="true"
            >
              <path
                d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19 3 20l1-4L16.5 3.5Z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
      <button
        type="button"
        className="mt-2.5 w-full py-2.5 rounded-[13px] bg-button text-on-button text-[13px] font-semibold tracking-[-0.12px] disabled:opacity-50"
        disabled={disabled || pending <= 0}
        onClick={() => onCommit(pending)}
      >
        {t('intakeConfirm')}
      </button>
    </div>
  )
}
