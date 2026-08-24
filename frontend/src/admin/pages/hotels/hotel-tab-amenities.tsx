import { useMemo } from 'react'
import type { AmenityOption } from '../../api/hotels-client'
import { AMENITY_GROUP_ORDER, groupLabelForCategory } from '../../lib/amenity-groups'
import { PipelineFieldBadge } from './pipeline-field-badge'
import { RagFieldLabel } from './rag-field-label'

interface HotelTabAmenitiesProps {
  catalog: AmenityOption[]
  /** Ids currently selected. May contain ids not present in `catalog` --
   * this is expected, not a bug: an ETL-sourced hotel can carry an id that
   * has since fallen out of the approved/hotel-eligible catalog, and
   * toggling one chip must never silently drop those. */
  selected: string[]
  onChange: (next: string[]) => void
  locked: boolean
  changed: boolean
}

function ChangedBadge() {
  return <span style={{ fontSize: 11, color: 'var(--acc)', fontWeight: 600 }}>đã sửa</span>
}

/** hotel-tab-amenities.tsx -- B3's "Tiện ích" tab (phase-09-hotel-edit.md).
 * Groups the catalog's 14 real `category` values into the 5 display groups
 * from amenity-groups.ts (L33) -- the artboard's 5 Vietnamese group names
 * aren't a real column, they're a presentation-only mapping. */
export function HotelTabAmenities({ catalog, selected, onChange, locked, changed }: HotelTabAmenitiesProps) {
  const selectedSet = useMemo(() => new Set(selected), [selected])
  // Counted against `catalog`, not `selected.length` -- a legacy id not in
  // `catalog` (see props docstring) has no chip to represent it and would
  // otherwise inflate "Đã chọn" past the "/ N" total.
  const selectedInCatalogCount = useMemo(() => catalog.filter((entry) => selectedSet.has(entry.id)).length, [catalog, selectedSet])

  const groups = useMemo(() => {
    const byGroup = new Map<string, AmenityOption[]>()
    for (const label of AMENITY_GROUP_ORDER) byGroup.set(label, [])
    for (const entry of catalog) {
      byGroup.get(groupLabelForCategory(entry.category))?.push(entry)
    }
    return Array.from(byGroup.entries()).filter(([, items]) => items.length > 0)
  }, [catalog])

  function toggle(id: string) {
    // Adds/removes exactly this one id and otherwise leaves `selected` (and
    // its order) untouched -- rebuilding from `catalog`'s order would
    // silently drop any id `catalog` doesn't recognize (see the props
    // docstring), and clicking one chip has no reason to reorder the rest.
    if (selectedSet.has(id)) onChange(selected.filter((existing) => existing !== id))
    else onChange([...selected, id])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>Tiện ích khách sạn</span>
          <RagFieldLabel />
          {locked && <PipelineFieldBadge />}
          {changed && <ChangedBadge />}
        </div>
        <span style={{ fontSize: 12, color: 'var(--t3)' }}>
          Đã chọn {selectedInCatalogCount} / {catalog.length}
        </span>
      </div>

      {groups.map(([groupLabel, items]) => {
        const selectedInGroup = items.filter((item) => selectedSet.has(item.id)).length
        return (
          <div key={groupLabel} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--t2)' }}>
              {groupLabel} · {selectedInGroup}/{items.length}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {items.map((item) => {
                const isOn = selectedSet.has(item.id)
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={isOn ? 'amenity-chip amenity-chip--on' : 'amenity-chip'}
                    onClick={() => toggle(item.id)}
                  >
                    {isOn ? `✓ ${item.label_vi}` : item.label_vi}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
