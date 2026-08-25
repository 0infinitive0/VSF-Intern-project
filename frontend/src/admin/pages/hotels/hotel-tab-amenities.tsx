import { useMemo, useState } from 'react'
import type { AmenityOption } from '../../api/hotels-client'
import { AMENITY_CATEGORY_ORDER, categoryLabel } from '../../lib/amenity-categories'
import { Input } from '../../ui/input'
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
 * Sections the catalog by its real `category` column, one section per
 * category (see amenity-categories.ts) -- no consolidation into fewer
 * display buckets. */
export function HotelTabAmenities({ catalog, selected, onChange, locked, changed }: HotelTabAmenitiesProps) {
  const [search, setSearch] = useState('')
  const selectedSet = useMemo(() => new Set(selected), [selected])
  // Counted against `catalog`, not `selected.length` -- a legacy id not in
  // `catalog` (see props docstring) has no chip to represent it and would
  // otherwise inflate "Đã chọn" past the "/ N" total. Uses the unfiltered
  // catalog so typing a search query never changes this overall progress.
  const selectedInCatalogCount = useMemo(() => catalog.filter((entry) => selectedSet.has(entry.id)).length, [catalog, selectedSet])

  // Ordered by pick order (`selected`, not `catalog`) so the summary reads as
  // "what you've picked so far" -- a legacy id with no catalog entry (see
  // props docstring) has no label_vi to show here and is silently skipped,
  // same as it already is from `selectedInCatalogCount`.
  const selectedItems = useMemo(() => {
    const catalogById = new Map(catalog.map((entry) => [entry.id, entry]))
    return selected.map((id) => catalogById.get(id)).filter((entry): entry is AmenityOption => entry != null)
  }, [catalog, selected])

  // Plain substring match on label_vi -- catalog size is small (14 fixed
  // categories worth of entries) so this is just a find-as-you-type filter
  // over the existing sectioned chips, not a replacement for the chip grid.
  const filteredCatalog = useMemo(() => {
    const query = search.trim().toLowerCase()
    return query === '' ? catalog : catalog.filter((entry) => entry.label_vi.toLowerCase().includes(query))
  }, [catalog, search])

  const sections = useMemo(() => {
    const byCategory = new Map<string, AmenityOption[]>()
    for (const entry of filteredCatalog) {
      const items = byCategory.get(entry.category)
      if (items) items.push(entry)
      else byCategory.set(entry.category, [entry])
    }
    // Known categories render in the fixed backend-mirrored order; a
    // category the catalog has but AMENITY_CATEGORY_ORDER doesn't (see its
    // fallback) still renders, just appended at the end instead of dropped.
    const orderedCategories = [
      ...AMENITY_CATEGORY_ORDER.filter((category) => byCategory.has(category)),
      ...Array.from(byCategory.keys()).filter((category) => !AMENITY_CATEGORY_ORDER.includes(category)),
    ]
    return orderedCategories.map((category) => [category, categoryLabel(category), byCategory.get(category) as AmenityOption[]] as const)
  }, [filteredCatalog])

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

      {selectedItems.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--t2)' }}>Đã chọn ({selectedItems.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {selectedItems.map((item) => (
              <button key={item.id} type="button" className="amenity-chip amenity-chip--on" onClick={() => toggle(item.id)}>
                ✓ {item.label_vi}
              </button>
            ))}
          </div>
        </div>
      )}

      <Input
        type="search"
        placeholder="Tìm tiện ích..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Tìm tiện ích"
      />

      {sections.length === 0 && <span style={{ fontSize: 12.5, color: 'var(--t3)' }}>Không tìm thấy tiện ích phù hợp.</span>}

      {sections.map(([category, label, items]) => {
        const selectedInSection = items.filter((item) => selectedSet.has(item.id)).length
        return (
          <div key={category} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--t2)' }}>
              {label} · {selectedInSection}/{items.length}
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
