import { useEffect, useMemo, useState } from 'react'
import {
  getHotel,
  listAccommodationTypes,
  listAmenities,
  listDestinations,
  setHotelActive,
  updateHotel,
  type AmenityOption,
  type DestinationOption,
  type HotelDetailResponse,
  type UpdateHotelRequest,
} from '../../api/hotels-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
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
import { ReembedDialog } from './reembed-dialog'
import { UnsavedBar } from './unsaved-bar'

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
  void navigate
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
  const [reembedOpen, setReembedOpen] = useState(false)
  const [lastRagFieldsChanged, setLastRagFieldsChanged] = useState<string[]>([])

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
    if (result.data.rag_fields_changed.length > 0) {
      setLastRagFieldsChanged(result.data.rag_fields_changed)
      setReembedOpen(true)
    }
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
    return <div style={{ flex: 1, padding: 28 }} />
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
      <PageHeader
        breadcrumb={`Quản trị · Khách sạn · ${hotel.name}`}
        title={hotel.name}
        action={
          <>
            <HotelSourceChip isManual={hotel.is_manual} />
            <HotelEmbeddingDot
              embeddingState={hotel.embedding_state}
              roomCount={hotel.room_count}
              roomsMissingEmbedding={hotel.rooms_missing_embedding}
            />
            <Switch checked={hotel.is_active} onChange={handleToggleActive} label="Đang bán" disabled={activeBusy} />
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '14px 28px 0' }}>
          {!hotel.is_manual && (
            <Banner tone="warn">
              Khách sạn này do pipeline ETL quản lý. Các ô có biểu tượng khoá sẽ bị ghi đè vào lần chạy kế tiếp.
            </Banner>
          )}
          {lookupError && (
            <div style={{ marginTop: 10 }}>
              <Banner tone="err">{lookupError}</Banner>
            </div>
          )}
          {activeError && (
            <div style={{ marginTop: 10 }}>
              <Banner tone="err">{activeError}</Banner>
            </div>
          )}
          {saveError && (
            <div style={{ marginTop: 10 }}>
              <Banner tone="err">{saveError}</Banner>
            </div>
          )}
        </div>

        <div style={{ padding: '14px 28px 0' }}>
          <Tabs
            items={TABS.map((tab) => (tab.key === 'rooms' ? { ...tab, label: `Phòng (${hotel.room_count})` } : tab))}
            activeKey={activeTabId}
            onChange={setActiveTab}
          />
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 22 }}>
          {/* Rooms is a data table (8 columns), not a single-column form
              like every other tab -- the shared 760px card cap would force
              it into a narrow horizontal scroll for no reason. */}
          <div className="card" style={{ maxWidth: activeTabId === 'rooms' ? undefined : 760, padding: 20 }}>
            {activeTabId === 'basic' && (
              <HotelTabBasic
                value={basic}
                onChange={setBasic}
                accommodationTypeOptions={accommodationTypes}
                lockedFields={hotel.pipeline_managed_fields}
                changedFields={changedFields}
              />
            )}
            {activeTabId === 'location' && (
              <HotelTabLocation
                value={location}
                onChange={setLocation}
                destinations={destinations}
                lockedFields={hotel.pipeline_managed_fields}
                changedFields={changedFields}
              />
            )}
            {activeTabId === 'amenities' && (
              <HotelTabAmenities
                catalog={amenityCatalog}
                selected={amenityIds}
                onChange={setAmenityIds}
                locked={hotel.pipeline_managed_fields.includes('amenities')}
                changed={changedFields.includes('amenities')}
              />
            )}
            {activeTabId === 'images' && <HotelTabImages hotelId={hotelId} images={images} onChange={setImages} />}
            {activeTabId === 'rooms' && (
              <HotelTabRooms
                hotelId={hotelId}
                hotelName={hotel.name}
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

        <UnsavedBar
          changedFields={changedFields}
          ragFieldsChanged={ragFieldsChanged}
          onDiscard={handleDiscard}
          onSave={handleSave}
          saving={saving}
        />
      </div>

      <ReembedDialog
        open={reembedOpen}
        onClose={() => setReembedOpen(false)}
        hotelId={hotelId}
        ragFieldsChanged={lastRagFieldsChanged}
      />
    </>
  )
}
