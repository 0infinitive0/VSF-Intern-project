import { Button } from '../../ui/button'

/** Backend column name -> Vietnamese label, for both this bar and
 * reembed-dialog.tsx's "Bạn vừa sửa X và Y" interpolation. `coordinates` is
 * this page's own pseudo-field for the latitude/longitude pair (there is no
 * single form field for it) -- see hotel-detail-page.tsx's changed-fields
 * computation. */
export const FIELD_LABELS: Record<string, string> = {
  name: 'Tên khách sạn',
  accommodation_type: 'Loại hình',
  star_rating: 'Hạng sao',
  description: 'Mô tả',
  location_highlight: 'Điểm nổi bật vị trí',
  address: 'Địa chỉ',
  city: 'Thành phố / Tỉnh',
  coordinates: 'Vĩ độ / Kinh độ',
  check_in_time: 'Giờ nhận phòng',
  check_out_time: 'Giờ trả phòng',
  amenities: 'Tiện ích',
  images: 'Hình ảnh',
}

interface UnsavedBarProps {
  changedFields: string[]
  ragFieldsChanged: string[]
  onDiscard: () => void
  onSave: () => void
  saving: boolean
}

/** unsaved-bar.tsx -- B3's sticky bottom bar (phase-09-hotel-edit.md). Lists
 * the actual changed field names (not a generic "you have unsaved changes")
 * and marks -- per field, with `*` -- exactly which ones affect the bot's
 * search: "nói rõ ô nào ảnh hưởng RAG, không phải câu chung chung" (plan's
 * L57). A blanket trailing "— ảnh hưởng tìm kiếm của bot" on the whole line
 * would misattribute RAG impact to every changed field whenever at least
 * one of them is RAG-relevant (e.g. "Mô tả · Hạng sao" -- only Mô tả is). */
export function UnsavedBar({ changedFields, ragFieldsChanged, onDiscard, onSave, saving }: UnsavedBarProps) {
  if (changedFields.length === 0) return null

  const ragSet = new Set(ragFieldsChanged)
  const names = changedFields
    .map((field) => {
      const label = FIELD_LABELS[field] ?? field
      return ragSet.has(field) ? `${label}*` : label
    })
    .join(' · ')

  return (
    <div
      style={{
        position: 'sticky',
        bottom: 0,
        flex: 'none',
        padding: '14px 28px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        background: 'var(--g2)',
        backdropFilter: 'blur(18px)',
        borderTop: '1px solid var(--stroke)',
      }}
    >
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Bạn có {changedFields.length} thay đổi chưa lưu
        </div>
        <div style={{ fontSize: 12, color: 'var(--t3)' }}>
          {names}
          {ragFieldsChanged.length > 0 && ' · * ảnh hưởng tìm kiếm của bot'}
        </div>
      </div>
      <Button variant="secondary" size="sm" onClick={onDiscard} disabled={saving}>
        Huỷ thay đổi
      </Button>
      <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>
        Lưu
      </Button>
    </div>
  )
}
