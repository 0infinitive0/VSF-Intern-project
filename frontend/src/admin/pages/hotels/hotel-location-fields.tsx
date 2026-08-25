import { useId } from 'react'
import type { DestinationOption } from '../../api/hotels-client'
import { Input } from '../../ui/input'
import { MapStaticPreview } from './map-static-preview'
import { PipelineFieldBadge } from './pipeline-field-badge'
import { RagFieldLabel } from './rag-field-label'

export interface HotelLocationFieldsValue {
  address: string
  city: string
  latitude: number | null
  longitude: number | null
}

interface HotelLocationFieldsProps {
  value: HotelLocationFieldsValue
  onChange: (next: HotelLocationFieldsValue) => void
  destinations: DestinationOption[]
  /** DB column names this hotel's row got from the ETL pipeline. Renders the
   * 🔒 warning badge next to the field's label -- decision #7
   * (phase-09-hotel-edit.md) means the field stays fully editable
   * regardless; this is a warning, never a `disabled`. B2 always passes []. */
  lockedFields: string[]
  /** Field names changed from the loaded value but not yet saved -- renders
   * the "đã sửa" badge next to that field's label. B2 always passes []. */
  changedFields: string[]
}

function toNumberOrNull(raw: string): number | null {
  if (raw.trim() === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function ChangedBadge() {
  return <span style={{ fontSize: 11, color: 'var(--acc)', fontWeight: 600 }}>đã sửa</span>
}

/** hotel-location-fields.tsx -- "Vị trí" group, shared by B2
 * (hotel-create-page.tsx, lockedFields=[]) and B3's Vị trí tab
 * (phase-09-hotel-edit.md, lockedFields=ETL columns). `city` stays free
 * text (L26); resolving it to a `destination_id` only happens at submit
 * time in hotel-create-page.tsx (against whatever `destinations` list has
 * loaded by then), not here on every keystroke -- doing it here would race
 * the destinations fetch and could silently drop a match typed before the
 * list arrived. */
export function HotelLocationFields({ value, onChange, destinations, lockedFields, changedFields }: HotelLocationFieldsProps) {
  const locked = (field: string) => lockedFields.includes(field)
  const changed = (field: string) => changedFields.includes(field)
  // Unique per mounted instance -- B3 (Phase 9) is expected to render this
  // component alongside other field groups, and a literal id would collide
  // across two instances.
  const uid = useId()
  const addressId = `${uid}-address`
  const cityId = `${uid}-city`
  const cityListId = `${uid}-destination-options`
  const latitudeId = `${uid}-latitude`
  const longitudeId = `${uid}-longitude`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <label htmlFor={addressId} className="field-label">
            Địa chỉ
          </label>
          <RagFieldLabel />
          {locked('address') && <PipelineFieldBadge />}
          {changed('address') && <ChangedBadge />}
        </div>
        <Input
          id={addressId}
          maxLength={500}
          placeholder="42 Nguyễn Phúc Chu, phường Minh An"
          value={value.address}
          onChange={(e) => onChange({ ...value, address: e.target.value })}
        />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <label htmlFor={cityId} className="field-label">
            Thành phố / Tỉnh
          </label>
          {locked('city') && <PipelineFieldBadge />}
          {changed('city') && <ChangedBadge />}
        </div>
        <Input
          id={cityId}
          list={cityListId}
          maxLength={100}
          placeholder="Quảng Nam"
          value={value.city}
          onChange={(e) => onChange({ ...value, city: e.target.value })}
        />
        <datalist id={cityListId}>
          {destinations.map((d) => (
            <option key={d.id} value={d.name} />
          ))}
        </datalist>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={latitudeId} className="field-label">
              Vĩ độ
            </label>
            {locked('coordinates') && <PipelineFieldBadge />}
            {changed('coordinates') && <ChangedBadge />}
          </div>
          <Input
            id={latitudeId}
            type="number"
            step="any"
            placeholder="15.87721"
            value={value.latitude ?? ''}
            onChange={(e) => onChange({ ...value, latitude: toNumberOrNull(e.target.value) })}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={longitudeId} className="field-label">
              Kinh độ
            </label>
            {locked('coordinates') && <PipelineFieldBadge />}
            {changed('coordinates') && <ChangedBadge />}
          </div>
          <Input
            id={longitudeId}
            type="number"
            step="any"
            placeholder="108.32694"
            value={value.longitude ?? ''}
            onChange={(e) => onChange({ ...value, longitude: toNumberOrNull(e.target.value) })}
          />
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span className="field-label">Xem trước vị trí trên bản đồ</span>
        <MapStaticPreview latitude={value.latitude} longitude={value.longitude} />
      </div>
    </div>
  )
}
