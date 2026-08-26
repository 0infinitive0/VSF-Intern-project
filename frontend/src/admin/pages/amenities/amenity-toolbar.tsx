import { AMENITY_CATEGORY_ORDER, categoryLabel } from '../../lib/amenity-categories'
import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import type { CatalogStatus } from '../../api/amenity-catalog-client'

interface AmenityToolbarProps {
  q: string
  onQChange: (q: string) => void
  category: string
  onCategoryChange: (category: string) => void
  status: CatalogStatus
  onStatusChange: (status: CatalogStatus) => void
  shownCount: number
  totalCount: number
}

export function AmenityToolbar({ q, onQChange, category, onCategoryChange, status, onStatusChange, shownCount, totalCount }: AmenityToolbarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div style={{ flex: 1, minWidth: 220, maxWidth: 320 }}>
        <Input placeholder="⌕ Tìm theo tên tiếng Việt, tiếng Anh…" value={q} onChange={(e) => onQChange(e.target.value)} />
      </div>

      <Select value={category} onChange={(e) => onCategoryChange(e.target.value)} style={{ width: 230 }}>
        <option value="all">Nhóm: Tất cả (14)</option>
        {AMENITY_CATEGORY_ORDER.map((c) => (
          <option key={c} value={c}>
            Nhóm: {categoryLabel(c)}
          </option>
        ))}
      </Select>

      <Select value={status} onChange={(e) => onStatusChange(e.target.value as CatalogStatus)} style={{ width: 200 }}>
        <option value="all">Trạng thái: Tất cả</option>
        <option value="approved">Trạng thái: Đã duyệt</option>
        <option value="pending">Trạng thái: Chờ duyệt</option>
        <option value="retired">Trạng thái: Đã ngừng dùng</option>
      </Select>

      <div style={{ flex: 1 }} />

      <span className="tabular-nums" style={{ fontSize: 12.5, color: 'var(--t3)', whiteSpace: 'nowrap' }}>
        Hiển thị {shownCount} / {totalCount} tiện ích
      </span>
    </div>
  )
}
