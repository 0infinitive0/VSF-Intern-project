import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DayPicker } from '@daypicker/react'
import { addMonths, addYears, format, subMonths, subYears } from 'date-fns'
import { vi as viLocale } from 'date-fns/locale/vi'
import { enUS as enLocale } from 'date-fns/locale'
import { formatFullDate } from '../lib/format-trip-dates'
import { useCalendarGridFadeReplay } from '../lib/use-calendar-grid-fade'
import '@daypicker/react/style.css'

function toISODate(date: Date): string {
  return format(date, 'yyyy-MM-dd')
}

function fromISODate(value: string | undefined): Date | undefined {
  if (!value) return undefined
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed
}

// Initial month shown when the user hasn't picked a start date yet.
const DEFAULT_CALENDAR_MONTH = fromISODate('2026-07-01')!

/**
 * IntakeDateRange — a range-picker calendar with month+year navigation, from/to
 * summary chips and a confirm button (design dc.html:226-256).
 *
 * Built on react-day-picker v10 range mode with controlled `month`/`onMonthChange`
 * and `hideNavigation` — the nav row (prev/next month + prev/next year) is the
 * design's custom row. The selected range is held as pending state; "confirm"
 * commits it (so selecting does not auto-advance the flow).
 */
export default function IntakeDateRange({
  start,
  end,
  onCommit,
  disabled,
}: {
  start: string
  end: string
  onCommit: (range: { start: string; end: string }) => void
  disabled: boolean
}) {
  const { t, i18n } = useTranslation()
  const [month, setMonth] = useState<Date>(() => fromISODate(start) ?? DEFAULT_CALENDAR_MONTH)
  const [pending, setPending] = useState<{ start: string; end: string }>({ start, end })
  const locale = i18n.language === 'vi' ? viLocale : enLocale
  const calendarRef = useRef<HTMLDivElement>(null)
  useCalendarGridFadeReplay(calendarRef, month)

  const range = useMemo(() => {
    const from = fromISODate(pending.start)
    const to = fromISODate(pending.end)
    return from || to ? { from: from ?? to, to: to ?? from } : undefined
  }, [pending.start, pending.end])

  const hasBoth = Boolean(pending.start && pending.end && pending.end > pending.start)
  const startLabel = formatFullDate(pending.start, i18n.language)
  const endLabel = formatFullDate(pending.end, i18n.language)

  return (
    <div className="glass-card p-3.5 animate-[vPop_0.5s_cubic-bezier(0.22,1,0.36,1)_both]">
      {/* Month/year navigation — design's prev/next month + year buttons */}
      <div className="flex items-center gap-1.5 mb-2.5">
        <button
          type="button"
          title={t('ttPrevYear')}
          aria-label={t('ttPrevYear')}
          onClick={() => setMonth((m) => subYears(m, 1))}
          className="w-[26px] h-[26px] rounded-[9px] border border-stroke bg-glass-2 text-on-surface-variant text-[11px] hover:bg-button hover:text-on-button"
        >
          «
        </button>
        <button
          type="button"
          title={t('ttPrevMonth')}
          aria-label={t('ttPrevMonth')}
          onClick={() => setMonth((m) => subMonths(m, 1))}
          className="w-[26px] h-[26px] rounded-[9px] border border-stroke bg-glass-2 text-on-surface-variant text-[11px] hover:bg-button hover:text-on-button"
        >
          ‹
        </button>
        <div className="flex-1 text-center text-[13px] font-semibold tracking-[-0.12px] text-on-surface">
          {format(month, 'MMMM', { locale })} <span className="font-normal text-on-surface-muted">{format(month, 'yyyy', { locale })}</span>
        </div>
        <button
          type="button"
          title={t('ttNextMonth')}
          aria-label={t('ttNextMonth')}
          onClick={() => setMonth((m) => addMonths(m, 1))}
          className="w-[26px] h-[26px] rounded-[9px] border border-stroke bg-glass-2 text-on-surface-variant text-[11px] hover:bg-button hover:text-on-button"
        >
          ›
        </button>
        <button
          type="button"
          title={t('ttNextYear')}
          aria-label={t('ttNextYear')}
          onClick={() => setMonth((m) => addYears(m, 1))}
          className="w-[26px] h-[26px] rounded-[9px] border border-stroke bg-glass-2 text-on-surface-variant text-[11px] hover:bg-button hover:text-on-button"
        >
          »
        </button>
      </div>

      {/* vFade replays on the grid via the ref effect above, keyed by month —
          the design's `calKey`-driven month transition — without remounting
          DayPicker (which would drop keyboard focus mid-navigation). */}
      <div ref={calendarRef} className="day-calendar">
        <DayPicker
          mode="range"
          locale={locale}
          month={month}
          onMonthChange={setMonth}
          hideNavigation
          animate
          selected={range}
          onSelect={(selectedRange) => {
            if (!selectedRange?.from) {
              setPending({ start: '', end: '' })
              return
            }
            const nextStart = toISODate(selectedRange.from)
            const nextEnd = selectedRange.to ? toISODate(selectedRange.to) : nextStart
            setPending({ start: nextStart, end: nextEnd })
          }}
          numberOfMonths={1}
        />
      </div>

      {/* From/to summary chips */}
      <div className="flex gap-1.5 mt-3">
        <div className="flex-1 px-2.5 py-2 rounded-[12px] bg-fill">
          <div className="text-[9.5px] text-on-surface-muted tracking-[0.05em] uppercase">{t('dateFrom')}</div>
          <div className="text-[12.5px] font-semibold tracking-[-0.1px] text-on-surface mt-0.5">
            {startLabel ?? '—'}
          </div>
        </div>
        <div className="flex-1 px-2.5 py-2 rounded-[12px] bg-fill">
          <div className="text-[9.5px] text-on-surface-muted tracking-[0.05em] uppercase">{t('dateTo')}</div>
          <div className="text-[12.5px] font-semibold tracking-[-0.1px] text-on-surface mt-0.5">
            {endLabel ?? '—'}
          </div>
        </div>
      </div>

      <button
        type="button"
        className={`mt-2.5 w-full py-2.5 rounded-[13px] text-[13px] font-semibold tracking-[-0.12px] transition-colors ${
          hasBoth ? 'bg-button text-on-button' : 'bg-fill2 text-on-surface-faint'
        }`}
        disabled={disabled || !hasBoth}
        onClick={() => onCommit({ start: pending.start, end: pending.end })}
      >
        {t('confirmDates')}
      </button>
    </div>
  )
}
