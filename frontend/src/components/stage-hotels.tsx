import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import HotelFilterBar from './hotel-filter-bar'
import HotelOptionCards from './hotel-option-card'
import HotelDetailPanel from './hotel-detail-panel'
import MapView, { type MapMarkerSpec } from './map-view'
import { useMapSync } from '../hooks/use-map-sync'
import { hotelOptionSyncId } from '../lib/map-sync-id'
import { hotelMapFields, hotelMapRays } from '../lib/map-presentation'
import { useHotelDetail } from '../hooks/use-hotel-detail'
import { activeAmenityPills, filterAndSortHotels, type HotelSortOrder } from '../lib/hotel-filters'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import type { Theme } from '../hooks/use-theme'
import type { ChatState, HotelFilterData, HotelOption } from '../types'

type FocusModeApi = ReturnType<typeof useFocusMode>

/**
 * Nights from the real intake dates — never a constant (phase-08 §"Giá tổng").
 * Returns null when either date is missing/invalid or the diff isn't positive,
 * in which case cards show the nightly rate only (no invented total).
 */
function nightsFrom(startIso?: string | null, endIso?: string | null): number | null {
  if (!startIso || !endIso) return null
  const start = new Date(startIso).getTime()
  const end = new Date(endIso).getTime()
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null
  const nights = Math.round((end - start) / 86_400_000)
  return nights > 0 ? nights : null
}

/**
 * StageHotels — the split-view "hotels" stage (V-OTA Planner.dc.html:377+):
 * glass header (V logo, step title, status badge, confirm button) over three
 * flex columns: card list (with the filter bar) | map | detail panel.
 *
 * Two-step hotel pick, now gated by a room hold (V-OTA Planner design
 * update — room selection moved BEFORE itinerary creation): a card's "Chọn"
 * only sets local selectedIndex; the header button no longer calls
 * onConfirmHotel directly — it opens the selected hotel's detail panel so
 * the user can pick room(s) and press "Giữ phòng" there. onConfirmHotel
 * itself (still byte-identical to the pre-design-update wire: posts
 * String(hotel.index) through onSend, no new verb, no new endpoint) is now
 * invoked by HotelDetailPanel's hold footer, as the ONHELD callback passed
 * to roomHold.startHold — see use-room-hold.ts's module doc comment.
 * selectedIndex resets when hotel_options rotates (backend clears them on
 * the next turn, as before). selectedIndex itself is owned by App.tsx
 * (per-session, so switching conversations never leaks a pick into the
 * wrong one) — this component only reads/reports it.
 *
 * Focus mode (chat collapses in app-shell): the list widens 520→470px per the
 * design's hListW, the map column collapses to 0, and the detail panel joins
 * as a third flex sibling. The list NEVER unmounts and switching the focused
 * hotel keeps focus open (use-focus-mode replaces in place). List scroll
 * position is captured on open and restored on close.
 *
 * `hotelFilterData` (the amenity catalog + preference lists) is a separate
 * prop, not read off `state` directly, for the same reason `hotelOptions`
 * already is one (bug fix): App.tsx retains both together per session, so a
 * later turn that doesn't re-run the hotel search (selecting a hotel,
 * building the itinerary, a qa_node answer) doesn't leave these still-shown
 * cards resolving their amenity tags against an empty catalog and falling
 * back to raw canonical ids like "swimming_pool".
 */
