import { useTranslation } from 'react-i18next'
import { formatHotelStars } from '../lib/format-stars'
import { formatSourcePlatform } from '../lib/format-source-platform'
import { dayRouteMetrics, tripRouteMetrics } from '../lib/leg'
import { dayColor } from '../lib/map-colors'
import { capitalizeFirst } from '../lib/capitalize'
import RemoteImage from './remote-image'
import type { Day, TripPlan } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

// Nights from the real trip dates — duration_days - 1 is only a fallback for
// when the dates are missing/unusable (never invented).
function nightsFrom(start?: string | null, end?: string | null, fallbackDays?: number): number | null {
  if (start && end) {
    const s = new Date(start).getTime()
    const e = new Date(end).getTime()
    if (Number.isFinite(s) && Number.isFinite(e)) {
      const n = Math.round((e - s) / 86_400_000)
      if (n > 0) return n
    }
  }
  return fallbackDays != null && fallbackDays > 1 ? fallbackDays - 1 : null
}

/**
 * TripOverviewTab — the workspace "Tổng quan" tab (VP-OTA Planner.dc.html:223+).
 * Only stats computable from trip_plan render; anything without a source is
 * dropped entirely (phase-09 §Các ô thống kê): days·nights, places, route km
 * (≈ when any leg used the haversine fallback), travel time (~ prefix, hidden
 * when no real routed minutes exist). Cost is never shown — trip_plan has no
 * cost field.
 *
 * Sections: stat grid → hotel card (stayLabel + real hotel fields) → route-by-day
 * DayCard list (colors from lib/map-colors.ts, shared with the map) → applied
 * adjustments. The budget-split block is not rendered: trip_plan has no budget
 * data (plan.md "Phần chưa làm" #13).
 */
