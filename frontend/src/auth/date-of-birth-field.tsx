import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DayPicker } from '@daypicker/react'
import { format, setYear, subMonths, addMonths } from 'date-fns'
import { vi as viLocale } from 'date-fns/locale/vi'
import { enUS as enLocale } from 'date-fns/locale'
import { formatFullDate } from '../lib/format-trip-dates'
import { useCalendarGridFadeReplay } from '../lib/use-calendar-grid-fade'
import '@daypicker/react/style.css'

function toISODate(date: Date): string {
  return format(date, 'yyyy-MM-dd')
}

function fromISODate(value: string): Date | undefined {
  if (!value) return undefined
  const parsed = new Date(`${value}T00:00:00`)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed
}

// Design's own fallback month when nothing is picked yet (V-OTA
// Planner.dc.html:1997, `new Date(1994, 2, 1)`) — a birth-year-plausible
// starting point beats defaulting to "now", which would put every
// first-time user's calendar decades away from where they need to navigate.
const DEFAULT_DOB_MONTH = new Date(1994, 2, 1)

const YEAR_RANGE = 100

/**
 * DateOfBirthField — the profile modal's date-of-birth picker (design:
 * V-OTA Planner.dc.html:1016-1052, toggleDobCal/dobCalendarCells/dobYears
 * around lines 1996-2118). Built on the same @daypicker/react + date-fns
 * stack as IntakeDateRange (mode="single" here instead of "range"), sharing
 * its `.day-calendar` cell theming (styles.css) rather than duplicating it.
 *
 * Two things IntakeDateRange doesn't need that this does:
 *  - A year-grid quick-jump (design's dobYearGrid/dobYears): birth years
 *    span decades, so a year label the user can tap to reveal a scrollable
 *    year grid replaces IntakeDateRange's prev/next-year buttons, which
 *    would take dozens of clicks to reach a birth year. Range is 100 years
 *    back from the real current year (design hard-codes its own fictional
 *    "today" of 2026 — this doesn't).
 *  - The popover opens upward (`bottom: 100%`, same as the design, design:
 *    dc.html:1024) instead of living inline on the page — this field sits
 *    inside ProfilePasswordModal's compact two-column form, not its own
 *    full-width card the way the trip-dates picker does.
 *
 * Outside-click-to-close isn't in the design's markup but is added here —
 * same convention as every other popover in this app (e.g. UserMenu's own
 * dropdown).
 */
