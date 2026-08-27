import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getHotel,
  listAccommodationTypes,
  listAmenities,
  listDestinations,
  reembedHotels,
  setHotelActive,
  updateHotel,
  type AmenityOption,
  type DestinationOption,
  type HotelDetailResponse,
  type UpdateHotelRequest,
} from '../../api/hotels-client'
import { listPipelines, type PipelineItem } from '../../api/pipelines-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Spinner } from '../../ui/spinner'
import { Switch } from '../../ui/switch'
import { Tabs, type TabItem } from '../../ui/tabs'
import { HotelEmbeddingDot } from './hotel-embedding-dot'
import { HotelSourceChip } from './hotel-source-chip'
import { HotelTabAmenities } from './hotel-tab-amenities'
import { HotelTabBasic } from './hotel-tab-basic'
import { HotelTabImages } from './hotel-tab-images'
import { HotelTabLocation } from './hotel-tab-location'
import { HotelTabNearby } from './hotel-tab-nearby'
import { HotelTabRooms } from './rooms/hotel-tab-rooms'
import type { HotelBasicFieldsValue } from './hotel-basic-fields'
import type { HotelLocationFieldsValue } from './hotel-location-fields'
import { PipelineRunProgress } from '../pipelines/pipeline-run-progress'
import { UnsavedBar } from './unsaved-bar'

const EMBEDDING_POLL_MS = 1000
// ~2 minutes -- if Airflow hasn't moved the run past `queued`/`running` by
// then, stop polling instead of leaving the banner looking permanently
// stuck; the Pipelines page still has the real live status.
const MAX_EMBEDDING_POLL_ATTEMPTS = 120

interface HotelDetailPageProps {
  hotelId: string
  navigate: (to: string) => void
}

type LoadState = { status: 'loading' } | { status: 'error'; detail: string } | { status: 'ok' }

function basicFromHotel(hotel: HotelDetailResponse): HotelBasicFieldsValue {
  return {
    name: hotel.name,
    accommodationType: hotel.accommodation_type ?? '',
    starRating: hotel.star_rating ?? null,
    description: hotel.description ?? '',
    locationHighlight: hotel.location_highlight ?? '',
  }
}

function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const bSet = new Set(b)
  return a.every((value) => bSet.has(value))
}

function locationFromHotel(hotel: HotelDetailResponse): HotelLocationFieldsValue {
  return {
    address: hotel.address ?? '',
    city: hotel.city ?? '',
    latitude: hotel.latitude ?? null,
    longitude: hotel.longitude ?? null,
  }
}

const TABS: TabItem[] = [
  { key: 'basic', label: 'Cơ bản' },
  { key: 'location', label: 'Vị trí' },
  { key: 'amenities', label: 'Tiện ích' },
  { key: 'images', label: 'Hình ảnh' },
  { key: 'rooms', label: 'Phòng' },
  { key: 'nearby', label: 'Lân cận' },
]

/** hotel-detail-page.tsx -- B3 orchestrator (phase-09-hotel-edit.md). Holds
 * every tab's edit state in one flat object (not per-tab local state) so
 * "which exact fields changed" can be computed by diffing against the
 * originally-loaded value -- the unsaved bar needs field NAMES, not a dirty
 * flag (see the plan's explicit note against per-input dirty flags).
 * Switching tabs never loses state because there is no per-tab state to
 * lose; only leaving the PAGE while dirty is guarded (beforeunload) --
 * same scope line Phase 8 drew: a sidebar-click guard needs a router-level
 * change out of this phase. */
