import { useEffect, useRef, useState } from 'react'
import type { NightRow } from '../../../api/hotels-client'
import { dateRange } from '../../../lib/expand-dates'

const WEEKDAY_LABELS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']

interface PriceCalendarProps {
  /** First day of the displayed month, `YYYY-MM-DD`. */
  monthStart: string
  nights: NightRow[]
  selectedDates: Set<string>
  onSelectionChange: (dates: Set<string>) => void
  todayIso: string
}

function daysInMonth(monthStart: string): string[] {
  const [y, m] = monthStart.split('-').map(Number)
  const count = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return Array.from({ length: count }, (_, i) => `${monthStart.slice(0, 8)}${String(i + 1).padStart(2, '0')}`)
}

/** Monday-first weekday index (0=Mon..6=Sun) for a `YYYY-MM-DD` date. */
function mondayIndex(isoDate: string): number {
  const [y, m, d] = isoDate.split('-').map(Number)
  const jsDay = new Date(Date.UTC(y, m - 1, d)).getUTCDay() // 0=Sun..6=Sat
  return (jsDay + 6) % 7
}

function shiftDate(isoDate: string, deltaDays: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + deltaDays)).toISOString().slice(0, 10)
}

/**
 * price-calendar.tsx — B6's month grid (phase-11-room-prices.md). Mouse
 * drag-select (mousedown anchor -> mouseenter extends -> window mouseup
 * commits) and Shift+Arrow keyboard selection share one range primitive
 * (`dateRange`) so both produce identical results. Past dates render at
 * reduced opacity and are inert to both input paths -- pricing a night
 * that has already happened is meaningless (see module's phase plan).
 *
 * Selection is driven ONLY by mousedown/mouseenter (drag) and Enter/Space
 * (keyboard toggle) -- there is deliberately no `onClick` handler. A click
 * fires mousedown then mouseup then click; mousedown already collapses the
 * selection to that one cell (a plain click = select-one-day), and layering
 * a second toggle on top of that in `onClick` raced the window `mouseup`
 * listener that clears `selecting` -- depending on event-flush timing, the
 * click's own mousedown-selection could get toggled straight back off.
 */
export function PriceCalendar({ monthStart, nights, selectedDates, onSelectionChange, todayIso }: PriceCalendarProps) {
  const nightsByDate = new Map(nights.map((n) => [n.date, n]))
  const days = daysInMonth(monthStart)
  const leadingBlanks = mondayIndex(days[0])

  function isPast(date: string): boolean {
    return date < todayIso
  }

  const [anchor, setAnchor] = useState<string | null>(null)
  const [selecting, setSelecting] = useState(false)
  // A plain click's mousedown->mouseup isn't perfectly stationary -- a few
  // px of cursor jitter (common on trackpads, especially near a cell's
  // edge) can land a `mouseenter` on the neighboring cell before mouseup,
  // which extendSelect would otherwise read as "drag onto that cell too".
  // Requiring real pixel travel past this threshold before an enter counts
  // as a drag (not just "a different cell") tells the two apart.
  const DRAG_THRESHOLD_PX = 6
  const mouseDownPosRef = useRef<{ x: number; y: number } | null>(null)
  const draggingRef = useRef(false)
  // Roving tabindex starts on the first selectable (non-past) day -- a
  // `disabled` button can never receive focus, so starting on a past day
  // (e.g. loading the current month after the 1st) would leave nothing in
  // the grid reachable by Tab at all.
  const [focusDate, setFocusDate] = useState<string>(() => days.find((d) => !isPast(d)) ?? days[days.length - 1])
  const cellRefs = useRef(new Map<string, HTMLButtonElement>())

  useEffect(() => {
    if (!selecting) return
    const stop = () => setSelecting(false)
    window.addEventListener('mouseup', stop)
    return () => window.removeEventListener('mouseup', stop)
  }, [selecting])

  function startSelect(date: string, e: React.MouseEvent) {
    if (isPast(date)) return
    setAnchor(date)
    setSelecting(true)
    setFocusDate(date)
    draggingRef.current = false
    mouseDownPosRef.current = { x: e.clientX, y: e.clientY }
    onSelectionChange(new Set([date]))
  }

  function extendSelect(date: string, e: React.MouseEvent) {
    if (!selecting || !anchor || isPast(date)) return
    if (!draggingRef.current) {
      const start = mouseDownPosRef.current
      const traveled = start ? Math.hypot(e.clientX - start.x, e.clientY - start.y) : Infinity
      if (traveled < DRAG_THRESHOLD_PX) return
      draggingRef.current = true
    }
    onSelectionChange(new Set(dateRange(anchor, date)))
  }

  function moveFocus(date: string, extend: boolean) {
    if (date < days[0] || date > days[days.length - 1] || isPast(date)) return
    setFocusDate(date)
    cellRefs.current.get(date)?.focus()
    if (extend) {
      const from = anchor ?? focusDate
      setAnchor(from)
      onSelectionChange(new Set(dateRange(from, date).filter((d) => !isPast(d))))
    }
  }

  function toggleDate(date: string) {
    if (isPast(date)) return
    setAnchor(date)
    const next = new Set(selectedDates)
    if (next.has(date)) next.delete(date)
    else next.add(date)
    onSelectionChange(next)
  }

  return (
    <div className="price-calendar">
      <div className="price-calendar__legend">
        <span>
          <i className="price-calendar__swatch price-calendar__swatch--selected" /> Đang chọn
        </span>
        <span>
          <i className="price-calendar__swatch price-calendar__swatch--sold-out" /> Hết phòng
        </span>
        <span>Kéo thả để chọn nhiều ngày</span>
      </div>

      <div className="price-calendar__grid">
        {WEEKDAY_LABELS.map((label) => (
          <div key={label} className="price-calendar__weekday">
            {label}
          </div>
        ))}
        {Array.from({ length: leadingBlanks }, (_, i) => (
          <div key={`blank-${i}`} />
        ))}
        {days.map((date) => {
          const night = nightsByDate.get(date)
          const past = isPast(date)
          const weekend = mondayIndex(date) >= 5
          const selected = selectedDates.has(date)
          const soldOut = night?.sold_out ?? false
          return (
            <button
              key={date}
              type="button"
              ref={(el) => {
                if (el) cellRefs.current.set(date, el)
                else cellRefs.current.delete(date)
              }}
              className="price-calendar__cell"
              data-selected={selected || undefined}
              data-sold-out={soldOut || undefined}
              data-past={past || undefined}
              tabIndex={date === focusDate ? 0 : -1}
              disabled={past}
              onMouseDown={(e) => startSelect(date, e)}
              onMouseEnter={(e) => extendSelect(date, e)}
              onFocus={() => setFocusDate(date)}
              onKeyDown={(e) => {
                const deltas: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
                if (e.key in deltas) {
                  e.preventDefault()
                  moveFocus(shiftDate(date, deltas[e.key]), e.shiftKey)
                } else if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  toggleDate(date)
                }
              }}
            >
              <span className="price-calendar__day" data-weekend={weekend || undefined}>
                {date.slice(-2)}
              </span>
              {night ? (
                <span className="price-calendar__price">{Number(night.price).toLocaleString('vi-VN')}</span>
              ) : (
                <span className="price-calendar__price price-calendar__price--empty">Chưa có giá</span>
              )}
              {soldOut && <span className="price-calendar__chip">Hết phòng</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}
