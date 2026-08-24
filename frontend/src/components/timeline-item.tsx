import { useTranslation } from 'react-i18next'
import { placeNameFromActivity } from '../lib/activity-name'
import { formatItemDuration, minutesBetween, stripSeconds } from '../lib/item-duration'
import { legBetween } from '../lib/leg'
import { dayColor, legColor } from '../lib/map-colors'
import { itemSyncId } from '../lib/map-sync-id'
import RemoteImage from './remote-image'
import type { DayItem } from '../types'

const NUM_LOCALE = (lang: string) => (lang === 'vi' ? 'vi-VN' : 'en-US')

// RemoteImage fallback icon keyed by the itinerary kind codes the backend
// actually emits (trip_formatter.py:325). Unknown kinds fall back to 'place'.
const THUMB_ICONS: Record<string, string> = {
  attraction: 'attractions',
  breakfast: 'restaurant',
  lunch: 'restaurant',
  dinner: 'restaurant',
  coffee: 'local_cafe',
  transport: 'directions_car',
  hotel: 'hotel',
}

function getKindStyle(kind?: string | null) {
  switch (kind) {
    case 'breakfast':
    case 'lunch':
    case 'dinner':
      return 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/25'
    case 'attraction':
      return 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300 border-indigo-500/25'
    case 'coffee':
      return 'bg-orange-500/10 text-orange-700 dark:text-orange-300 border-orange-500/25'
    case 'hotel':
      return 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/25'
    case 'transport':
      return 'bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/25'
    default:
      return 'bg-fill text-on-surface-variant border-stroke'
  }
}

function getVehicleIcon(profile?: string | null): string {
  switch (profile) {
    case 'foot-walking':
    case 'walking':
      return 'directions_walk'
    case 'driving-car':
    case 'driving':
    case 'car':
      return 'directions_car'
    case 'cycling-regular':
    case 'cycling':
      return 'two_wheeler'
    default:
      return 'route'
  }
}

function isNoteRedundant(activity?: string | null, placeName?: string | null): boolean {
  if (!activity || !placeName) return true
  const cleanAct = activity
    .toLowerCase()
    .replace(/^(ăn sáng|ăn trưa|ăn tối|tham quan|thưởng thức|uống cà phê|nghỉ ngơi|check-in|nhận phòng)\s+(tại|ở)\s+/i, '')
    .trim()
  return cleanAct === placeName.toLowerCase().trim()
}

/**
 * TimelineItem — one itinerary row plus the leg pill that follows it
 * (TimelineItem.dc.html).
 */