export default function TripOverviewTab({
  tripPlan,
  onPickDay,
  onOpenHotel,
}: {
  tripPlan: TripPlan
  onPickDay: (dayNumber: number) => void
  onOpenHotel?: (hotelId: string) => void
}) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language), { maximumFractionDigits: 1 })

  const { hotel, days = [], adjustments = [], duration_days, start_date, end_date } = tripPlan

  const m = tripRouteMetrics(days)
  const placeCount = days.reduce((n, d) => n + d.items.length, 0)
  const nights = nightsFrom(start_date, end_date, duration_days)

  interface StatItem {
    key: string
    value: string
    unit?: string
    label: string
    icon: string
    iconBg: string
    iconColor: string
    iconBorder: string
  }

  const stats: StatItem[] = []
  if (duration_days != null && duration_days > 0) {
    stats.push({
      key: 'days',
      value: String(duration_days),
      unit: t('statDaysUnit', { defaultValue: 'ngày' }),
      label: nights != null ? t('statNightsWord', { count: nights, defaultValue: `${nights} đêm nghỉ` }) : t('statDays'),
      icon: 'calendar_month',
      iconBg: 'rgba(59, 130, 246, 0.12)',
      iconColor: '#2563EB',
      iconBorder: 'rgba(59, 130, 246, 0.25)',
    })
  }
  if (placeCount > 0) {
    stats.push({
      key: 'places',
      value: String(placeCount),
      unit: t('statPlacesUnit', { defaultValue: 'điểm' }),
      label: t('statPlacesLabel', { defaultValue: 'Điểm tham quan' }),
      icon: 'location_on',
      iconBg: 'rgba(244, 63, 94, 0.12)',
      iconColor: '#E11D48',
      iconBorder: 'rgba(244, 63, 94, 0.25)',
    })
  }
  if (m.distanceKm > 0) {
    stats.push({
      key: 'km',
      value: `${m.approximate ? '≈ ' : ''}${numFmt.format(m.distanceKm)}`,
      unit: t('statKmUnit', { defaultValue: 'km' }),
      label: t('statKmLabel', { defaultValue: 'Quãng đường' }),
      icon: 'route',
      iconBg: 'rgba(16, 185, 129, 0.12)',
      iconColor: '#059669',
      iconBorder: 'rgba(16, 185, 129, 0.25)',
    })
  }
  if (m.durationMins > 0) {
    let durVal = ''
    let durUnit = ''
    if (m.durationMins < 60) {
      durVal = `~${Math.round(m.durationMins)}`
      durUnit = t('statMinsUnit', { defaultValue: 'phút' })
    } else {
      const hours = Math.floor(m.durationMins / 60)
      const mins = Math.round(m.durationMins % 60)
      if (mins === 0) {
        durVal = `~${hours}h`
      } else {
        durVal = `~${hours}h${mins < 10 ? '0' : ''}${mins}`
      }
      durUnit = ''
    }
    stats.push({
      key: 'duration',
      value: durVal,
      unit: durUnit,
      label: t('statTravelTimeLabel', { defaultValue: 'Di chuyển' }),
      icon: 'schedule',
      iconBg: 'rgba(245, 158, 11, 0.12)',
      iconColor: '#D97706',
      iconBorder: 'rgba(245, 158, 11, 0.25)',
    })
  }

  return (
    <div
      className="flex flex-col gap-[14px]"
      style={{ animation: 'vRise .5s cubic-bezier(.22,1,.36,1) both' }}
    >
      {stats.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {stats.map((s, i) => (
            <div
              key={s.key}
              className="px-2.5 py-3 sm:px-3 sm:py-3.5 rounded-[20px] flex flex-col justify-between transition-all duration-200 hover:shadow-md hover:scale-[1.01]"
              style={{
                background: 'var(--g1)',
                border: '1px solid var(--edge)',
                boxShadow: '0 8px 24px -16px rgb(var(--shadow-rgb) / 0.35), inset 0 1px 0 var(--gloss)',
                backdropFilter: 'blur(20px)',
                WebkitBackdropFilter: 'blur(20px)',
                animation: `vFade .5s ${60 + i * 55}ms cubic-bezier(.22,1,.36,1) both`,
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div
                  className="w-7 h-7 rounded-[9px] flex items-center justify-center flex-none"
                  style={{
                    background: s.iconBg,
                    color: s.iconColor,
                    border: `1px solid ${s.iconBorder}`,
                  }}
                >
                  <span className="material-symbols-outlined text-[15px]" aria-hidden="true">
                    {s.icon}
                  </span>
                </div>
              </div>
              <div className="min-w-0">
                <div className="flex items-baseline gap-0.5 whitespace-nowrap">
                  <span className="text-[17.5px] sm:text-[18.5px] font-[650] tracking-[-0.4px] text-on-surface tabular-nums leading-tight whitespace-nowrap">
                    {s.value}
                  </span>
                  {s.unit && (
                    <span className="text-[11px] sm:text-[11.5px] font-[550] text-on-surface-variant leading-tight flex-none ml-0.5 whitespace-nowrap">
                      {s.unit}
                    </span>
                  )}
                </div>
                <div
                  className="text-[11px] font-[450] text-on-surface-muted truncate mt-0.5"
                  title={s.label}
                >
                  {s.label}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {hotel && hotel.name && (
        <div
          role={onOpenHotel && hotel.id ? 'button' : undefined}
          tabIndex={onOpenHotel && hotel.id ? 0 : undefined}
          onClick={() => {
            if (onOpenHotel && hotel.id) {
              onOpenHotel(hotel.id)
            }
          }}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ' ') && onOpenHotel && hotel.id) {
              e.preventDefault()
              onOpenHotel(hotel.id)
            }
          }}
          className={`p-[14px] rounded-[20px] bg-glass-2 border border-edge flex gap-[13px] items-center transition-all duration-200 ${
            onOpenHotel && hotel.id
              ? 'cursor-pointer hover:bg-glass-3 hover:border-primary/40 hover:shadow-md active:scale-[0.99] group'
              : ''
          }`}
        >
          <RemoteImage
            src={hotel.image_url}
            alt={t('hotelImgAlt', { name: hotel.name })}
            className="w-[62px] h-[62px] flex-none rounded-[16px]"
            icon="hotel"
          />
          <div className="flex-1 min-w-0">
            <div className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
              {t('stayLabel')}
            </div>
            <div className="text-[15px] font-[590] tracking-[-0.3px] text-on-surface mt-[2px] truncate group-hover:text-primary transition-colors">
              {hotel.name}
            </div>
            {hotel.star_rating != null && (
              <div className="text-[12px] text-warning tracking-[1px] mt-[2px]" aria-hidden="true">
                {formatHotelStars(hotel.star_rating)}
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5 flex-none">
            {hotel.source_url && hotel.source_platform && (
              <a
                href={hotel.source_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                title={t('detailHandoff', { platform: formatSourcePlatform(hotel.source_platform) })}
                aria-label={t('detailHandoff', { platform: formatSourcePlatform(hotel.source_platform) })}
                className="w-[34px] h-[34px] rounded-full border border-stroke flex items-center justify-center text-on-surface-variant transition-colors hover:bg-glass-3"
              >
                <span className="material-symbols-outlined text-[17px]" aria-hidden="true">
                  open_in_new
                </span>
              </a>
            )}
            {onOpenHotel && hotel.id && (
              <div
                className="w-[34px] h-[34px] rounded-full border border-stroke flex items-center justify-center text-on-surface-variant transition-all duration-200 group-hover:border-primary/40 group-hover:text-primary group-hover:translate-x-0.5"
                title={t('detailTitle')}
                aria-label={t('detailTitle')}
              >
                <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
                  chevron_right
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {days.length > 0 && (
        <div>
          <div className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted mb-[9px]">
            {t('routeByDay')}
          </div>
          <div className="flex flex-col gap-2.5">
            {days.map((day, i) => (
              <DayCard
                key={day.day_number}
                day={day}
                index={i}
                onPick={() => onPickDay(day.day_number)}
              />
            ))}
          </div>
        </div>
      )}

      {adjustments.length > 0 && (
        <div
          className="p-4 rounded-[22px] bg-glass-2 border border-edge flex flex-col gap-3"
          style={{
            boxShadow: '0 8px 24px -16px rgb(var(--shadow-rgb) / 0.3)',
          }}
        >
          <div className="flex items-center gap-1.5 text-[10.5px] font-[600] tracking-[0.08em] uppercase text-primary">
            <span className="material-symbols-outlined text-[15px]">auto_awesome</span>
            <span>{t('adjustmentsApplied')}</span>
          </div>
          <div className="flex flex-col gap-2">
            {adjustments.map((adj, i) => {
              const match = adj.match(/^(Ngày\s*\d+|Day\s*\d+)\s*:\s*(.+)$/i)
              return (
                <div
                  key={i}
                  className="flex items-center gap-2.5 p-2.5 px-3 rounded-[14px] bg-glass-1 border border-edge/60 text-[12.5px] font-normal text-on-surface"
                >
                  {match ? (
                    <>
                      <span className="px-2 py-0.5 rounded-md text-[10.5px] font-[600] uppercase tracking-wide bg-primary/10 text-primary border border-primary/20 flex-none leading-none">
                        {match[1]}
                      </span>
                      <span className="flex-1 min-w-0 leading-relaxed text-on-surface/90">
                        {match[2]}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="material-symbols-outlined text-[16px] text-emerald-500 flex-none leading-none" aria-hidden="true">
                        check_circle
                      </span>
                      <span className="flex-1 min-w-0 leading-relaxed text-on-surface/90">
                        {adj}
                      </span>
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

/** Local DayCard (DayCard.dc.html) — lives inside this file per phase-09; the
 *  old day-card.tsx is deleted. Day color comes from lib/map-colors.ts so the
 *  overview card and the Phase 10 map route never drift apart. */
function DayCard({ day, index, onPick }: { day: Day; index: number; onPick: () => void }) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language), { maximumFractionDigits: 1 })

  const color = dayColor(day.day_number)
  const m = dayRouteMetrics(day.items)
  const itemCount = day.items.length
  const kmPart = m.distanceKm > 0 ? `${m.approximate ? '≈ ' : ''}${numFmt.format(m.distanceKm)} km` : null
  const durationPart =
    m.durationMins > 0
      ? m.durationMins < 60
        ? `~${Math.round(m.durationMins)} phút`
        : `~${Math.floor(m.durationMins / 60)}h ${Math.round(m.durationMins % 60)}p`
      : null

  return (
    <button
      type="button"
      onClick={onPick}
      className="group w-full text-left flex items-center gap-3.5 rounded-[20px] p-3.5 sm:p-4 cursor-pointer border border-edge bg-glass-2 transition-all duration-200 hover:bg-glass-3 hover:border-primary/40 hover:shadow-md active:scale-[0.99]"
      style={{
        animation: `vFade .5s ${120 + index * 70}ms ease both`,
        boxShadow: '0 4px 18px -12px rgb(var(--shadow-rgb) / 0.25)',
      }}
    >
      {/* Day Badge */}
      <div
        className="w-11 h-11 rounded-[14px] flex flex-col items-center justify-center flex-none shadow-sm transition-transform duration-200 group-hover:scale-105"
        style={{
          background: `linear-gradient(135deg, ${color}, ${color}dd)`,
          color: '#fff',
          boxShadow: `0 4px 12px -3px ${color}66`,
        }}
      >
        <span className="text-[9px] font-[600] uppercase tracking-wider opacity-90 leading-none">
          {t('dayWord', { defaultValue: 'Ngày' })}
        </span>
        <span className="text-[16px] font-[700] leading-none mt-0.5">
          {day.day_number}
        </span>
      </div>

      {/* Main Info */}
      <div className="flex-1 min-w-0">
        <div className="text-[14px] font-[590] tracking-[-0.2px] text-on-surface truncate group-hover:text-primary transition-colors">
          {day.theme ? capitalizeFirst(day.theme) : `${t('dayWord', { defaultValue: 'Ngày' })} ${day.day_number}`}
        </div>
        <div className="flex items-center gap-2 text-[11.5px] text-on-surface-muted font-normal mt-1 flex-wrap">
          {itemCount > 0 && (
            <span className="inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px] text-rose-500/80">place</span>
              <span>{itemCount} {t('statPlacesUnit', { defaultValue: 'điểm' })}</span>
            </span>
          )}
          {kmPart && (
            <>
              <span className="opacity-40">·</span>
              <span className="inline-flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px] text-emerald-500/80">route</span>
                <span>{kmPart}</span>
              </span>
            </>
          )}
          {durationPart && (
            <>
              <span className="opacity-40">·</span>
              <span className="inline-flex items-center gap-1">
                <span className="material-symbols-outlined text-[13px] text-amber-500/80">schedule</span>
                <span>{durationPart}</span>
              </span>
            </>
          )}
        </div>
      </div>

      {/* Right chevron button */}
      <div className="w-8 h-8 rounded-full border border-stroke flex items-center justify-center text-on-surface-variant flex-none transition-all duration-200 group-hover:border-primary/40 group-hover:text-primary group-hover:translate-x-1 group-hover:bg-glass-3">
        <span className="material-symbols-outlined text-[18px]" aria-hidden="true">
          chevron_right
        </span>
      </div>
    </button>
  )
}
