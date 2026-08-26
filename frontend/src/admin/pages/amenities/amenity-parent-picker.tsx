import { useEffect, useState } from 'react'
import { Input } from '../../ui/input'
import { getAmenity, listAmenityCatalog, type AmenityCatalogRow } from '../../api/amenity-catalog-client'

interface AmenityParentPickerProps {
  value: string
  onChange: (id: string) => void
  scope: 'hotel' | 'room'
  /** The row being edited, if any -- excluded from results so admin can't
   * hand-pick a self-reference (the multi-hop cycle check still happens
   * server-side, G4). */
  excludeId?: string
}

const SEARCH_DEBOUNCE_MS = 250
const RESULT_LIMIT = 20

/** amenity-parent-picker.tsx -- searchable "Danh mục cha" combobox. Searches
 * the server live (debounced) instead of preloading every approved amenity
 * up front -- the previous version had the page fetch the *entire* approved
 * catalog (looping past the list endpoint's 100-row page cap) on every
 * "+ Thêm tiện ích"/"Sửa" click just so this field had something to filter
 * client-side, which both re-downloaded ~450 rows on every open and quietly
 * broke once the catalog grew past whatever page count it looped to. Kept
 * local to pages/amenities/ rather than promoted to ui/ since
 * amenity-form-fields.tsx is its only caller. */
export function AmenityParentPicker({ value, onChange, scope, excludeId }: AmenityParentPickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<AmenityCatalogRow[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null)

  // Resolve just the one label the already-set value needs -- a single
  // cheap row read, not the whole catalog.
  useEffect(() => {
    if (!value) {
      setSelectedLabel(null)
      return
    }
    let cancelled = false
    getAmenity(value).then((result) => {
      if (!cancelled && result.ok) setSelectedLabel(result.data.label_vi)
    })
    return () => {
      cancelled = true
    }
  }, [value])

  // Query/scope change -- fresh search, back to page 1.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    const timer = setTimeout(() => {
      listAmenityCatalog({ scope, status: 'approved', category: 'all', q: query || undefined, sort: 'name', page: 1, pageSize: RESULT_LIMIT }).then(
        (result) => {
          if (cancelled) return
          setLoading(false)
          if (result.ok) {
            setResults(result.data.items.filter((o) => o.id !== excludeId))
            setTotal(result.data.total)
            setPage(1)
          }
        },
      )
    }, SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, query, scope, excludeId])

  function loadMore() {
    if (loading || loadingMore || results.length >= total) return
    const nextPage = page + 1
    setLoadingMore(true)
    listAmenityCatalog({ scope, status: 'approved', category: 'all', q: query || undefined, sort: 'name', page: nextPage, pageSize: RESULT_LIMIT }).then(
      (result) => {
        setLoadingMore(false)
        if (result.ok) {
          setResults((prev) => [...prev, ...result.data.items.filter((o) => o.id !== excludeId)])
          setPage(nextPage)
        }
      },
    )
  }

  function select(id: string) {
    onChange(id)
    setOpen(false)
    setQuery('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
      <label htmlFor="amenity-parent-picker" className="field-label">
        Danh mục cha (tuỳ chọn)
      </label>
      <Input
        id="amenity-parent-picker"
        placeholder="Không có — gõ để tìm…"
        value={open ? query : (selectedLabel ?? '')}
        onFocus={() => {
          setOpen(true)
          setQuery('')
        }}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false)
            e.currentTarget.blur()
          }
        }}
        onBlur={() => setOpen(false)}
        autoComplete="off"
      />
      {open && (
        <div
          onScroll={(e) => {
            const el = e.currentTarget
            if (el.scrollHeight - el.scrollTop - el.clientHeight < 40) loadMore()
          }}
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 20,
            marginTop: 4,
            maxHeight: 260,
            overflowY: 'auto',
            background: 'var(--g2)',
            border: '1px solid var(--stroke)',
            borderRadius: 10,
            boxShadow: '0 8px 24px rgba(0,0,0,.24)',
            padding: 4,
          }}
        >
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => select('')}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 10px',
              fontSize: 13,
              color: 'var(--t3)',
              background: value === '' ? 'var(--acc-soft)' : 'transparent',
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
            }}
          >
            Không có
          </button>
          {loading && <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Đang tìm…</div>}
          {!loading && results.length === 0 && <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Không tìm thấy</div>}
          {!loading &&
            results.map((option) => (
              <button
                key={option.id}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => select(option.id)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '8px 10px',
                  fontSize: 13,
                  background: option.id === value ? 'var(--acc-soft)' : 'transparent',
                  border: 'none',
                  borderRadius: 8,
                  cursor: 'pointer',
                }}
              >
                {option.label_vi}
                <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--t4)' }}>{option.label_en}</span>
              </button>
            ))}
          {loadingMore && <div style={{ padding: '8px 10px', fontSize: 12, color: 'var(--t4)' }}>Đang tải thêm…</div>}
        </div>
      )}
    </div>
  )
}
