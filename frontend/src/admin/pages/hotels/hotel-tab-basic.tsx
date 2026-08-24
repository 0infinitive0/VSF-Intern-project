import { HotelBasicFields, type HotelBasicFieldsValue } from './hotel-basic-fields'

interface HotelTabBasicProps {
  value: HotelBasicFieldsValue
  onChange: (next: HotelBasicFieldsValue) => void
  accommodationTypeOptions: string[]
  lockedFields: string[]
  changedFields: string[]
}

/** hotel-tab-basic.tsx -- B3's "Cơ bản" tab (phase-09-hotel-edit.md). All
 * field rendering lives in hotel-basic-fields.tsx (Phase 8, reused as-is);
 * this only turns on `showLocationHighlight` (B2's create form excludes it,
 * L28) and fixes the 1000-char description cap to the DB's soft limit. */
export function HotelTabBasic({ value, onChange, accommodationTypeOptions, lockedFields, changedFields }: HotelTabBasicProps) {
  return (
    <HotelBasicFields
      value={value}
      onChange={onChange}
      accommodationTypeOptions={accommodationTypeOptions}
      lockedFields={lockedFields}
      changedFields={changedFields}
      descriptionMaxLength={1000}
      showLocationHighlight
    />
  )
}
