import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import type { AmenityCatalogRow, RetireBlockedError } from '../../api/amenity-catalog-client'

interface RetireBlockedDialogProps {
  open: boolean
  onClose: () => void
  row: AmenityCatalogRow | null
  blocked: RetireBlockedError | null
  onReload: () => void
}

/** retire-blocked-dialog.tsx -- the 409 safety net for "Ngừng dùng"
 * (phase-18-amenity-catalog.md). The table already disables the button
 * client-side once usage/child_count > 0, so reaching this dialog means the
 * row changed between load and click (G8/G12) -- it explains why, not just
 * that it failed. */
export function RetireBlockedDialog({ open, onClose, row, blocked, onReload }: RetireBlockedDialogProps) {
  if (!open || !row || !blocked) return null

  const isChildBlock = blocked.detail === 'amenity_has_active_children'
  const reason = isChildBlock
    ? `Còn ${blocked.child_count} tiện ích con đang tham chiếu vào nó.`
    : `Hiện đang dùng ở ${blocked.hotel_count} khách sạn và ${blocked.room_count} phòng.`
  const why = isChildBlock
    ? 'Ngừng dùng một tiện ích cha khi vẫn còn tiện ích con sống sẽ để con trỏ vào một mục không còn hiển thị được.'
    : 'Ngừng dùng chỉ áp dụng cho tiện ích không còn khách sạn/phòng nào tham chiếu — bảng bạn đang xem có thể chưa cập nhật kịp một thay đổi vừa xảy ra ở nơi khác.'

  return (
    <Modal open={open} onClose={onClose}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{row.label_vi}</div>
          <div style={{ fontSize: 11, color: 'var(--t4)' }}>{row.label_en}</div>
        </div>
        <div>
          <div style={{ fontSize: 15.5, fontWeight: 700 }}>Không thể ngừng dùng</div>
          <div style={{ fontSize: 12.5, color: 'var(--t2)', marginTop: 4 }}>{reason}</div>
        </div>
        <div className="banner banner--warn" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: '.02em' }}>VÌ SAO BỊ CHẶN</div>
          <div style={{ fontSize: 12 }}>{why}</div>
          {isChildBlock && blocked.children && blocked.children.length > 0 && (
            <ul style={{ margin: '4px 0 0', paddingLeft: 18, fontSize: 12 }}>
              {blocked.children.map((child) => (
                <li key={child.id}>{child.label_vi}</li>
              ))}
            </ul>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Đã hiểu
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              onReload()
              onClose()
            }}
          >
            Tải lại bảng
          </Button>
        </div>
      </div>
    </Modal>
  )
}
