import { useState } from 'react'
import { bulkApproveAmenities, type AmenityCatalogRow } from '../../api/amenity-catalog-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Drawer } from '../../ui/drawer'
import { AmenityDraftCard } from './amenity-draft-card'

interface AmenityDraftReviewListProps {
  open: boolean
  onClose: () => void
  items: AmenityCatalogRow[]
  scope: 'hotel' | 'room'
  onDone: () => void
}

/** amenity-draft-review-list.tsx -- Bước 2 of "+ Thêm tiện ích"
 * (phase-18-amenity-catalog.md): the list of AI-drafted rows from POST
 * /draft, each already persisted `is_approved=false` (closing the drawer
 * mid-review leaves them in "Chờ duyệt" on the main table, same as a chat/
 * pipeline proposal -- there is no separate unsaved-draft state to lose).
 *
 * The parent (amenity-catalog-page.tsx) keeps this component mounted the
 * whole time and only toggles `open`/`items` -- it never remounts it. Track
 * only which ids have been resolved this session (a Set), not a copy of
 * `items` itself: copying into `useState(items)` only captures whatever
 * `items` was at the FIRST mount (empty, before any draft ever ran) and
 * never re-syncs on a later prop change, which left this drawer always
 * rendering "Đã xử lý xong." / 0 items even when /draft genuinely created a
 * new row -- the row was there in the main table, just never shown here. */
export function AmenityDraftReviewList({ open, onClose, items, scope, onDone }: AmenityDraftReviewListProps) {
  const [resolvedIds, setResolvedIds] = useState<Set<string>>(new Set())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  if (!open) return null

  const visible = items.filter((row) => !resolvedIds.has(row.id))

  function handleResolved(id: string) {
    setResolvedIds((prev) => {
      const next = new Set(prev)
      next.add(id)
      if (items.every((row) => next.has(row.id))) onDone()
      return next
    })
  }

  async function handleApproveAll() {
    setBulkBusy(true)
    setBulkError(null)
    const result = await bulkApproveAmenities(visible.map((row) => row.id))
    setBulkBusy(false)
    if (!result.ok) {
      setBulkError(result.detail)
      return
    }
    setResolvedIds(new Set(items.map((row) => row.id)))
    onDone()
  }

  return (
    <Drawer open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Xem lại &amp; duyệt</div>
            <div style={{ fontSize: 12.5, color: 'var(--t3)' }}>Bước 2 / 2 · {visible.length} tiện ích chờ duyệt</div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Đóng">
            ✕
          </Button>
        </div>

        <Banner tone="info">✨ AI đã điền các trường bên dưới từ tên bạn nhập — kiểm tra lại trước khi duyệt.</Banner>
        {bulkError && <Banner tone="err">{bulkError}</Banner>}

        {visible.length > 0 && (
          <Button variant="primary" size="sm" onClick={handleApproveAll} disabled={bulkBusy} style={{ alignSelf: 'flex-start' }}>
            {bulkBusy ? 'Đang duyệt…' : `Duyệt tất cả (${visible.length})`}
          </Button>
        )}

        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {visible.length === 0 && <div style={{ fontSize: 13, color: 'var(--t3)' }}>Đã xử lý xong.</div>}
          {visible.map((row) => (
            <AmenityDraftCard
              key={row.id}
              row={row}
              scope={scope}
              onApproved={handleResolved}
              onRejected={handleResolved}
              disabled={bulkBusy}
            />
          ))}
        </div>
      </div>
    </Drawer>
  )
}
