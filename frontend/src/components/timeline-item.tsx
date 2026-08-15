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

/**
 * TimelineItem — one itinerary row plus the leg pill that follows it
 * (TimelineItem.dc.html). The left 44px column shows the start time (hidden
 * when null — the numbered dot stays, per phase-09: never invent an hour),
 * stripped of the backend's always-":00" seconds, and a 24px numbered dot
 * tinted with the day color; the 52×52 thumb is the item's real photo
 * (item.image_url, already on the wire — trip_formatter.py:335) via the
 * shared RemoteImage fallback chain, keyed by kind for the icon shown while
 * loading/missing.
 *
 * Content is three lines, matching the design's name/note/meta split:
 *   - name: the place's own name (activity-name.ts strips the backend's
 *     "Ăn trưa tại "-style lead-in off `item.activity`) + kind badge.
 *   - note (design's `it.note` — dropped pre-phase-09 for lack of a backend
 *     field, see plan.md "Phần chưa làm" #24): the full original `item.activity`
 *     sentence, e.g. "Ăn trưa tại NHÀ HÀNG NGON". Real data, just re-slotted —
 *     shown only when it actually adds something beyond the bare name.
 *   - meta: a duration ("1 tiếng"), computed from the real start/end fields,
 *     replacing a literal "start – end" range.
 *
 * Click affordance is gated on the real contract: only items with
 * reference_type 'Attraction' AND a non-empty reference_id open Place Detail
 * Focus Mode. Everything else renders with the default cursor and no hover
 * elevation, so the UI never invites a click that opens nothing (phase-09
 * §Phi chức năng). The focused highlight (accent ring) tracks the id the
 * detail panel is showing.
 *
 * The pill is the four-state legBetween() semantics: real route
 * (vehicle · km · ~mins), identical coordinates ("cùng địa điểm" — never
 * "0 km · 0 phút"), straight-line fallback (km only, no vehicle/duration), or
 * omitted entirely when coordinates are missing.
 *
 * Row body click -> onOpen (Place Detail Focus Mode directly). Phase 10.5
 * briefly routed this through a preview step with a trailing chevron button;
 * the UI-fix pass removed that button entirely per explicit spec ("Xóa nút
 * Xem chi tiết dạng Chevron") — the row itself is the only interactive
 * affordance again, matching HotelOptionCard's own explicit "Xem chi tiết"
 * button's philosophy of a single, direct click target (that button lives
 * one level up in HotelOptionCard and is untouched by this change).
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
    item.reference_type === 'Attraction' &&
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
  // Only worth its own line when it says more than the bare name already does.
  const activityNote = placeName !== item.activity ? item.activity : ''

  // Real metadata only: a duration computed from the item's own start/end
  // window. Nothing is invented — null (missing/unparseable/non-positive
  // window) renders nothing rather than a guess.
  const durationMinutes = minutesBetween(item.start_time, item.end_time)
  const meta = durationMinutes != null ? formatItemDuration(durationMinutes, t) : ''

  function legLabel(): string {
    switch (leg.kind) {
      case 'route': {
        // Unknown profile → drop the vehicle label but keep km + duration
        // (phase-09: never render a raw profile code).
        const vehicle = leg.profile ? t(`routeProfile.${leg.profile}`, { defaultValue: '' }) : ''
        const parts: string[] = []
        if (vehicle) parts.push(vehicle)
        parts.push(t('legDistanceKm', { km: numFmt.format(leg.distanceKm) }))
        parts.push(t('legDurationMins', { mins: numFmt.format(leg.durationMins) }))
        return parts.join(' · ')
      }
      case 'same-place':
        return t('legSamePlace')
      case 'crow-fly':
        return t('legCrowFly', { km: numFmt.format(leg.distanceKm) })
      case 'none':
        return ''
    }
  }

  // A real <button> when openable (keyboard focus + Enter/Space, screen
  // readers announce it as interactive) — plain <div> otherwise, so a row
  // that opens nothing is never in the tab order (review finding M5).
  const Row = canOpen ? 'button' : 'div'

  return (
    <div style={{ animation: `vIn .55s ${index * 65}ms cubic-bezier(.22,1,.36,1) both` }}>
      <Row
        type={canOpen ? 'button' : undefined}
        className="timeline-item rounded-[20px] border flex gap-3 p-[13px] w-full text-left"
        data-clickable={canOpen ? 'true' : undefined}
        data-focused={focused ? 'true' : undefined}
        data-hovered={isHovered ? 'true' : undefined}
        data-card={syncId}
        onClick={canOpen ? () => onOpen(item) : undefined}
        onMouseEnter={() => onHoverChange?.(syncId)}
        onMouseLeave={() => onHoverChange?.(null)}
        style={{ cursor: canOpen ? 'pointer' : 'default' }}
      >
        <div className="flex flex-col items-center gap-[6px] flex-none w-[44px]">
          {item.start_time != null && (
            <div className="text-[11.5px] font-[530] text-on-surface-variant tabular-nums">
              {stripSeconds(item.start_time)}
            </div>
          )}
          <div
            className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-[590] text-on-primary"
            style={{ background: dotBg, boxShadow: `0 4px 10px -4px ${dotBg}` }}
          >
            {index + 1}
          </div>
        </div>
        <RemoteImage
          src={item.image_url}
          alt={t('placeImgAlt', { name: item.activity })}
          className="w-[52px] h-[52px] flex-none rounded-[14px]"
          icon={thumbIcon}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-[7px]">
            <div className="text-[14px] font-[590] tracking-[-0.2px] text-on-surface truncate">
              {placeName}
            </div>
            {kindLabel && (
              <div className="text-[9.5px] px-[7px] py-[2px] rounded-full bg-fill text-on-surface-variant whitespace-nowrap">
                {kindLabel}
              </div>
            )}
          </div>
          {activityNote && (
            <div className="text-[11.5px] text-on-surface-muted font-normal leading-[1.45] text-pretty mt-[3px]">
              {activityNote}
            </div>
          )}
          {meta && <div className="text-[11px] text-on-surface-muted mt-[5px]">{meta}</div>}
        </div>
      </Row>
      {hasLeg && (
        <div className="flex items-center gap-[9px] py-[6px] pl-[52px]">
          <div
            className="w-[2px] h-[22px] rounded-[2px]"
            style={{ background: `repeating-linear-gradient(to bottom, ${pillColor} 0 4px, transparent 4px 8px)` }}
          />
          <div
            className="flex items-center gap-[7px] py-[3px] pr-[10px] pl-[8px] rounded-full bg-glass-1"
            style={{ border: `1px solid ${pillColor}44` }}
          >
            <div className="w-[7px] h-[7px] rounded-full" style={{ background: pillColor }} />
            <div className="text-[10.5px] font-[530] text-on-surface-muted tabular-nums">
              {index + 1} → {index + 2}
            </div>
            <div className="text-[11px] text-on-surface-muted font-normal">{legLabel()}</div>
          </div>
        </div>
      )}
    </div>
  )
}