export default function DateOfBirthField({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const { t, i18n } = useTranslation()
  const locale = i18n.language === 'vi' ? viLocale : enLocale
  const [open, setOpen] = useState(false)
  const [yearGridOpen, setYearGridOpen] = useState(false)
  const [month, setMonth] = useState<Date>(() => fromISODate(value) ?? DEFAULT_DOB_MONTH)
  const rootRef = useRef<HTMLDivElement>(null)
  const calendarRef = useRef<HTMLDivElement>(null)
  useCalendarGridFadeReplay(calendarRef, month)

  // Re-seed the visible month from the current value each time the popover
  // opens (design's toggleDobCal does the same) — otherwise reopening after
  // navigating away would leave the calendar wherever it was last scrolled to.
  useEffect(() => {
    if (!open) return
    setYearGridOpen(false)
    setMonth(fromISODate(value) ?? DEFAULT_DOB_MONTH)
  }, [open, value])

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('mousedown', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const selected = fromISODate(value)
  const label = formatFullDate(value, i18n.language) ?? t('authDobPlaceholder')
  const currentYear = new Date().getFullYear()
  const years = Array.from({ length: YEAR_RANGE }, (_, i) => currentYear - i)

  return (
    <div ref={rootRef} className="relative flex flex-col gap-1.5">
      <span className="text-[10.5px] font-semibold tracking-wide uppercase text-on-surface-muted">
        {t('authDobLabel')}
      </span>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="h-10 px-3.5 rounded-[13px] border text-[13px] text-on-surface flex items-center gap-2 text-left transition-[box-shadow,border-color] duration-200"
        style={{
          background: 'var(--g3)',
          borderColor: open ? 'var(--color-primary)' : 'var(--color-outline-variant)',
          boxShadow: open ? '0 0 0 4px var(--color-primary-soft)' : 'none',
        }}
      >
        <span className="flex-1 min-w-0 truncate">{label}</span>
        <span
          className="shrink-0 text-[12px] text-on-surface-muted transition-transform duration-200"
          style={{ transform: open ? 'rotate(180deg)' : 'none' }}
          aria-hidden="true"
        >
          ▾
        </span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label={t('authDobLabel')}
          className="absolute bottom-full left-0 right-0 z-10 mb-[7px] p-3.5 rounded-[22px] border border-edge"
          style={{
            background: 'var(--g3)',
            backdropFilter: 'blur(24px) saturate(1.8)',
            WebkitBackdropFilter: 'blur(24px) saturate(1.8)',
            boxShadow: '0 -30px 70px -26px rgb(var(--shadow-rgb) / 0.75), 0 2px 10px rgb(var(--shadow-rgb) / 0.28)',
            animation: 'vPop .38s cubic-bezier(.22,1,.36,1) both',
            transformOrigin: 'bottom center',
          }}
        >
          <div className="flex items-center gap-1.5 mb-2.5">
            <button
              type="button"
              title={t('ttPrevMonth')}
              aria-label={t('ttPrevMonth')}
              onClick={() => setMonth((m) => subMonths(m, 1))}
              className="w-[26px] h-[26px] rounded-[9px] border border-stroke bg-glass-2 text-on-surface-variant text-[11px] hover:bg-button hover:text-on-button"
            >
              ‹
            </button>
            <div className="flex-1 flex items-center justify-center gap-1.5">
              <span className="text-[13px] font-semibold tracking-[-0.2px] text-on-surface">
                {format(month, 'MMMM', { locale })}
              </span>
              <button
                type="button"
                onClick={() => setYearGridOpen((y) => !y)}
                aria-expanded={yearGridOpen}
                aria-label={t('authDobPickYear')}
                className="flex items-center gap-1 h-6 px-2.5 rounded-full text-[12px] font-semibold transition-colors"
                style={{
                  background: yearGridOpen ? 'var(--btn)' : 'var(--fill)',
                  color: yearGridOpen ? 'var(--btn-fg)' : 'var(--color-on-surface-variant)',
                  border: yearGridOpen ? '1px solid transparent' : '1px solid var(--stroke)',
                }}
              >
                {format(month, 'yyyy')}
                <span
                  className="text-[9px] opacity-60 transition-transform duration-200"
                  style={{ transform: yearGridOpen ? 'rotate(180deg)' : 'none' }}
                  aria-hidden="true"
                >
                  ▾
                </span>
              </button>
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
          </div>

          {yearGridOpen ? (
            <div className="grid grid-cols-4 gap-[3px] max-h-[190px] overflow-y-auto animate-[vFade_0.28s_ease_both]">
              {years.map((y) => {
                const isSelected = y === month.getFullYear()
                return (
                  <button
                    key={y}
                    type="button"
                    onClick={() => {
                      setMonth((m) => setYear(m, y))
                      setYearGridOpen(false)
                    }}
                    className="h-[31px] rounded-[11px] text-[12.5px] transition-colors hover:bg-[rgba(58,115,222,.12)]"
                    style={{
                      fontWeight: isSelected ? 590 : 450,
                      background: isSelected ? 'var(--btn)' : 'transparent',
                      color: isSelected ? 'var(--btn-fg)' : 'var(--t1)',
                    }}
                  >
                    {y}
                  </button>
                )
              })}
            </div>
          ) : (
            <div ref={calendarRef} className="day-calendar">
              <DayPicker
                mode="single"
                locale={locale}
                month={month}
                onMonthChange={setMonth}
                hideNavigation
                animate
                selected={selected}
                onSelect={(date) => {
                  if (!date) return
                  onChange(toISODate(date))
                  setOpen(false)
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
