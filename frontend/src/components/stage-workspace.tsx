import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import DayTimeline from './day-timeline'
import MapView, { type MapMarkerSpec } from './map-view'
import PlaceDetailPanel from './place-detail-panel'
import TripOverviewTab from './trip-overview-tab'
import { placeNameFromActivity } from '../lib/activity-name'
import { useMapSync } from '../hooks/use-map-sync'
import { legBetween, type Leg } from '../lib/leg'
import { formatTripDateRange } from '../lib/format-trip-dates'
import { itemSyncId, suggestedPlaceSyncId, TRIP_HOTEL_SYNC_KEY } from '../lib/map-sync-id'
import { buildDaySegments, buildTripSegments } from '../lib/route-segments'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { Theme } from '../hooks/use-theme'
import type { ChatState, Day, DayItem } from '../types'

type FocusModeApi = ReturnType<typeof useFocusMode>
type TabKey = 'overview' | number

// The design's "Tạo lại" (V-OTA Planner.dc.html:206 regenerate) posts a plain
// natural-language message through onSend — no new verb, no new endpoint. The
// string is translated exactly as the two-step hotel confirm pattern.
const REGENERATE_VI = 'Tạo lại lịch trình giúp mình'
const REGENERATE_EN = 'Please regenerate the itinerary'

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
 * StageWorkspace — the Phase 9 workspace (V-OTA Planner.dc.html:192-295): a
 * glass trip header (logo, destination, date-range/days/nights/people meta,
 * one "Tạo lại" button — no "Chia sẻ", user decision 06/08/2026) over a
 * segmented tab bar (Tổng quan + one tab per day) and the itinerary scroll
 * column, alongside the map. All figures come from the existing `trip_plan`
 * contract — nothing new is invented.
 *
 * Focus mode reuses use-focus-mode: clicking an openable timeline item
 * (`reference_type 'Attraction'` + reference_id — the same gate as
 * TimelineItem) collapses chat (app-shell) and the map, widens the itinerary
 * column 470→520px per the design's itinW, and joins the detail panel as a
 * third flex sibling. Picking a tab resets focus; the itinerary scroll
 * position is captured on open and restored on close (phase-09).
 */
