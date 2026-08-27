import { useState } from 'react'
import { Banner } from '../../../ui/banner'
import { Button } from '../../../ui/button'
import { Modal } from '../../../ui/modal'

interface RoomReembedDialogProps {
  open: boolean
  onClose: () => void
  hotelId: string
  ragFieldsChanged: string[]
}

/** `RAG_FIELDS_ROOM` (backend/src/api/admin/embedding_fields.py) -> Vietnamese
 * label, for this dialog's "Bạn vừa sửa X và Y" interpolation. */
const ROOM_FIELD_LABELS: Record<string, string> = {
  name: 'Tên phòng',
  bed_description: 'Mô tả giường',
  view: 'Hướng nhìn',
  room_facilities: 'Tiện nghi phòng',
}

function joinWithVa(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} và ${names[names.length - 1]}`
}

/** room-reembed-dialog.tsx -- B5's post-save dialog (phase-10-rooms.md):
 * "cùng hộp thoại `Chạy lại embedding ngay?` của Phase 9, phạm vi ghi
 * `1 phòng`". Deliberately does NOT call the shared `POST /hotels/reembed`
 * (phase-12-embedding-status.md): that endpoint is hotel-scoped (it marks
 * `hotels.embedding_stale` for the given `hotel_ids` and triggers a run over
 * all of them), so calling it here would re-embed the whole parent hotel
 * over an unrelated room-description edit -- exactly what this dialog's own
 * copy ("Chỉ nhúng lại phòng này — không ảnh hưởng các phòng còn lại")
 * promises won't happen. `update_room` already marked this room's
 * `embedding_stale` at save time (rooms.py), so there is nothing left to
 * trigger for the room itself
 * until Phase 13's Airflow client can kick off a real re-embed run -- "Chạy
 * ngay" just surfaces that state instead of firing a request. */
export function RoomReembedDialog({ open, onClose, hotelId: _hotelId, ragFieldsChanged }: RoomReembedDialogProps) {
  const [state, setState] = useState<'idle' | 'unavailable'>('idle')

  function handleReembedNow() {
    setState('unavailable')
  }

  function handleClose() {
    setState('idle')
    onClose()
  }

  const changedNames = joinWithVa(ragFieldsChanged.map((field) => ROOM_FIELD_LABELS[field] ?? field))

  return (
    <Modal open={open} onClose={handleClose}>
      <div style={{ fontSize: 15, fontWeight: 600 }}>Chạy lại embedding ngay?</div>
      <div style={{ fontSize: 13, color: 'var(--t3)' }}>
        Bạn vừa sửa <strong>{changedNames}</strong>. Bot vẫn dùng nội dung cũ cho tới khi embedding lại.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--t4)' }}>Phạm vi</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>1 phòng</div>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>Chỉ nhúng lại phòng này — không ảnh hưởng các phòng còn lại.</div>

      {state === 'unavailable' && (
        <Banner tone="warn">Đã đánh dấu cần nhúng lại. Chạy pipeline embedding ở trang Tổng quan để bot học ngay.</Banner>
      )}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button variant="secondary" size="sm" onClick={handleClose}>
          Để sau
        </Button>
        <Button variant="primary" size="sm" onClick={handleReembedNow} disabled={state === 'unavailable'}>
          Chạy ngay
        </Button>
      </div>
    </Modal>
  )
}