export default function TimelineItem({
  item,
  index,
  dayNumber,
  next,
  focusedId,
  onOpen,
  hoveredId,
  onHoverChange,
}: {
  item: DayItem
  index: number
  dayNumber: number
  next: DayItem | null | undefined
  focusedId: string | null
  onOpen: (item: DayItem) => void
  /** Phase 10 map hover sync (lib/map-sync-id.ts ids) — optional so this component still works standalone. */
  hoveredId?: string | null
  onHoverChange?: (id: string | null) => void
}) {
  const { t, i18n } = useTranslation()
  const numFmt = new Intl.NumberFormat(NUM_LOCALE(i18n.language), { maximumFractionDigits: 1 })

  const canOpen =
    (item.reference_type === 'Attraction' || item.reference_type === 'Hotel') &&
    typeof item.reference_id === 'string' &&
    item.reference_id.length > 0
  const focused = canOpen && focusedId != null && item.reference_id === focusedId
  const syncId = itemSyncId(dayNumber, item, index)
  const isHovered = hoveredId != null && hoveredId === syncId

  const leg = legBetween(item, next)
  const hasLeg = leg.kind !== 'none'

  const dotBg = dayColor(dayNumber)
  const pillColor = legColor(index)
  const thumbIcon = THUMB_ICONS[item.kind ?? ''] ?? 'place'

  const kindLabel = item.kind
    ? t(`kind${item.kind[0]?.toUpperCase() ?? ''}${item.kind.slice(1)}`, { defaultValue: item.kind })
    : ''

  const placeName = placeNameFromActivity(item.activity)
  const activityNote = placeName !== item.activity ? item.activity : ''
  const noteRedundant = isNoteRedundant(item.activity, placeName)

  const durationMinutes = minutesBetween(item.start_time, item.end_time)
  const meta = durationMinutes != null ? formatItemDuration(durationMinutes, t) : ''

  // A real <button> when openable (keyboard focus + Enter/Space, screen
  // readers announce it as interactive) — plain <div> otherwise.
  const Row = canOpen ? 'button' : 'div'

  return (
    <div className="relative flex flex-col" style={{ animation: `vIn .55s ${index * 65}ms cubic-bezier(.22,1,.36,1) both` }}>
      <Row
        type={canOpen ? 'button' : undefined}
        className="timeline-item rounded-[22px] border flex items-center gap-3 p-3 sm:p-3.5 w-full text-left transition-all duration-200 group"
        data-clickable={canOpen ? 'true' : undefined}
        data-focused={focused ? 'true' : undefined}
        data-hovered={isHovered ? 'true' : undefined}
        data-card={syncId}
        onClick={canOpen ? () => onOpen(item) : undefined}
        onMouseEnter={() => onHoverChange?.(syncId)}
        onMouseLeave={() => onHoverChange?.(null)}
        style={{ cursor: canOpen ? 'pointer' : 'default' }}
      >
        {/* Left column: Time & Order Node */}
        <div className="flex flex-col items-center justify-center gap-1.5 flex-none w-[44px]">
          {item.start_time != null ? (
            <div className="text-[12px] font-[650] text-on-surface tabular-nums leading-none">
              {stripSeconds(item.start_time)}
            </div>
          ) : (
            <div className="text-[11px] font-[500] text-on-surface-muted tabular-nums leading-none">
              --:--
            </div>
          )}
          <div
            className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-[700] text-white shadow-xs transition-transform duration-200 group-hover:scale-110"
            style={{
              background: `linear-gradient(135deg, ${dotBg}, ${dotBg}dd)`,
              boxShadow: `0 2px 8px -1px ${dotBg}88`,
            }}
          >
            {index + 1}
          </div>
        </div>

        {/* Thumbnail Image */}
        <RemoteImage
          src={item.image_url}
          alt={t('placeImgAlt', { name: item.activity })}
          className="w-[52px] h-[52px] flex-none rounded-[14px] object-cover border border-edge/40 shadow-xs"
          icon={thumbIcon}
        />

        {/* Content Body */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[14px] font-[600] tracking-[-0.2px] text-on-surface truncate group-hover:text-primary transition-colors">
              {placeName}
            </span>
            {kindLabel && (
              <span className={`text-[10px] font-[600] px-2 py-0.5 rounded-full border leading-tight ${getKindStyle(item.kind)}`}>
                {kindLabel}
              </span>
            )}
          </div>

          {!noteRedundant && activityNote && (
            <div className="text-[12px] text-on-surface-muted font-normal leading-relaxed mt-1 line-clamp-2">
              {activityNote}
            </div>
          )}

          {meta && (
            <div className="inline-flex items-center gap-1 text-[11px] font-[500] text-on-surface-muted mt-1 px-2 py-0.5 rounded-md bg-fill/60 border border-edge/40 leading-none">
              <span className="material-symbols-outlined text-[13px] text-amber-500/80 leading-none">
                schedule
              </span>
              <span>{meta}</span>
            </div>
          )}
        </div>

        {/* Right arrow if openable */}
        {canOpen && (
          <div className="w-7 h-7 rounded-full border border-stroke flex items-center justify-center text-on-surface-variant flex-none opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all duration-200">
            <span className="material-symbols-outlined text-[16px]">chevron_right</span>
          </div>
        )}
      </Row>

      {/* Transit Leg Connector */}
      {hasLeg && (
        <div className="flex items-center gap-2 my-2 ml-[22px] py-0.5 pl-3.5 border-l-2 border-dashed border-edge/80">
          <div
            className="flex items-center gap-2 py-1 px-3 rounded-full bg-glass-1 border text-[11px] text-on-surface-muted shadow-xs transition-all hover:bg-glass-2"
            style={{ borderColor: `${pillColor}33` }}
          >
            <span className="material-symbols-outlined text-[13px] text-primary flex-none leading-none">
              {getVehicleIcon(leg.profile)}
            </span>
            <span className="font-semibold text-on-surface/90">
              {leg.profile ? `${t(`routeProfile.${leg.profile}`, { defaultValue: '' })} · ` : ''}
              {numFmt.format(leg.distanceKm)} km
            </span>
            {leg.durationMins > 0 && (
              <>
                <span className="opacity-40">·</span>
                <span className="font-medium text-on-surface-muted">
                  ~{leg.durationMins < 60 ? `${Math.round(leg.durationMins)} phút` : `${Math.floor(leg.durationMins / 60)}h ${Math.round(leg.durationMins % 60)}p`}
                </span>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