export default function StageHotels({
  state,
  hotelOptions,
  hotelFilterData,
  selectedIndex,
  onSelectHotel,
  onConfirmHotel,
  focusMode,
  theme,
  roomHold,
}: {
  state: ChatState
  hotelOptions: HotelOption[]
  hotelFilterData: HotelFilterData
  selectedIndex: number | null
  onSelectHotel: (index: number) => void
  onConfirmHotel: (hotel: HotelOption) => void
  focusMode: FocusModeApi
  theme: Theme
  /** Owns the room cart + real hold — threaded into HotelDetailPanel below. */
  roomHold: RoomHoldApi
}) {
  const { t, i18n } = useTranslation()
  const hotels = hotelOptions
  const amenityCatalog = hotelFilterData.hotelAmenities
  const [minPrice, setMinPrice] = useState<number | null>(null)
  const [maxPrice, setMaxPrice] = useState<number | null>(null)
  const [minStars, setMinStars] = useState<number | null>(null)
  const [preferenceIds, setPreferenceIds] = useState<string[]>([])
  const [sortOrder, setSortOrder] = useState<HotelSortOrder>('match')
  const filteredHotels = useMemo(
    () => filterAndSortHotels(hotels, { minPrice, maxPrice, minStars, preferenceIds, sortOrder }),
    [hotels, maxPrice, minPrice, minStars, preferenceIds, sortOrder],
  )
  const mapSync = useMapSync()

  const focusedId = focusMode.focus?.kind === 'hotel' ? focusMode.focus.id : null
  const focused = focusedId != null
  // The detail panel is always mounted now (never conditionally rendered) so
  // it can animate its own close, not just its open — see design's hDet*
  // tokens. That means its CONTENT must outlive `focusedId` going back to
  // null the instant focus closes, or the close transition would fade out an
  // already-blank panel. `lastFocusedId` is the sticky "last hotel actually
  // viewed" value fed to HotelDetailPanel; `focusedId` itself still drives
  // every visual open/closed state (including the card's own highlight ring)
  // so nothing else lags behind the real focus state.
  const [lastFocusedId, setLastFocusedId] = useState<string | null>(null)
  useEffect(() => {
    if (focusedId != null) {
      setLastFocusedId(focusedId)
    } else if (lastFocusedId != null && !hotels.some((h) => h.id === lastFocusedId)) {
      setLastFocusedId(null)
    }
  }, [focusedId, hotels, lastFocusedId])
  const selectedHotel = useMemo(() => {
    if (selectedIndex != null) {
      const found = hotels.find((h) => h.index === selectedIndex)
      if (found) return found
    }
    if (state.tripPlan?.hotel) {
      const planHotel = state.tripPlan.hotel
      const found = hotels.find(
        (h) =>
          (planHotel.id && h.id === planHotel.id) ||
          (planHotel.name && h.name && h.name.toLowerCase().trim() === planHotel.name.toLowerCase().trim()),
      )
      if (found) return found
    }
    if (roomHold.heldHotelId) {
      const found = hotels.find((h) => h.id === roomHold.heldHotelId)
      if (found) return found
    }
    return null
  }, [hotels, selectedIndex, state.tripPlan?.hotel, roomHold.heldHotelId])
  const resolvedSelectedIndex = selectedHotel?.index ?? selectedIndex
  const nights = nightsFrom(state.intake?.start_date, state.intake?.end_date)
  const selectedId = selectedHotel ? hotelOptionSyncId(selectedHotel) : null
  const { detail: selectedHotelDetail } = useHotelDetail(selectedHotel?.id ?? null)
  const selectedHotelRays = useMemo(() => hotelMapRays(selectedHotelDetail), [selectedHotelDetail])

  useEffect(() => {
    setPreferenceIds(hotelFilterData.activePreferences.map(({ id }) => id))
  }, [hotels, hotelFilterData.activePreferences])

  const filterPreferences = useMemo(
    () => activeAmenityPills(hotelFilterData.allPreferences, amenityCatalog, i18n.language),
    [amenityCatalog, i18n.language, hotelFilterData.allPreferences],
  )

  const listRef = useRef<HTMLDivElement>(null)
  const savedScroll = useRef(0)

  function openFocus(hotel: HotelOption) {
    if (!hotel.id) return
    savedScroll.current = listRef.current?.scrollTop ?? 0
    focusMode.openFocus({ kind: 'hotel', id: hotel.id })
  }

  // Phase 10: one marker per hotel option (post-filter, so a filtered-out
  // hotel's marker disappears with its card). hotel.id gates openId exactly
  // like the card's own canOpen check — a marker for a hotel without an id
  // scrolls its card into view on click but never opens a focus panel that
  // has nothing to fetch.
  const markers: MapMarkerSpec[] = useMemo(
    () =>
      filteredHotels.map((hotel) => ({
        syncId: hotelOptionSyncId(hotel),
        coordinates: hotel.coordinates,
        kind: 'hotel' as const,
        openId: hotel.id,
        ...hotelMapFields(hotel, i18n.language),
      })),
    [filteredHotels, i18n.language],
  )

  // Marker click mirrors the card's "Chọn" zone (user decision — an earlier
  // pass had this open the detail panel instead, mirroring "Xem chi tiết",
  // but the request coming back from actually using it is a plain pick:
  // same as pressing "Chọn khách sạn này" on the card). focusOn scrolls the
  // list to the corresponding card ("Click Marker → Scroll tới Card").
  function handleMarkerClick(marker: MapMarkerSpec) {
    const hotel = hotels.find((candidate) => hotelOptionSyncId(candidate) === marker.syncId)
    if (!hotel) return
    onSelectHotel(hotel.index)
    mapSync.focusOn(marker.syncId)
  }

  // Auto-scroll smoothly to the selected hotel card on mount or when selection/filters change
  const autoScrolledId = useRef<string | null>(null)
  useEffect(() => {
    if (focused) return
    const container = listRef.current
    if (!container) return

    const targetId = selectedId
    let timerId: ReturnType<typeof setTimeout> | null = null

    const rafId = requestAnimationFrame(() => {
      timerId = setTimeout(() => {
        const el =
          (targetId ? container.querySelector<HTMLElement>(`[data-card="${CSS.escape(targetId)}"]`) : null) ??
          container.querySelector<HTMLElement>('[data-selected="true"]')

        if (!el || !listRef.current) return
        autoScrolledId.current = targetId

        const elTop = el.offsetTop
        const elHeight = el.offsetHeight
        const containerHeight = listRef.current.clientHeight
        const targetScroll = Math.max(0, elTop - containerHeight / 2 + elHeight / 2)

        listRef.current.scrollTo({
          top: targetScroll,
          behavior: 'smooth',
        })
        el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      }, 150)
    })

    return () => {
      cancelAnimationFrame(rafId)
      if (timerId != null) clearTimeout(timerId)
    }
  }, [selectedId, resolvedSelectedIndex, filteredHotels, focused])

  const prevFocused = useRef(focused)
  useLayoutEffect(() => {
    if (prevFocused.current && !focused && listRef.current) {
      listRef.current.scrollTop = savedScroll.current
    }
    prevFocused.current = focused
  }, [focused])

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col animate-[vRise_0.7s_cubic-bezier(0.22,1,0.36,1)_both]">
      {/* Header */}
      <div className="glass-panel flex-none flex items-center gap-3.5 mx-3.5 mt-3.5 px-[18px] py-[13px] rounded-[26px]">
        <div
          className="w-[30px] h-[30px] rounded-[10px] bg-gradient-to-br from-[#5C93EE] to-[#2C5FC9] flex items-center justify-center text-on-primary font-[590] text-[14px]"
          style={{ boxShadow: '0 6px 16px -5px rgba(44,95,201,.6)' }}
          aria-hidden="true"
        >
          V
        </div>
        <div className="flex flex-col min-w-0">
          <div className="text-[15px] font-[590] tracking-[-0.3px] text-on-surface">
            {t('step2Full')}
          </div>
          <div className="text-[11.5px] text-on-surface-muted font-normal">{t('hotelHeadSub')}</div>
        </div>
      </div>

      {/* Three flex siblings: list | map | detail. The list never unmounts and
          the map never unmounts — both are resized, keeping focus open/close
          free of data refetches (phase-08 §Hotel Detail Focus Mode). */}
      <div className="flex-1 flex gap-3.5 p-3.5 min-h-0 min-w-0">
        <div
          ref={listRef}
          className="overflow-y-auto custom-scrollbar flex flex-col gap-3 pr-0.5 min-w-0 flex-none"
          style={{
            flexBasis: focused ? '470px' : '520px',
            maxWidth: '100%',
            transition: 'flex-basis .62s cubic-bezier(.22,1,.36,1)',
          }}
        >
          <HotelFilterBar
            hotels={hotels}
            apiPriceMin={hotelFilterData.minPrice}
            apiPriceMax={hotelFilterData.maxPrice}
            amenityOptions={filterPreferences}
            minPrice={minPrice}
            maxPrice={maxPrice}
            minStars={minStars}
            preferenceIds={preferenceIds}
            sortOrder={sortOrder}
            onMinPriceChange={setMinPrice}
            onMaxPriceChange={setMaxPrice}
            onMinStarsChange={setMinStars}
            onPreferenceIdsChange={setPreferenceIds}
            onSortOrderChange={setSortOrder}
            onClear={() => {
              setMinPrice(null)
              setMaxPrice(null)
              setMinStars(null)
              setPreferenceIds([])
              setSortOrder('match')
            }}
          />
          <HotelOptionCards
            hotels={filteredHotels}
            selectedIndex={resolvedSelectedIndex}
            focusedId={focusedId}
            nights={nights}
            hotelAmenities={amenityCatalog}
            onSelect={(hotel) => onSelectHotel(hotel.index)}
            onOpen={openFocus}
            hoveredId={mapSync.hoveredId}
            onHoverChange={mapSync.setHoveredId}
          />
          {filteredHotels.length === 0 && (
            <p className="px-3 text-center text-[12px] text-on-surface-muted" role="status">
              {t('hotelFiltersNoResults')}
            </p>
          )}
        </div>

        <div
          className="min-w-0 overflow-hidden rounded-[26px]"
          aria-hidden={focused}
          style={{
            flex: focused ? '0 0 0px' : '1 1 auto',
            minWidth: focused ? '0px' : '340px',
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
            variant="hotels"
            theme={theme}
            markers={markers}
            segments={[]}
            hoveredId={mapSync.hoveredId}
            onHoverChange={mapSync.hoverMarker}
            onMarkerClick={handleMarkerClick}
            selectedId={selectedId}
            hotelRays={selectedHotelRays}
          />
        </div>

        {/* Always mounted (never conditionally rendered) so it can animate its
            own open AND close via flex/opacity/scale/blur, per design's hDet*
            tokens — see the lastFocusedId comment above for why its content
            uses the sticky id, not the live focusedId. */}
        <div
          className="min-w-0 overflow-hidden rounded-[26px]"
          aria-hidden={!focused}
          style={{
            flex: focused ? '1 1 auto' : '0 0 0px',
            minWidth: focused ? '440px' : '0px',
            opacity: focused ? 1 : 0,
            transform: focused ? 'none' : 'scale(.96)',
            // Instant toggle, not animated — same reasoning as the map
            // column's own filter above.
            filter: focused ? 'blur(0px)' : 'blur(12px)',
            pointerEvents: focused ? 'auto' : 'none',
            transition: 'flex .62s cubic-bezier(.22,1,.36,1), opacity .36s ease, transform .55s cubic-bezier(.22,1,.36,1)',
          }}
        >
          <HotelDetailPanel
            hotelId={lastFocusedId}
            option={hotels.find((h) => h.id === lastFocusedId)}
            hotelAmenities={amenityCatalog}
            selectedAmenityIds={preferenceIds}
            onClose={focusMode.closeFocus}
            roomHold={roomHold}
            checkInDate={state.intake?.start_date ?? null}
            checkOutDate={state.intake?.end_date ?? null}
            onConfirmHotel={onConfirmHotel}
            onSelectHotel={onSelectHotel}
            heldElsewhereHotelName={hotels.find((h) => h.id === roomHold.heldHotelId)?.name ?? null}
          />
        </div>
      </div>
    </div>
  )
}
