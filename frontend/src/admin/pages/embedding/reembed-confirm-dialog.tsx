import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import { Switch } from '../../ui/switch'

interface ReembedConfirmDialogProps {
  open: boolean
  count: number
  includeRooms: boolean
  busy: boolean
  onIncludeRoomsChange: (value: boolean) => void
  onConfirm: () => void
  onClose: () => void
}

/** reembed-confirm-dialog.tsx — shared by B1's bulk bar and B7's row
 * action (phase-12-embedding-status.md). The phase's own risk table:
 * "`include_rooms` mặc định `false`; UI hỏi rõ trước khi bật" -- a bulk
 * reembed nulls every selected hotel's embedding (and every room under it
 * when this is on), which drops them out of `match_hotels_with_rooms`
 * until the next scheduled run, so it needs the same confirm-before-write
 * posture as B1's bulk deactivate rather than firing straight from the
 * bar/row button. */
export function ReembedConfirmDialog({ open, count, includeRooms, busy, onIncludeRoomsChange, onConfirm, onClose }: ReembedConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onClose}>
      <div style={{ fontSize: 15, fontWeight: 600 }}>Chạy lại embedding cho {count} khách sạn?</div>
      <div style={{ fontSize: 13, color: 'var(--t3)' }}>
        Các khách sạn này sẽ tạm biến mất khỏi kết quả tìm kiếm của bot cho tới khi embedding lại xong.
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0' }}>
        <Switch checked={includeRooms} onChange={onIncludeRoomsChange} label="Kèm cả phòng thuộc các khách sạn này" disabled={busy} />
        <span style={{ fontSize: 13 }}>Kèm cả phòng thuộc các khách sạn này</span>
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button variant="secondary" size="sm" onClick={onClose} disabled={busy}>
          Huỷ
        </Button>
        <Button variant="primary" size="sm" onClick={onConfirm} disabled={busy}>
          Chạy embedding
        </Button>
      </div>
    </Modal>
  )
}
