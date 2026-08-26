import { useEffect, useMemo, useState } from 'react'
import { createHotel, listAccommodationTypes, listDestinations, type CreateHotelRequest, type DestinationOption } from '../../api/hotels-client'
import { PageHeader } from '../../layout/page-header'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import { Select } from '../../ui/select'
import { HotelBasicFields, type HotelBasicFieldsValue } from './hotel-basic-fields'
import { HotelLocationFields, type HotelLocationFieldsValue } from './hotel-location-fields'

const DESCRIPTION_MAX_LENGTH = 1000
const DEFAULT_CHECK_IN_TIME = '14:00'
const DEFAULT_CHECK_OUT_TIME = '12:00'

const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const h = String(Math.floor(i / 2)).padStart(2, '0')
  const m = i % 2 === 0 ? '00' : '30'
  return `${h}:${m}`
})

interface HotelCreatePageProps {
  navigate: (to: string) => void
}

/** hotel-create-page.tsx -- B2 orchestrator (phase-08-hotel-create.md). Owns
 * form state and the two lookups (destinations, accommodation-type
 * suggestions); hotel-basic-fields.tsx/hotel-location-fields.tsx stay
 * presentational and are reused as-is by B3 (Phase 9). */
export function HotelCreatePage({ navigate }: HotelCreatePageProps) {
  const [basic, setBasic] = useState<HotelBasicFieldsValue>({
    name: '',
    accommodationType: '',
    starRating: null,
    description: '',
    locationHighlight: '',
  })
  const [location, setLocation] = useState<HotelLocationFieldsValue>({ address: '', city: '', latitude: null, longitude: null })
  const [checkInTime, setCheckInTime] = useState(DEFAULT_CHECK_IN_TIME)
  const [checkOutTime, setCheckOutTime] = useState(DEFAULT_CHECK_OUT_TIME)

  const [destinations, setDestinations] = useState<DestinationOption[]>([])
  const [accommodationTypes, setAccommodationTypes] = useState<string[]>([])
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [leaveConfirmOpen, setLeaveConfirmOpen] = useState(false)

  useEffect(() => {
    listDestinations().then((result) => {
      if (result.ok) setDestinations(result.data)
      else setLookupError((prev) => prev ?? `Không tải được danh sách tỉnh/thành: ${result.detail}`)
    })
    listAccommodationTypes().then((result) => {
      if (result.ok) setAccommodationTypes(result.data)
      else setLookupError((prev) => prev ?? `Không tải được gợi ý loại hình: ${result.detail}`)
    })
  }, [])

  const isDirty = useMemo(
    () =>
      basic.name !== '' ||
      basic.accommodationType !== '' ||
      basic.description !== '' ||
      basic.starRating !== null ||
      location.address !== '' ||
      location.city !== '' ||
      location.latitude !== null ||
      location.longitude !== null ||
      checkInTime !== DEFAULT_CHECK_IN_TIME ||
      checkOutTime !== DEFAULT_CHECK_OUT_TIME,
    [basic, location, checkInTime, checkOutTime],
  )

  // Covers reload/tab-close/external navigation. Internal navigation (the
  // Cancel button below) goes through leaveConfirmOpen instead, since
  // browser confirm() would look inconsistent with the rest of the portal.
  // A sidebar click away from this page is NOT intercepted -- doing that
  // would need a route-level guard in router.tsx/admin-shell.tsx, out of
  // this phase's scope.
  useEffect(() => {
    if (!isDirty) return
    function handler(e: BeforeUnloadEvent) {
      e.preventDefault()
      // Legacy engines (older Safari) ignore preventDefault() and only
      // prompt when returnValue is set to a non-empty string.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isDirty])

  function handleCancel() {
    if (isDirty) {
      setLeaveConfirmOpen(true)
      return
    }
    navigate('/admin/hotels')
  }

  async function handleSubmit() {
    setSubmitError(null)
    if (basic.name.trim() === '') {
      setSubmitError('Tên khách sạn là bắt buộc.')
      return
    }
    setSubmitting(true)
    const trimmedCity = location.city.trim()
    // Resolved here, against whatever `destinations` has loaded by submit
    // time, rather than while the admin was typing -- see
    // hotel-location-fields.tsx's module docstring for why.
    const matchedDestination = destinations.find((d) => d.name.toLowerCase() === trimmedCity.toLowerCase())
    const body: CreateHotelRequest = {
      name: basic.name.trim(),
      accommodation_type: basic.accommodationType.trim() || null,
      description: basic.description.trim() || null,
      star_rating: basic.starRating,
      address: location.address.trim() || null,
      destination_id: matchedDestination?.id ?? null,
      city: trimmedCity || null,
      latitude: location.latitude,
      longitude: location.longitude,
      check_in_time: checkInTime,
      check_out_time: checkOutTime,
    }
    const result = await createHotel(body)
    setSubmitting(false)
    if (!result.ok) {
      setSubmitError(result.detail)
      return
    }
    // Phase 10 (quản lý phòng) chưa xong -- về trang chi tiết (Phase 9, đã
    // xây), không kèm ?tab=rooms vì tab Phòng ở đó vẫn là chỗ giữ trống.
    navigate(`/admin/hotels/${result.data.id}`)
  }

  return (
    <>
      <PageHeader
        breadcrumb="Quản trị · Khách sạn · Thêm mới"
        title="Tạo khách sạn mới"
        action={
          <>
            <Button variant="secondary" size="sm" onClick={handleCancel} disabled={submitting}>
              Huỷ
            </Button>
            <Button variant="primary" size="sm" onClick={handleSubmit} disabled={submitting}>
              Lưu và tạo phòng
            </Button>
          </>
        }
      />

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '22px 28px' }}>
        <div style={{ maxWidth: 760, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Banner tone="info">Khách sạn tạo tay sẽ không bị pipeline ghi đè.</Banner>

          {lookupError && <Banner tone="err">{lookupError}</Banner>}
          {submitError && <Banner tone="err">{submitError}</Banner>}

          <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>Thông tin cơ bản</div>
            <HotelBasicFields
              value={basic}
              onChange={setBasic}
              accommodationTypeOptions={accommodationTypes}
              changedFields={[]}
              descriptionMaxLength={DESCRIPTION_MAX_LENGTH}
            />
          </div>

          <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>Vị trí</div>
            <HotelLocationFields
              value={location}
              onChange={setLocation}
              destinations={destinations}
              changedFields={[]}
            />
          </div>

          <div className="card" style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>Giờ nhận / trả phòng</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <Select id="hotel-check-in" label="Giờ nhận phòng" value={checkInTime} onChange={(e) => setCheckInTime(e.target.value)}>
                {TIME_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
              <Select id="hotel-check-out" label="Giờ trả phòng" value={checkOutTime} onChange={(e) => setCheckOutTime(e.target.value)}>
                {TIME_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <Banner tone="warn">Khách sạn mới chưa được embedding — bot chưa tìm thấy cho tới khi chạy lại pipeline.</Banner>
        </div>
      </div>

      <Modal open={leaveConfirmOpen} onClose={() => setLeaveConfirmOpen(false)}>
        <div style={{ fontSize: 15, fontWeight: 600 }}>Rời trang khi form đang dở?</div>
        <div style={{ fontSize: 13, color: 'var(--t3)' }}>Thay đổi chưa lưu sẽ bị mất.</div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={() => setLeaveConfirmOpen(false)}>
            Ở lại
          </Button>
          <Button variant="danger" size="sm" onClick={() => navigate('/admin/hotels')}>
            Rời trang
          </Button>
        </div>
      </Modal>
    </>
  )
}
