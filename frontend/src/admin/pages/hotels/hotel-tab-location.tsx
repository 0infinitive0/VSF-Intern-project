import type { DestinationOption } from '../../api/hotels-client'
import { HotelLocationFields, type HotelLocationFieldsValue } from './hotel-location-fields'

interface HotelTabLocationProps {
  value: HotelLocationFieldsValue
  onChange: (next: HotelLocationFieldsValue) => void
  destinations: DestinationOption[]
  changedFields: string[]
}

/** hotel-tab-location.tsx -- B3's "Vị trí" tab (phase-09-hotel-edit.md).
 * Thin wrapper: all field rendering lives in hotel-location-fields.tsx
 * (Phase 8, reused as-is per the plan). */
export function HotelTabLocation({ value, onChange, destinations, changedFields }: HotelTabLocationProps) {
  return (
    <HotelLocationFields
      value={value}
      onChange={onChange}
      destinations={destinations}
      changedFields={changedFields}
    />
  )
}