export function HotelDetailPage({ hotelId, navigate }: HotelDetailPageProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' })
  const [hotel, setHotel] = useState<HotelDetailResponse | null>(null)
  const [activeTab, setActiveTab] = useState('basic')

  const [basic, setBasic] = useState<HotelBasicFieldsValue | null>(null)
  const [location, setLocation] = useState<HotelLocationFieldsValue | null>(null)
  const [checkInTime, setCheckInTime] = useState('')
  const [checkOutTime, setCheckOutTime] = useState('')
  const [amenityIds, setAmenityIds] = useState<string[]>([])
  const [images, setImages] = useState<string[]>([])

  const [original, setOriginal] = useState<{
    basic: HotelBasicFieldsValue
    location: HotelLocationFieldsValue
    checkInTime: string
    checkOutTime: string
    amenityIds: string[]
    images: string[]
  } | null>(null)

  const [destinations, setDestinations] = useState<DestinationOption[]>([])
  const [accommodationTypes, setAccommodationTypes] = useState<string[]>([])
  const [amenityCatalog, setAmenityCatalog] = useState<AmenityOption[]>([])
  const [lookupError, setLookupError] = useState<string | null>(null)

  const [activeBusy, setActiveBusy] = useState(false)
  const [activeError, setActiveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [reembedState, setReembedState] = useState<'idle' | 'loading' | 'queued' | 'unavailable' | 'stalled' | 'success' | 'failed'>(
    'idle',
  )
  const [embeddingRun, setEmbeddingRun] = useState<PipelineItem | null>(null)
  const embeddingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const embeddingPollAttemptsRef = useRef(0)
  // The DAG's own `max_active_runs=1` queues this trigger's run behind
  // whatever's already active (a scheduled sweep, or another admin's
  // reembed) instead of erroring -- see embedding.py's module docstring.
  // Polling must therefore track THIS specific dag_run_id, not just
  // whatever the DAG's `last_run` happens to be: otherwise an unrelated
  // run finishing first reads as "Đã embed thành công" for this hotel while
  // its own (still-queued) run hasn't executed yet.
  const embeddingDagRunIdRef = useRef<string | null>(null)

  useEffect(() => {
    return () => {
      if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoadState({ status: 'loading' })
    getHotel(hotelId).then((result) => {
      if (cancelled) return
      if (!result.ok) return setLoadState({ status: 'error', detail: result.detail })
      const data = result.data
      const loadedBasic = basicFromHotel(data)
      const loadedLocation = locationFromHotel(data)
      setHotel(data)
      setBasic(loadedBasic)
      setLocation(loadedLocation)
      setCheckInTime(data.check_in_time ?? '')
      setCheckOutTime(data.check_out_time ?? '')
      setAmenityIds(data.amenities)
      setImages(data.images)
      setOriginal({
        basic: loadedBasic,
        location: loadedLocation,
        checkInTime: data.check_in_time ?? '',
        checkOutTime: data.check_out_time ?? '',
        amenityIds: data.amenities,
        images: data.images,
      })
      setLoadState({ status: 'ok' })
    })
    return () => {
      cancelled = true
    }
  }, [hotelId])

  useEffect(() => {
    listDestinations().then((result) => {
      if (result.ok) setDestinations(result.data)
      else setLookupError((prev) => prev ?? `Không tải được danh sách tỉnh/thành: ${result.detail}`)
    })
    listAccommodationTypes().then((result) => {
      if (result.ok) setAccommodationTypes(result.data)
      else setLookupError((prev) => prev ?? `Không tải được gợi ý loại hình: ${result.detail}`)
    })
    listAmenities().then((result) => {
      if (result.ok) setAmenityCatalog(result.data)
      else setLookupError((prev) => prev ?? `Không tải được danh mục tiện ích: ${result.detail}`)
    })
  }, [])

  const changedFields = useMemo(() => {
    if (!basic || !location || !original) return []
    const changed: string[] = []
    if (basic.name !== original.basic.name) changed.push('name')
    if (basic.accommodationType !== original.basic.accommodationType) changed.push('accommodation_type')
    if (basic.starRating !== original.basic.starRating) changed.push('star_rating')
    if (basic.description !== original.basic.description) changed.push('description')
    if (basic.locationHighlight !== original.basic.locationHighlight) changed.push('location_highlight')
    if (location.address !== original.location.address) changed.push('address')
    if (location.city !== original.location.city) changed.push('city')
    if (location.latitude !== original.location.latitude || location.longitude !== original.location.longitude) {
      changed.push('coordinates')
    }
    if (checkInTime !== original.checkInTime) changed.push('check_in_time')
    if (checkOutTime !== original.checkOutTime) changed.push('check_out_time')
    // Set comparison, not list -- hotel-tab-amenities.tsx only ever
    // adds/removes one id per toggle, but a toggle-on-then-off round trip
    // must not read as "changed" (it would clear `embedding` server-side
    // for a same-set reorder, the "quá tay" cost the plan's risk table
    // flags). `images` stays list/order-sensitive: gallery order is real.
    if (!sameStringSet(amenityIds, original.amenityIds)) changed.push('amenities')
    if (JSON.stringify(images) !== JSON.stringify(original.images)) changed.push('images')
    return changed
  }, [basic, location, checkInTime, checkOutTime, amenityIds, images, original])

  const ragFieldsChanged = useMemo(
    () => (hotel ? changedFields.filter((field) => hotel.rag_fields.includes(field)) : []),
    [changedFields, hotel],
  )

  const isDirty = changedFields.length > 0

  useEffect(() => {
    if (!isDirty) return
    function handler(e: BeforeUnloadEvent) {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  function handleDiscard() {
    if (!original) return
    setBasic(original.basic)
    setLocation(original.location)
    setCheckInTime(original.checkInTime)
    setCheckOutTime(original.checkOutTime)
    setAmenityIds(original.amenityIds)
    setImages(original.images)
    setSaveError(null)
  }

  async function handleSave() {
    if (!basic || !location || !original || !hotel) return
    if (changedFields.includes('name') && basic.name.trim() === '') {
      setSaveError('Tên khách sạn là bắt buộc.')
      return
    }
    setSaving(true)
    setSaveError(null)

    const body: UpdateHotelRequest = {}
    if (changedFields.includes('name')) body.name = basic.name.trim()
    if (changedFields.includes('accommodation_type')) body.accommodation_type = basic.accommodationType.trim() || null
    if (changedFields.includes('star_rating')) body.star_rating = basic.starRating
    if (changedFields.includes('description')) body.description = basic.description.trim() || null
    if (changedFields.includes('location_highlight')) body.location_highlight = basic.locationHighlight.trim() || null
    if (changedFields.includes('address')) body.address = location.address.trim() || null
    if (changedFields.includes('city')) {
      const trimmedCity = location.city.trim()
      const matched = destinations.find((d) => d.name.toLowerCase() === trimmedCity.toLowerCase())
      body.city = trimmedCity || null
      // Only sent when matched -- `destinations` is a small, separately-
      // loaded list, and city text that doesn't (yet) match one is not
      // evidence the hotel's existing destination link is wrong. Nulling
      // it here would silently drop the hotel out of every
      // destination-scoped search (match_hotels_with_rooms filters on
      // destination_id, not city) on what may be a purely cosmetic edit.
      if (matched) body.destination_id = matched.id
    }
    if (changedFields.includes('coordinates')) {
      body.latitude = location.latitude
      body.longitude = location.longitude
    }
    if (changedFields.includes('check_in_time')) body.check_in_time = checkInTime
    if (changedFields.includes('check_out_time')) body.check_out_time = checkOutTime
    if (changedFields.includes('amenities')) body.amenities = amenityIds
    if (changedFields.includes('images')) body.images = images

    const result = await updateHotel(hotelId, body)
    setSaving(false)
    if (!result.ok) {
      setSaveError(result.detail)
      return
    }

    setOriginal({ basic, location, checkInTime, checkOutTime, amenityIds, images })
    // Re-fetched rather than patched from local state: `hotel` never held
    // the edited name/description/etc (only `basic`/`location`/... did), so
    // writing just `embedding_state` into the stale `hotel` closure left
    // the header showing the pre-save name. `is_active` is preserved from
    // whatever's currently displayed so a toggle that lands while this PATCH
    // was in flight doesn't get reverted by the refresh.
    const refreshed = await getHotel(hotelId)
    if (refreshed.ok) {
      setHotel((current) => (current ? { ...refreshed.data, is_active: current.is_active } : refreshed.data))
    } else {
      setHotel((current) => (current ? { ...current, embedding_state: result.data.embedding_state } : current))
    }
    // No confirm dialog here: `update_hotel` already marked `embedding_stale`
    // when a RAG field changed, so the header's HotelEmbeddingDot already
    // reflects the "Cần chạy lại" state on its own. The persistent
    // "Chạy embedding" button below reads that same state instead of
    // interrupting every save with a popup.
  }

  async function handleReembedNow() {
    setReembedState('loading')
    // includeRooms=true: this button appears whenever embedding_state is
    // anything but 'embedded', and both 'partial' and 'stale' can be driven
    // by the rooms alone while the hotel row itself is fine -- a hotel-only
    // reembed would re-embed a row that's already current and never touch
    // the rooms, leaving the badge stuck forever. Unlike the
    // bulk reembed action (reembed-confirm-dialog.tsx), this is already
    // scoped to exactly one hotel by being on its own detail page, so it
    // doesn't need the same confirm-before-including-rooms gate.
    const result = await reembedHotels([hotelId], true)
    const queued = result.ok && result.data.queued
    setReembedState(queued ? 'queued' : 'unavailable')
    if (queued) {
      embeddingDagRunIdRef.current = result.ok ? result.data.dag_run_id ?? null : null
      if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
      embeddingPollAttemptsRef.current = 0
      pollEmbeddingProgress()
    }
  }

  // Polls the shared Pipelines list (same idiom as pipelines-page.tsx) so
  // "Chạy embedding" shows real %-done instead of leaving the admin staring
  // at a static "đã gửi yêu cầu" with no idea when it'll actually finish.
  // Stops once the DAG's `last_run` is no longer `running` and refreshes the
  // hotel so the embedding badge picks up the outcome on its own.
  // Dismisses any reembed banner (queued/stalled/success/failed/unavailable).
  // Also stops an in-flight poll -- the pipeline itself keeps running on the
  // backend regardless, this only stops the UI from tracking it further.
  function handleDismissReembed() {
    if (embeddingPollRef.current) clearTimeout(embeddingPollRef.current)
    embeddingDagRunIdRef.current = null
    setReembedState('idle')
    setEmbeddingRun(null)
  }

  function pollEmbeddingProgress() {
    listPipelines().then((result) => {
      const embedding = result.ok ? (result.data.items.find((item: PipelineItem) => item.has_params) ?? null) : null
      const expectedRunId = embeddingDagRunIdRef.current
      // `last_run` is the DAG's overall newest run, which is someone else's
      // run for as long as this trigger's run sits queued behind it -- only
      // read a state off it once it's actually reporting THIS run.
      if (expectedRunId && embedding?.last_run?.run_id !== expectedRunId) {
        setEmbeddingRun(null)
        embeddingPollAttemptsRef.current += 1
        if (embeddingPollAttemptsRef.current >= MAX_EMBEDDING_POLL_ATTEMPTS) {
          setReembedState('stalled')
          return
        }
        embeddingPollRef.current = setTimeout(pollEmbeddingProgress, EMBEDDING_POLL_MS)
        return
      }
      setEmbeddingRun(embedding)
      const state = embedding?.last_run?.state
      if (state === 'running' || state === 'queued') {
        embeddingPollAttemptsRef.current += 1
        if (embeddingPollAttemptsRef.current >= MAX_EMBEDDING_POLL_ATTEMPTS) {
          // Airflow itself hasn't moved this run past queued/running in
          // ~2 minutes -- stop here instead of polling forever; the
          // Pipelines page still has the real live status.
          setReembedState('stalled')
          return
        }
        embeddingPollRef.current = setTimeout(pollEmbeddingProgress, EMBEDDING_POLL_MS)
        return
      }
      // Run finished -- stop, show the real outcome instead of leaving the
      // "queued" banner up, and refresh the hotel so HotelEmbeddingDot picks
      // up the result too.
      setReembedState(state === 'success' ? 'success' : state === 'failed' ? 'failed' : 'idle')
      setEmbeddingRun(null)
      getHotel(hotelId).then((refreshed) => {
        if (refreshed.ok) setHotel((current) => (current ? { ...refreshed.data, is_active: current.is_active } : refreshed.data))
      })
    })
  }

  async function handleToggleActive(next: boolean) {
    if (!hotel) return
    setActiveError(null)
    setActiveBusy(true)
    const previous = hotel.is_active
    setHotel({ ...hotel, is_active: next })
    const result = await setHotelActive(hotelId, next)
    setActiveBusy(false)
    if (!result.ok) {
      setHotel((current) => (current ? { ...current, is_active: previous } : current))
      setActiveError(result.detail)
    }
  }

  if (loadState.status === 'loading') {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size={22} />
      </div>
    )
  }

  if (loadState.status === 'error' || !hotel || !basic || !location) {
    return (
      <div style={{ flex: 1, padding: 28 }}>
        <Banner tone="err">{loadState.status === 'error' ? loadState.detail : 'Không tải được khách sạn.'}</Banner>
      </div>
    )
  }

  const activeTabId = TABS.find((t) => t.key === activeTab) ? activeTab : 'basic'

  return (
    <>
      {/* Two-row sticky header (breadcrumb+title+source/embed chips on the
          left, "Đang bán" switch on the right; tabs directly below, no gap)
          matches B3's artboard -- the generic PageHeader used elsewhere
          renders a single fixed-height row with `action` pinned to the far
          right, which would strand the source/embed chips away from the
          title and leave the tabs visually detached from the header bar. */}
      <div
        style={{
          flex: 'none',
          padding: '14px 28px 0',
          background: 'var(--g1)',
          backdropFilter: 'blur(18px)',
          borderBottom: '1px solid var(--stroke)',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>Quản trị · Khách sạn · {hotel.name}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '-.01em' }}>{hotel.name}</div>
              <HotelSourceChip isManual={hotel.is_manual} />
              <HotelEmbeddingDot
                embeddingState={hotel.embedding_state}
                roomCount={hotel.room_count}
                roomsMissingEmbedding={hotel.rooms_missing_embedding}
                roomsStaleEmbedding={hotel.rooms_stale_embedding}
              />
              {hotel.embedding_state !== 'embedded' && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleReembedNow}
                  disabled={reembedState === 'loading' || reembedState === 'queued'}
                >
                  {reembedState === 'loading' ? 'Đang chạy…' : reembedState === 'queued' ? 'Đã gửi yêu cầu' : 'Chạy embedding'}
                </Button>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12.5, color: 'var(--t3)' }}>Đang bán</span>
            <Switch checked={hotel.is_active} onChange={handleToggleActive} label="Đang bán" disabled={activeBusy} />
          </div>
        </div>

        <Tabs
          items={TABS.map((tab) => (tab.key === 'rooms' ? { ...tab, label: `Phòng (${hotel.room_count})` } : tab))}
          activeKey={activeTabId}
          onChange={setActiveTab}
        />
      </div>

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 22, display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: activeTabId === 'rooms' ? '100%' : 820, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {!hotel.is_manual && (
              <Banner tone="warn">
                Khách sạn này do pipeline ETL quản lý. Các ô có biểu tượng khoá sẽ bị ghi đè vào lần chạy kế tiếp.
              </Banner>
            )}
            {lookupError && <Banner tone="err">{lookupError}</Banner>}
            {activeError && <Banner tone="err">{activeError}</Banner>}
            {saveError && <Banner tone="err">{saveError}</Banner>}
            {reembedState === 'unavailable' && (
              <Banner tone="warn">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
                  <span style={{ flex: 1 }}>Đã đánh dấu cần embed lại. Chạy pipeline embedding ở trang Tổng quan để bot học ngay.</span>
                  <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                    ✕
                  </Button>
                </div>
              </Banner>
            )}
            {reembedState === 'stalled' && (
              <Banner tone="warn">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
                  <span style={{ flex: 1, minWidth: 200 }}>
                    Pipeline embedding đang chờ lâu hơn bình thường (Airflow chưa bắt đầu chạy). Đã đánh dấu cần embed lại, bot sẽ học khi pipeline chạy.
                  </span>
                  <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                    ✕
                  </Button>
                </div>
              </Banner>
            )}
            {reembedState === 'queued' && (
              <Banner tone="ok">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
                    <span style={{ flex: 1 }}>Đã gửi yêu cầu chạy lại embedding.</span>
                    <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                      ✕
                    </Button>
                  </div>
                  {embeddingRun?.last_run?.state === 'running' ? (
                    <PipelineRunProgress lastRun={embeddingRun.last_run} />
                  ) : (
                    <span style={{ fontSize: 11.5 }}>Đang chờ pipeline bắt đầu…</span>
                  )}
                </div>
              </Banner>
            )}
            {reembedState === 'success' && (
              <Banner tone="ok">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, paddingRight: 4, width: '100%' }}>
                  <span style={{ flex: 1 }}>Đã embed thành công — chatbot đã học nội dung mới của khách sạn này.</span>
                  <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                    ✕
                  </Button>
                </div>
              </Banner>
            )}
            {reembedState === 'failed' && (
              <Banner tone="err">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', paddingRight: 4, width: '100%' }}>
                  <span style={{ flex: 1, minWidth: 200 }}>Chạy embedding thất bại. Thử chạy lại pipeline ở trang Tổng quan.</span>
                  <Button variant="ghost" size="sm" onClick={handleDismissReembed} aria-label="Đóng">
                    ✕
                  </Button>
                </div>
              </Banner>
            )}

            {/* Rooms is a data table (8 columns), not a single-column form
                like every other tab -- the shared 820px column cap would
                force it into a narrow horizontal scroll for no reason. */}
            <div className="card" style={{ padding: 20 }}>
              {activeTabId === 'basic' && (
                <HotelTabBasic
                  value={basic}
                  onChange={setBasic}
                  accommodationTypeOptions={accommodationTypes}
                  changedFields={changedFields}
                />
              )}
              {activeTabId === 'location' && (
                <HotelTabLocation
                  value={location}
                  onChange={setLocation}
                  destinations={destinations}
                  changedFields={changedFields}
                />
              )}
              {activeTabId === 'amenities' && (
                <HotelTabAmenities
                  catalog={amenityCatalog}
                  selected={amenityIds}
                  onChange={setAmenityIds}
                  changed={changedFields.includes('amenities')}
                />
              )}
              {activeTabId === 'images' && <HotelTabImages hotelId={hotelId} images={images} onChange={setImages} />}
              {activeTabId === 'rooms' && (
                <HotelTabRooms
                  hotelId={hotelId}
                  hotelName={hotel.name}
                  navigate={navigate}
                  onRoomsChanged={() => {
                    // `room_count`/`embedding_state` in the header + tab badge
                    // are aggregates over `rooms` -- a room write makes them
                    // stale without this, same posture as handleSave's
                    // post-PATCH refetch below.
                    getHotel(hotelId).then((result) => {
                      if (result.ok) setHotel((current) => (current ? { ...result.data, is_active: current.is_active } : result.data))
                    })
                  }}
                />
              )}
              {activeTabId === 'nearby' && (
                <HotelTabNearby nearbyAttractions={hotel.nearby_attractions} nearbyEssentials={hotel.nearby_essentials} />
              )}
            </div>
          </div>
        </div>

        <UnsavedBar
          changedFields={changedFields}
          ragFieldsChanged={ragFieldsChanged}
          onDiscard={handleDiscard}
          onSave={handleSave}
          saving={saving}
        />
      </div>
    </>
  )
}
