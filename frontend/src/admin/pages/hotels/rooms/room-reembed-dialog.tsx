import { useState } from 'react'
import { reembedHotel } from '../../../api/hotels-client'
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
 * `1 phòng`". There is no per-room reembed endpoint (Phase 13's Airflow
 * client doesn't exist yet, same as B3's), so this reuses B3's hotel-scoped
 * `POST /reembed` trigger -- the same mechanism, only the displayed scope
 * label differs ("1 phòng" instead of "1 khách sạn"). */
export function RoomReembedDialog({ open, onClose, hotelId, ragFieldsChanged }: RoomReembedDialogProps) {
  const [state, setState] = useState<'idle' | 'loading' | 'unavailable' | 'queued'>('idle')

  async function handleReembedNow() {
    setState('loading')
    const result = await reembedHotel(hotelId)
    setState(result.ok ? 'queued' : 'unavailable')
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
        <Banner tone="warn">Đã đánh dấu cần nhúng lại. Chạy pipeline embedding ở mục Dữ liệu bot để bot học ngay.</Banner>
      )}
      {state === 'queued' && <Banner tone="ok">Đã gửi yêu cầu chạy lại embedding.</Banner>}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button variant="secondary" size="sm" onClick={handleClose} disabled={state === 'loading'}>
          Để sau
        </Button>
        <Button variant="primary" size="sm" onClick={handleReembedNow} disabled={state === 'loading' || state === 'queued'}>
          Chạy ngay
        </Button>
      </div>
    </Modal>
  )
}
