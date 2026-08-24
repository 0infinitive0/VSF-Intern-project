import { useId } from 'react'
import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import { Textarea } from '../../ui/textarea'
import { PipelineFieldBadge } from './pipeline-field-badge'
import { RagFieldLabel } from './rag-field-label'

export interface HotelBasicFieldsValue {
  name: string
  accommodationType: string
  starRating: number | null
  description: string
  locationHighlight: string
}

interface HotelBasicFieldsProps {
  value: HotelBasicFieldsValue
  onChange: (next: HotelBasicFieldsValue) => void
  accommodationTypeOptions: string[]
  /** DB column names (e.g. 'name', 'star_rating') this hotel's row got from
   * the ETL pipeline. Renders the 🔒 warning badge next to the field's
   * label -- decision #7 (phase-09-hotel-edit.md) means the field stays
   * fully editable regardless; this is a warning, never a `disabled`.
   * B2 always passes []. */
  lockedFields: string[]
  /** Field names changed from the loaded value but not yet saved -- renders
   * the "đã sửa" badge next to that field's label. B2 always passes []. */
  changedFields: string[]
  descriptionMaxLength: number
  /** B3's Cơ bản tab only (L28 excludes it from B2). Điểm nổi bật vị trí
   * (`location_highlight`) is RAG-relevant but wasn't part of B2's create
   * form. */
  showLocationHighlight?: boolean
}

const STAR_OPTIONS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

function starLabel(n: number): string {
  const full = '★'.repeat(Math.floor(n))
  const half = n % 1 !== 0 ? '½' : ''
  return n === 0 ? 'Chưa xếp hạng' : `${full}${half} (${n})`
}

function ChangedBadge() {
  return <span style={{ fontSize: 11, color: 'var(--acc)', fontWeight: 600 }}>đã sửa</span>
}

/** hotel-basic-fields.tsx -- "Thông tin cơ bản" group, shared by B2
 * (hotel-create-page.tsx, lockedFields=[]) and B3's Cơ bản tab
 * (phase-09-hotel-edit.md, lockedFields=ETL columns). */
export function HotelBasicFields({
  value,
  onChange,
  accommodationTypeOptions,
  lockedFields,
  changedFields,
  descriptionMaxLength,
  showLocationHighlight,
}: HotelBasicFieldsProps) {
  const locked = (field: string) => lockedFields.includes(field)
  const changed = (field: string) => changedFields.includes(field)
  // Unique per mounted instance -- B3 (Phase 9) is expected to render this
  // component alongside other field groups, and a literal id would collide
  // across two instances.
  const uid = useId()
  const nameId = `${uid}-name`
  const typeId = `${uid}-type`
  const typeListId = `${uid}-type-options`
  const starId = `${uid}-star-rating`
  const descriptionId = `${uid}-description`
  const locationHighlightId = `${uid}-location-highlight`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <label htmlFor={nameId} className="field-label">
            Tên khách sạn
          </label>
          <RagFieldLabel />
          {locked('name') && <PipelineFieldBadge />}
          {changed('name') && <ChangedBadge />}
        </div>
        <Input
          id={nameId}
          placeholder="Boutique Hoi An Riverside"
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={typeId} className="field-label">
              Loại hình
            </label>
            <RagFieldLabel />
            {locked('accommodation_type') && <PipelineFieldBadge />}
            {changed('accommodation_type') && <ChangedBadge />}
          </div>
          <Input
            id={typeId}
            list={typeListId}
            maxLength={50}
            placeholder="Khách sạn boutique"
            value={value.accommodationType}
            onChange={(e) => onChange({ ...value, accommodationType: e.target.value })}
          />
          <datalist id={typeListId}>
            {accommodationTypeOptions.map((type) => (
              <option key={type} value={type} />
            ))}
          </datalist>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={starId} className="field-label">
              Hạng sao
            </label>
            {locked('star_rating') && <PipelineFieldBadge />}
            {changed('star_rating') && <ChangedBadge />}
          </div>
          <Select
            id={starId}
            value={value.starRating ?? ''}
            onChange={(e) => onChange({ ...value, starRating: e.target.value === '' ? null : Number(e.target.value) })}
          >
            <option value="">— Chưa chọn —</option>
            {STAR_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {starLabel(n)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={descriptionId} className="field-label">
              Mô tả
            </label>
            <RagFieldLabel />
            {locked('description') && <PipelineFieldBadge />}
            {changed('description') && <ChangedBadge />}
          </div>
          <span style={{ fontSize: 11, color: 'var(--t4)' }}>
            {value.description.length} / {descriptionMaxLength} ký tự
          </span>
        </div>
        <Textarea
          id={descriptionId}
          rows={4}
          maxLength={descriptionMaxLength}
          value={value.description}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
      </div>

      {showLocationHighlight && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={locationHighlightId} className="field-label">
              Điểm nổi bật vị trí
            </label>
            <RagFieldLabel />
            {locked('location_highlight') && <PipelineFieldBadge />}
            {changed('location_highlight') && <ChangedBadge />}
          </div>
          <Input
            id={locationHighlightId}
            maxLength={255}
            placeholder="Cách bãi biển 350 mét"
            value={value.locationHighlight}
            onChange={(e) => onChange({ ...value, locationHighlight: e.target.value })}
          />
        </div>
      )}
    </div>
  )
}
