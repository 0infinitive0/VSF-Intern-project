import { Button } from '../../ui/button'

interface HotelsBulkBarProps {
  selectedCount: number
  onDeactivate: () => void
  onClear: () => void
  busy: boolean
}

/** hotels-bulk-bar.tsx — floats above the pagination bar once a row is
 * checked. Only 2 actions, not the design's 3 (phase-07-hotels-list.md
 * L19/L20): `Xoá` is cut for good (soft-delete decision #3, bookings.room_id
 * is ON DELETE RESTRICT), and `Chạy embedding` stays hidden until Phase 12
 * ships POST /admin/hotels/reembed rather than rendering a dead button. */
export function HotelsBulkBar({ selectedCount, onDeactivate, onClear, busy }: HotelsBulkBarProps) {
  if (selectedCount === 0) return null

  return (
    <div
      className="card"
      style={{
        position: 'sticky',
        bottom: 14,
        margin: '0 14px 14px',
        padding: '10px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        boxShadow: '0 12px 32px rgba(21, 24, 28, .16)',
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600 }}>Đã chọn {selectedCount} khách sạn</span>
      <div style={{ flex: 1 }} />
      <Button variant="secondary" size="sm" disabled={busy} onClick={onDeactivate}>
        Ngừng bán
      </Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={onClear}>
        Bỏ chọn
      </Button>
    </div>
  )
}
