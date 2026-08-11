import { useTranslation } from 'react-i18next'
import { dayColor, legColor } from '../lib/map-colors'
import type { RouteSegment } from '../lib/route-segments'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

function legText(segment: RouteSegment, t: (key: string, values?: Record<string, unknown>) => string, language: string) {
  const number = new Intl.NumberFormat(NUM_LOCALE(language), { maximumFractionDigits: 1 })
  if (segment.durationMins == null) return t('legCrowFly', { km: number.format(segment.distanceKm) })
  const profile = segment.profile ? t(`routeProfile.${segment.profile}`, { defaultValue: '' }) : ''
  const duration = t('legDurationMins', { mins: number.format(segment.durationMins) })
  return [profile, duration].filter(Boolean).join(' · ')
}

export default function MapLegend({
  segments,
  mode,
  onSegmentHover,
  className,
}: {
  segments: RouteSegment[]
  mode: 'overview' | 'day'
  onSegmentHover?: (segKey: string | null) => void
  className?: string
}) {
  const { t, i18n } = useTranslation()
  if (segments.length === 0) return null

  const days = [...new Set(segments.map((segment) => segment.dayNumber))].sort((a, b) => a - b)
  return (
    <div
      className={`rounded-[18px] border border-edge bg-glass-2 ${className ?? ''}`}
      style={{ padding: '12px 14px', backdropFilter: 'blur(20px) saturate(1.6)', WebkitBackdropFilter: 'blur(20px) saturate(1.6)', boxShadow: '0 10px 26px -14px rgb(var(--shadow-rgb) / .4)', maxWidth: 290 }}
    >
      <div className="mb-2 text-[10px] font-[590] uppercase tracking-[.1em] text-on-surface-muted">
        {mode === 'overview' ? t('mapLegendOverview') : t('mapLegendDayRoutes')}
      </div>
      {mode === 'overview' ? (
        <div className="flex flex-col gap-1.5">
          {days.map((day) => (
            <div key={day} className="flex items-center gap-2 text-[11.5px] text-on-surface-variant">
              <span className="h-[3px] w-4 rounded-full" style={{ background: dayColor(day) }} aria-hidden="true" />
              {t('dayWord')} {day}
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {segments.map((segment) => (
            <button
              key={segment.segKey}
              type="button"
              className="flex items-center gap-1.5 rounded-full border border-transparent px-1.5 py-1 text-left text-[10.5px] text-on-surface-variant transition-colors hover:border-edge hover:bg-glass-3"
              onMouseEnter={() => onSegmentHover?.(segment.segKey)}
              onMouseLeave={() => onSegmentHover?.(null)}
              onFocus={() => onSegmentHover?.(segment.segKey)}
              onBlur={() => onSegmentHover?.(null)}
            >
              <span className="h-[3px] w-4 shrink-0 rounded-full" style={{ background: legColor(segment.legIndex) }} aria-hidden="true" />
              <b className="font-[590] text-on-surface">{segment.legIndex + 1}→{segment.legIndex + 2}</b>
              <span>{legText(segment, t, i18n.language)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