export default function StageWorkspace({
  state,
  focusMode,
  onSend,
  theme,
}: {
  state: ChatState
  focusMode: FocusModeApi
  onSend: (text: string) => void
  theme: Theme
}) {
  const { t, i18n } = useTranslation()
  const tripPlan = state.tripPlan
  // Memoized so `days` is referentially stable across re-renders that don't
  // change tripPlan (e.g. Phase 10 hover state) — the segments/markers
  // useMemo below depend on it and must not recompute (re-decode polylines)
  // on every mousemove.
  const days = useMemo(() => tripPlan?.days ?? [], [tripPlan])
  const mapSync = useMapSync()

  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  // Transient, per-component (not persisted) — resets to visible whenever
  // this component remounts. A fresh batch of suggestedPlaces from a new
  // turn does NOT reset it back to true: the user's ẩn/hiện choice should
  // survive follow-up chat turns, not just the one reply that produced it.
  const [showSuggested, setShowSuggested] = useState(true)

  // `trip_plan` gets a fresh object identity on every chat turn (each reply
  // re-serializes it), so an effect keyed on the object would jump the user
  // back to Tổng quan on every message. Derive the displayed tab instead of
  // syncing it via an effect: falls back to Tổng quan only when the stored
  // tab's day genuinely no longer exists in the (possibly shrunk) plan.
  const resolvedTab: TabKey =
    typeof activeTab === 'number' && !days.some((d) => d.day_number === activeTab) ? 'overview' : activeTab

  const focusedId = focusMode.focus?.kind === 'place' ? focusMode.focus.id : null

  // The focused item's timeline context — day number, start time, kind and the
  // leg INTO it (previous item's route_to_next). First-of-day → no leg.
  // Computed here (ahead of the hooks below, not after the `!tripPlan` early
  // return) so `focused` can be gated on it: a chat turn can replace the plan
  // while a place is focused, and if that item is gone, `focused` must not
  // stay true with nothing to show (review finding H3). useMemo (not a plain
  // `let`) so its object identity is stable across renders when nothing it
  // depends on changed — required for the lastContext effect below, which
  // would otherwise re-fire (and re-render) every render on a "new" object
  // that's actually the same context.
  const context = useMemo<{ day: Day; item: DayItem; index: number; routeLeg: Leg } | null>(() => {
    if (!focusedId) return null
    for (const day of days) {
      for (let i = 0; i < day.items.length; i++) {
        const item = day.items[i]
        if (item.reference_type === 'Attraction' && item.reference_id === focusedId) {
          return { day, item, index: i, routeLeg: i === 0 ? { kind: 'none' } : legBetween(day.items[i - 1], item) }
        }
      }
    }
    return null
  }, [days, focusedId])
  const focused = focusedId != null && context != null

  // PlaceDetailPanel is always mounted now (never conditionally rendered) so
  // it can animate its own close, not just its open — see the map/detail
  // wrapper styles below. That means its CONTENT must outlive `context`
  // going back to null the instant focus closes, or the close transition
  // would fade out an already-blank panel. `lastContext` is the sticky "last
  // place actually viewed" value fed to PlaceDetailPanel; `focused` itself
  // still drives every visual open/closed state, same pattern as
  // stage-hotels.tsx's lastFocusedId.
  const [lastContext, setLastContext] = useState(context)
  useEffect(() => {
    if (context != null) setLastContext(context)
  }, [context])

  const itinRef = useRef<HTMLDivElement>(null)
  const savedScroll = useRef(0)

  function pickTab(tab: TabKey) {
    setActiveTab(tab)
    focusMode.closeFocus()
  }

  function openFocus(item: DayItem) {
    if (!(item.reference_type === 'Attraction' && item.reference_id)) return
    savedScroll.current = itinRef.current?.scrollTop ?? 0
    focusMode.openFocus({ kind: 'place', id: item.reference_id })
  }

  function handleOpenDetail(marker: MapMarkerSpec) {
    if (!marker.openId) return
    for (const day of days) {
      const item = day.items.find((it) => it.reference_type === 'Attraction' && it.reference_id === marker.openId)
      if (item) {
        openFocus(item)
        return
      }
    }
  }

  useLayoutEffect(() => {
    if (!focused && itinRef.current) {
      itinRef.current.scrollTop = savedScroll.current
    }
  }, [focused])

  function regenerate() {
    onSend(i18n.language === 'vi' ? REGENERATE_VI : REGENERATE_EN)
  }

  const activeDay = typeof resolvedTab === 'number' ? days.find((d) => d.day_number === resolvedTab) : null

  // Phase 10 map data. Deliberately NOT keyed on mapSync.hoveredId — hover
  // changes on every mousemove, and re-decoding every day's polylines on
  // each one would be wasteful; only real data (tab/plan/hotel) changes.
  const segments = useMemo(
    () =>
      resolvedTab === 'overview'
        ? buildTripSegments(days, tripPlan?.hotel)
        : activeDay
          ? buildDaySegments(activeDay, tripPlan?.hotel)
          : [],
    [resolvedTab, days, tripPlan?.hotel, activeDay],
  )

  const markers: MapMarkerSpec[] = useMemo(() => {
    const list: MapMarkerSpec[] = []
    if (tripPlan?.hotel?.coordinates) {
      list.push({
        syncId: TRIP_HOTEL_SYNC_KEY,
        coordinates: tripPlan.hotel.coordinates,
        kind: 'hotel',
      })
    }
    const daysToShow = resolvedTab === 'overview' ? days : activeDay ? [activeDay] : []
    for (const day of daysToShow) {
      day.items.forEach((item, index) => {
        list.push({
          syncId: itemSyncId(day.day_number, item, index),
          coordinates: item.coordinates,
          kind: 'item',
          label: index + 1,
          dayNumber: day.day_number,
          openId: item.reference_type === 'Attraction' && item.reference_id ? item.reference_id : undefined,
          endpoint: resolvedTab !== 'overview' && index === 0 ? 'start' : resolvedTab !== 'overview' && index === day.items.length - 1 ? 'end' : undefined,
        })
      })
    }
    if (showSuggested) {
      for (const place of state.suggestedPlaces) {
        list.push({
          syncId: suggestedPlaceSyncId(place),
          coordinates: place.coordinates,
          kind: 'suggested',
          name: place.name,
        })
      }
    }
    return list
  }, [resolvedTab, days, activeDay, tripPlan?.hotel, showSuggested, state.suggestedPlaces])

  function handleMarkerClick(marker: MapMarkerSpec) {
    mapSync.focusOn(marker.syncId)
    if (marker.openId) handleOpenDetail(marker)
  }

  if (!tripPlan) return null

  const dateRange = formatTripDateRange(tripPlan.start_date, tripPlan.end_date, i18n.language)
  const nights = nightsFrom(tripPlan.start_date, tripPlan.end_date, tripPlan.duration_days)
  const daysPart =
    tripPlan.duration_days > 0
      ? `${tripPlan.duration_days} ${t('daysWord')}${nights != null ? ` · ${nights} ${t('nightsWord')}` : ''}`
      : ''
  const peoplePart = tripPlan.number_of_adults != null ? `${tripPlan.number_of_adults} ${t('peopleWord')}` : ''
  const meta = [dateRange, daysPart, peoplePart].filter((x): x is string => Boolean(x)).join(' · ')

  const tabs: { key: TabKey; label: string; flex: number }[] = [
    { key: 'overview', label: t('overview'), flex: 1.6 },
    ...days.map((d) => ({ key: d.day_number, label: `${t('dayWord')} ${d.day_number}`, flex: 1 })),
  ]

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col animate-[vRise_0.75s_cubic-bezier(0.22,1,0.36,1)_both]">
      {/* Trip header — glass panel, ONE button ("Tạo lại"). No share button. */}
      <div className="glass-panel flex-none flex items-center gap-3.5 mx-3.5 mt-3.5 px-[18px] py-[13px] rounded-[26px]">
        <div
          className="w-[30px] h-[30px] rounded-[10px] bg-gradient-to-br from-[#5C93EE] to-[#2C5FC9] flex items-center justify-center text-on-primary font-[590] text-[14px]"
          style={{ boxShadow: '0 6px 16px -5px rgba(44,95,201,.6)' }}
          aria-hidden="true"
        >
          V
        </div>
        <div className="flex flex-col min-w-0">
          <div className="text-[15px] font-[590] tracking-[-0.3px] text-on-surface truncate">
            {tripPlan.destination ?? t('workspaceTitle')}
          </div>
          {meta && <div className="text-[11.5px] text-on-surface-muted font-normal truncate">{meta}</div>}
        </div>
        <div className="flex-1" />
        <button
          type="button"
          onClick={regenerate}
          className="px-4 py-[9px] rounded-[12px] border border-stroke bg-glass-2 text-[13px] font-normal text-on-surface cursor-pointer transition-all duration-200 hover:bg-glass-3 hover:-translate-y-px"
        >
          {t('regenerate')}
        </button>
      </div>

      {/* Content row — itinerary column | map | detail panel (focus). */}
      <div className="flex-1 flex gap-3.5 p-3.5 min-h-0 min-w-0">
        <div
          className="glass-panel flex-none flex flex-col min-h-0 overflow-hidden rounded-[26px]"
          style={{
            flexBasis: focused ? '520px' : '470px',
            maxWidth: '100%',
            transition: 'flex-basis .62s cubic-bezier(.22,1,.36,1)',
          }}
        >
          <div className="flex-none p-3 border-b border-line overflow-x-auto">
            <div className="flex gap-[3px] p-[3px] rounded-[15px]" style={{ background: 'var(--fill)' }}>
              {tabs.map((tab) => {
                const isActive = tab.key === resolvedTab
                return (
                  <button
                    key={String(tab.key)}
                    type="button"
                    onClick={() => pickTab(tab.key)}
                    style={{
                      flex: tab.flex,
                      padding: '8px 10px',
                      borderRadius: '12px',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '12.5px',
                      fontWeight: isActive ? 600 : 400,
                      background: isActive ? 'var(--g3)' : 'transparent',
                      color: isActive ? 'var(--t1)' : 'var(--t2)',
                      boxShadow: isActive ? '0 4px 12px -6px rgba(var(--sh),.55)' : 'none',
                      transition: 'all .32s cubic-bezier(.34,1.4,.64,1)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {tab.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div ref={itinRef} className="flex-1 overflow-y-auto custom-scrollbar p-4 min-h-0">
            {resolvedTab === 'overview' ? (
              <TripOverviewTab tripPlan={tripPlan} onPickDay={(n) => pickTab(n)} />
            ) : activeDay ? (
              <DayTimeline
                day={activeDay}
                focusedId={focusedId}
                onOpen={openFocus}
                hoveredId={mapSync.hoveredId}
                onHoverChange={mapSync.setHoveredId}
              />
            ) : null}
          </div>
        </div>

        {/* Map — collapses to 0 on focus (scale + blur per design, never unmount) */}
        <div
          className="min-w-0 overflow-hidden rounded-[26px]"
          aria-hidden={focused}
          style={{
            flex: focused ? '0 0 0px' : '1 1 auto',
            minWidth: focused ? '0px' : '320px',
            opacity: focused ? 0 : 1,
            transform: focused ? 'scale(.94)' : 'none',
            // Not in `transition` (see below) — animating blur radius forces
            // a full re-rasterize of everything under it (here, the Mapbox
            // WebGL canvas) EVERY frame for the whole .55-.62s the rest of
            // this box is transitioning; instant toggle keeps the same
            // before/after look for a fraction of the cost. Easy to miss
            // that it snapped since it's always paired with the opacity
            // fade already happening.
            filter: focused ? 'blur(16px)' : 'blur(0px)',
            pointerEvents: focused ? 'none' : 'auto',
            transition: 'flex .62s cubic-bezier(.22,1,.36,1), opacity .36s ease, transform .55s cubic-bezier(.22,1,.36,1)',
          }}
        >
          <MapView
            variant="workspace"
            theme={theme}
            markers={markers}
            segments={segments}
            hoveredId={mapSync.hoveredId}
            onHoverChange={mapSync.hoverMarker}
            onMarkerClick={handleMarkerClick}
            selectedId={focusedId}
            colorByDay={resolvedTab === 'overview'}
            showSuggested={showSuggested}
            onToggleSuggested={state.suggestedPlaces.length > 0 ? () => setShowSuggested((v) => !v) : undefined}
          />
        </div>

        {/* Always mounted (never conditionally rendered) so it can animate its
            own open AND close via flex/opacity/scale/blur, per design's det*
            tokens — same fix already applied to stage-hotels.tsx's detail
            column. Content comes from the sticky lastContext (see its own
            comment above), not the live context, so it doesn't go blank the
            instant focus closes. */}
        <div
          className="min-w-0 overflow-hidden rounded-[26px]"
          aria-hidden={!focused}
          style={{
            flex: focused ? '1 1 auto' : '0 0 0px',
            minWidth: focused ? '430px' : '0px',
            opacity: focused ? 1 : 0,
            transform: focused ? 'none' : 'scale(.96)',
            // Instant toggle, not animated — same reasoning as the map
            // column's own filter above.
            filter: focused ? 'blur(0px)' : 'blur(12px)',
            pointerEvents: focused ? 'auto' : 'none',
            transition: 'flex .62s cubic-bezier(.22,1,.36,1), opacity .36s ease, transform .55s cubic-bezier(.22,1,.36,1)',
          }}
        >
          <PlaceDetailPanel
            placeId={lastContext?.item.reference_id ?? null}
            name={lastContext ? placeNameFromActivity(lastContext.item.activity) : ''}
            kind={lastContext?.item.kind}
            dayNumber={lastContext?.day.day_number ?? 1}
            startTime={lastContext?.item.start_time ?? null}
            routeLeg={lastContext?.routeLeg ?? { kind: 'none' }}
            onClose={focusMode.closeFocus}
          />
        </div>
      </div>
    </div>
  )
}
