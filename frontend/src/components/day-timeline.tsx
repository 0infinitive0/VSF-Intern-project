import { useTranslation } from 'react-i18next'
import TimelineItem from './timeline-item'
import { dayRouteMetrics } from '../lib/leg'
import { capitalizeFirst } from '../lib/capitalize'
import { dayStayPoints } from '../lib/day-stay-points'
import type { Day, DayItem } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

/**
 * DayTimeline — one day tab of the workspace (VP-OTA Planner.dc.html:281-293).
 * Header row: big "Ngày N" title plus a small metadata sub line (theme · route
 * summary). The route figures come from dayRouteMetrics over the day's real
 * legs: km summed from route_to_next (haversine fallback prefixed with ≈ when
 * a leg was approximate) and duration shown only when real routed minutes
 * exist — a whole day of fallback legs has no duration, and none is invented.
 *
 * Below, the item list with leg pills between consecutive pairs (TimelineItem
 * renders both; the last item of the day has no next item, so no pill).
 */
export default function DayTimeline({
  day,
  hotel,
  focusedId,
  onOpen,
  onOpenHotel,
  hoveredId,
  onHoverChange,
}: {
  day: Day
  hotel: { id?: string | null; name?: string | null } | null | undefined
  focusedId: string | null
  onOpen: (item: DayItem) => void
  onOpenHotel?: (hotelId: string) => void
  /** Phase 10 map hover sync — optional so this component still works standalone. */
  hoveredId?: string | null
  onHoverChange?: (id: string | null) => void
}) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language), { maximumFractionDigits: 1 })

  const m = dayRouteMetrics(day.items)
  const hasRoute = m.distanceKm > 0 || m.durationMins > 0
  const kmPart = `${m.approximate ? '≈ ' : ''}${t('legDistanceKm', { km: numFmt.format(m.distanceKm) })}`
  const routePart =
    m.durationMins > 0 ? `${kmPart} · ${t('legDurationMins', { mins: numFmt.format(m.durationMins) })}` : kmPart
  const daySub = [day.theme ? capitalizeFirst(day.theme) : null, hasRoute ? routePart : null]
    .filter((x): x is string => Boolean(x))
    .join(' · ')
  const stayPoints = dayStayPoints(hotel)
  const startPoint = stayPoints.find((stayPoint) => stayPoint.position === 'start')
  const endPoint = stayPoints.find((stayPoint) => stayPoint.position === 'end')

  return (
    <div style={{ animation: 'vRise .45s cubic-bezier(.22,1,.36,1) both' }}>
      <div className="flex items-baseline gap-[10px] mb-[14px]">
        <div className="text-[22px] font-[590] tracking-[-0.7px] leading-[1.15] text-on-surface">
          {t('dayWord')} {day.day_number}
        </div>
        {daySub && <div className="text-[12px] text-on-surface-muted font-normal">{daySub}</div>}
      </div>
      <div className="flex flex-col">
        {startPoint && (
          <div
            role={onOpenHotel && hotel?.id ? 'button' : undefined}
            tabIndex={onOpenHotel && hotel?.id ? 0 : undefined}
            onClick={() => {
              if (onOpenHotel && hotel?.id) onOpenHotel(hotel.id)
            }}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && onOpenHotel && hotel?.id) {
                e.preventDefault()
                onOpenHotel(hotel.id)
              }
            }}
            className={`flex items-center gap-3 py-2 px-[13px] rounded-[16px] bg-glass-2 border border-edge text-[12px] text-on-surface-muted transition-all duration-200 ${
              onOpenHotel && hotel?.id
                ? 'cursor-pointer hover:bg-glass-3 hover:border-primary/40 hover:text-on-surface'
                : ''
            }`}
          >
            <span className="material-symbols-outlined text-[18px] text-primary" aria-hidden="true">hotel</span>
            <span className="flex-1">{t('dayStartAtHotel', { hotel: startPoint.hotelName })}</span>
            {onOpenHotel && hotel?.id && (
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant opacity-70" aria-hidden="true">
                chevron_right
              </span>
            )}
          </div>
        )}
        {day.items.map((item, i) => (
          <TimelineItem
            key={item.order_index ?? i}
            item={item}
            index={i}
            dayNumber={day.day_number}
            next={day.items[i + 1]}
            focusedId={focusedId}
            onOpen={onOpen}
            hoveredId={hoveredId}
            onHoverChange={onHoverChange}
          />
        ))}
        {endPoint && (
          <div
            role={onOpenHotel && hotel?.id ? 'button' : undefined}
            tabIndex={onOpenHotel && hotel?.id ? 0 : undefined}
            onClick={() => {
              if (onOpenHotel && hotel?.id) onOpenHotel(hotel.id)
            }}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && onOpenHotel && hotel?.id) {
                e.preventDefault()
                onOpenHotel(hotel.id)
              }
            }}
            className={`flex items-center gap-3 py-2 px-[13px] rounded-[16px] bg-glass-2 border border-edge text-[12px] text-on-surface-muted transition-all duration-200 ${
              onOpenHotel && hotel?.id
                ? 'cursor-pointer hover:bg-glass-3 hover:border-primary/40 hover:text-on-surface'
                : ''
            }`}
          >
            <span className="material-symbols-outlined text-[18px] text-primary" aria-hidden="true">hotel</span>
            <span className="flex-1">{t('dayEndAtHotel', { hotel: endPoint.hotelName })}</span>
            {onOpenHotel && hotel?.id && (
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant opacity-70" aria-hidden="true">
                chevron_right
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
