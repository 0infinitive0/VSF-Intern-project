import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import HotelOptionCards from './hotel-option-card'
import HotelDetailPanel from './hotel-detail-panel'
import MapView, { type MapMarkerSpec } from './map-view'
import { useMapSync } from '../hooks/use-map-sync'
import { hotelOptionSyncId } from '../lib/map-sync-id'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { Theme } from '../hooks/use-theme'
import type { ChatState, HotelOption } from '../types'

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
 * flex columns: card list | map (placeholder until Phase 10) | detail panel.
 *
 * Two-step hotel pick (user decision 06/08/2026): a card's "Chọn" only sets
 * local selectedIndex; the header's "Tạo lịch trình từ khách sạn này" is the
 * ONLY sender, posting String(hotel.index) through onSend — byte-identical
 * to the pre-Phase-8 wire, no new verb, no new endpoint. The bubble shown to
 * the user swaps that raw index for `displayText` (e.g. "Mình chọn Sóng Xanh
 * Boutique") so the thread reads naturally; the backend still only ever sees
 * the index. The button is disabled until something is selected so no empty
 * message can ever be sent. selectedIndex resets when hotel_options rotates
 * (backend clears them on the next turn, as before).
 *
 * Focus mode (chat collapses in app-shell): the list widens 520→470px per the
 * design's hListW, the map column collapses to 0, and the detail panel joins
 * as a third flex sibling. The list NEVER unmounts and switching the focused
 * hotel keeps focus open (use-focus-mode replaces in place). List scroll
 * position is captured on open and restored on close.
 */
export default function StageHotels({
  state,
  focusMode,
  onSend,
  theme,
}: {
  state: ChatState
  focusMode: FocusModeApi
  onSend: (text: string, options?: { displayText?: string }) => void
  theme: Theme
}) {
  const { t } = useTranslation()
  const hotels = state.hotelOptions
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const mapSync = useMapSync()

  useEffect(() => {
    setSelectedIndex(null)
  }, [hotels])

  const focusedId = focusMode.focus?.kind === 'hotel' ? focusMode.focus.id : null
  const focused = focusedId != null
  const focusedHotel = hotels.find((h) => h.id === focusedId)
  const selectedHotel = hotels.find((h) => h.index === selectedIndex) ?? null
  const nights = nightsFrom(state.intake?.start_date, state.intake?.end_date)

  const listRef = useRef<HTMLDivElement>(null)
  const savedScroll = useRef(0)

  function openFocus(hotel: HotelOption) {
    if (!hotel.id) return
    savedScroll.current = listRef.current?.scrollTop ?? 0
    focusMode.openFocus({ kind: 'hotel', id: hotel.id })
  }

  // Phase 10: one marker per hotel option. hotel.id gates openId exactly like
  // the card's own canOpen check — a marker for a hotel without an id
  // scrolls its card into view on click but never opens a focus panel that
  // has nothing to fetch.
  const markers: MapMarkerSpec[] = useMemo(
    () =>
      hotels.map((hotel) => ({
        syncId: hotelOptionSyncId(hotel),
        coordinates: hotel.coordinates,
        kind: 'hotel' as const,
        openId: hotel.id,
      })),
    [hotels],
  )

  function handleMarkerClick(marker: MapMarkerSpec) {
    mapSync.focusOn(marker.syncId)
    if (marker.openId) {
      const hotel = hotels.find((h) => h.id === marker.openId)
      if (hotel) openFocus(hotel)
    }
  }

  useLayoutEffect(() => {
    if (!focused && listRef.current) {
      listRef.current.scrollTop = savedScroll.current
    }
  }, [focused])

  function confirmSelection() {
    if (!selectedHotel) return
    onSend(String(selectedHotel.index), { displayText: t('hotelPickedMessage', { name: selectedHotel.name }) })
  }

  return (
    <div className="flex-1 min-w-0 min-h-0 flex flex-col animate-[vRise_0.7s_cubic-bezier(0.22,1,0.36,1)_both]">
      {/* Header — badge describes the real state in both branches; the confirm
          button switches token with selection and is disabled when empty so no
          vacuous message is ever sent. */}
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
        <div className="flex-1" />
        <div className="text-[11.5px] text-on-surface-muted font-normal max-w-[300px] truncate">
          {selectedHotel ? t('hotelBadgeSelected', { name: selectedHotel.name }) : t('hotelBadgeEmpty')}
        </div>
        <button
          type="button"
          disabled={!selectedHotel}
          onClick={confirmSelection}
          className="px-[18px] py-2.5 rounded-[13px] border-none text-[13px] font-[590] tracking-[-0.12px] transition-all duration-200 text-nowrap"
          style={{
            background: selectedHotel ? 'var(--btn)' : 'var(--fill2)',
            color: selectedHotel ? 'var(--btn-fg)' : 'var(--t4)',
            cursor: selectedHotel ? 'pointer' : 'default',
          }}
        >
          {t('buildFromHotel')}
        </button>
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
          <HotelOptionCards
            hotels={hotels}
            selectedIndex={selectedIndex}
            focusedId={focusedId}
            nights={nights}
            onSelect={(hotel) => setSelectedIndex(hotel.index)}
            onOpen={openFocus}
            hoveredId={mapSync.hoveredId}
            onHoverChange={mapSync.setHoveredId}
          />
        </div>

        <div
          className="min-w-0 overflow-hidden rounded-[26px]"
          aria-hidden={focused}
          style={{
            flex: focused ? '0 0 0px' : '1 1 auto',
            opacity: focused ? 0 : 1,
            pointerEvents: focused ? 'none' : 'auto',
            transition: 'flex .62s cubic-bezier(.22,1,.36,1), opacity .38s ease',
          }}
        >
          <MapView
            theme={theme}
            markers={markers}
            segments={[]}
            hoveredId={mapSync.hoveredId}
            onHoverChange={mapSync.setHoveredId}
            onMarkerClick={handleMarkerClick}
            statusOverlay={
              <div
                className="rounded-[18px] border border-edge bg-glass-2 inline-block"
                style={{ padding: '11px 14px', backdropFilter: 'blur(20px) saturate(1.6)', maxWidth: '280px' }}
              >
                <div className="text-[10px] font-[590] tracking-[0.1em] uppercase text-on-surface-muted">
                  {t('mapHotelCountLabel', { count: hotels.length })}
                </div>
                <div className="text-[11.5px] text-on-surface-variant mt-0.5" style={{ lineHeight: 1.45 }}>
                  {selectedHotel ? t('mapHotelHintSelected', { name: selectedHotel.name }) : t('mapHotelHintEmpty')}
                </div>
              </div>
            }
          />
        </div>

        {focused && (
          <HotelDetailPanel
            hotelId={focusedId}
            option={focusedHotel}
            onClose={focusMode.closeFocus}
          />
        )}
      </div>
    </div>
  )
}
