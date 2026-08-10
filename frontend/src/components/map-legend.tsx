import { useTranslation } from 'react-i18next'
import { dayColor } from '../lib/map-colors'
import type { RouteSegment } from '../lib/route-segments'

/**
 * MapLegend — day-color swatches + vehicle-profile legend, glass card
 * (design-fidelity-checklist.md §Phase 10 — Map: padding 11px 14px, radius
 * 18, bg --g2, blur 20 saturate 1.6, border --edge, max-width 280px).
 *
 * Content rule: only shows what's really in `segments` — a day not
 * currently rendered gets no swatch, an all-driving itinerary gets no
 * "đi bộ" row, and there is never a cable-car entry (no Mapbox profile, no
 * DB signal for it — out of scope project-wide, see plan.md "Phần chưa làm" #1).
 */
export default function MapLegend({ segments, className }: { segments: RouteSegment[]; className?: string }) {
  const { t } = useTranslation()

  if (segments.length === 0) return null

  const dayNumbers = [...new Set(segments.map((s) => s.dayNumber))].sort((a, b) => a - b)
  const hasDriving = segments.some((s) => !s.isFallback && s.profile !== 'walking')
  const hasWalking = segments.some((s) => !s.isFallback && s.profile === 'walking')
  const hasFallback = segments.some((s) => s.isFallback)

  return (
    <div
      className={`rounded-[18px] border border-edge bg-glass-2 ${className ?? ''}`}
      style={{ padding: '11px 14px', backdropFilter: 'blur(20px) saturate(1.6)', maxWidth: '280px' }}
    >
      {dayNumbers.length > 1 && (
        <div className="flex flex-col gap-1.5 mb-2">
          {dayNumbers.map((day) => (
            <div key={day} className="flex items-center gap-[7px]">
              <span className="w-[9px] h-[9px] rounded-full flex-none" style={{ background: dayColor(day) }} aria-hidden="true" />
              <span className="text-[11.5px] text-on-surface-variant">
                {t('dayWord')} {day}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-col gap-1.5">
        {hasDriving && (
          <div className="flex items-center gap-[7px]">
            <svg width="16" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="16" y2="4" stroke="var(--t2)" strokeWidth="2" />
            </svg>
            <span className="text-[11.5px] text-on-surface-variant">{t('mapLegendDriving')}</span>
          </div>
        )}
        {hasWalking && (
          <div className="flex items-center gap-[7px]">
            <svg width="16" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="16" y2="4" stroke="var(--t2)" strokeWidth="2" strokeDasharray="3 2" />
            </svg>
            <span className="text-[11.5px] text-on-surface-variant">{t('mapLegendWalking')}</span>
          </div>
        )}
        {hasFallback && (
          <div className="flex items-center gap-[7px]">
            <svg width="16" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="16" y2="4" stroke="var(--t4)" strokeWidth="1.5" strokeDasharray="1 2" />
            </svg>
            <span className="text-[11.5px] text-on-surface-variant">{t('mapLegendFallback')}</span>
          </div>
        )}
      </div>
    </div>
  )
}
