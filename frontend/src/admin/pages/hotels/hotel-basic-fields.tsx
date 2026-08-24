import { useId } from 'react'
import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import { Textarea } from '../../ui/textarea'
import { RagFieldLabel } from './rag-field-label'

export interface HotelBasicFieldsValue {
  name: string
  accommodationType: string
  starRating: number | null
  description: string
}

interface HotelBasicFieldsProps {
  value: HotelBasicFieldsValue
  onChange: (next: HotelBasicFieldsValue) => void
  accommodationTypeOptions: string[]
  /** DB column names (e.g. 'name', 'star_rating') this hotel's row got from
   * the ETL pipeline -- disabled here so B3 can't edit a pipeline-owned
   * field. B2 always passes []. */
  lockedFields: string[]
  descriptionMaxLength: number
}

const STAR_OPTIONS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

function starLabel(n: number): string {
  const full = '★'.repeat(Math.floor(n))
  const half = n % 1 !== 0 ? '½' : ''
  return n === 0 ? 'Chưa xếp hạng' : `${full}${half} (${n})`
}

/** hotel-basic-fields.tsx -- "Thông tin cơ bản" group, shared by B2
 * (hotel-create-page.tsx, lockedFields=[]) and B3's Cơ bản tab
 * (phase-09-hotel-edit.md, lockedFields=ETL columns). */
export function HotelBasicFields({ value, onChange, accommodationTypeOptions, lockedFields, descriptionMaxLength }: HotelBasicFieldsProps) {
  const locked = (field: string) => lockedFields.includes(field)
  // Unique per mounted instance -- B3 (Phase 9) is expected to render this
  // component alongside other field groups, and a literal id would collide
  // across two instances.
  const uid = useId()
  const nameId = `${uid}-name`
  const typeId = `${uid}-type`
  const typeListId = `${uid}-type-options`
  const starId = `${uid}-star-rating`
  const descriptionId = `${uid}-description`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <label htmlFor={nameId} className="field-label">
            Tên khách sạn
          </label>
          <RagFieldLabel />
        </div>
        <Input
          id={nameId}
          placeholder="Boutique Hoi An Riverside"
          value={value.name}
          disabled={locked('name')}
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
          </div>
          <Input
            id={typeId}
            list={typeListId}
            maxLength={50}
            placeholder="Khách sạn boutique"
            value={value.accommodationType}
            disabled={locked('accommodation_type')}
            onChange={(e) => onChange({ ...value, accommodationType: e.target.value })}
          />
          <datalist id={typeListId}>
            {accommodationTypeOptions.map((type) => (
              <option key={type} value={type} />
            ))}
          </datalist>
        </div>

        <Select
          id={starId}
          label="Hạng sao"
          value={value.starRating ?? ''}
          disabled={locked('star_rating')}
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

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <label htmlFor={descriptionId} className="field-label">
              Mô tả
            </label>
            <RagFieldLabel />
          </div>
          <span style={{ fontSize: 11, color: 'var(--t4)' }}>
            {value.description.length} / {descriptionMaxLength} ký tự
          </span>
        </div>
        <Textarea
          id={descriptionId}
          rows={4}
          maxLength={descriptionMaxLength}
          disabled={locked('description')}
          value={value.description}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
        />
      </div>
    </div>
  )
}
