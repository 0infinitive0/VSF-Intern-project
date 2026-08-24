import { useState } from 'react'
import { reembedHotel } from '../../api/hotels-client'
import { Banner } from '../../ui/banner'
import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'
import { FIELD_LABELS } from './unsaved-bar'

interface ReembedDialogProps {
  open: boolean
  onClose: () => void
  hotelId: string
  ragFieldsChanged: string[]
}

function joinWithVa(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} và ${names[names.length - 1]}`
}

/** reembed-dialog.tsx -- B3's post-save dialog (phase-09-hotel-edit.md).
 * Opens only when the save actually touched a RAG field. "Chạy ngay" calls
 * POST /reembed, which always 503s until Phase 13 (Airflow client) exists
 * -- `update_hotel` already cleared `embedding` regardless, so this dialog
 * stays useful even before that endpoint does anything (L36/L37: scope is
 * always "1 khách sạn", no time estimate -- no benchmark data to base one
 * on, and the plan says not to invent a number). */
export function ReembedDialog({ open, onClose, hotelId, ragFieldsChanged }: ReembedDialogProps) {
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

  const changedNames = joinWithVa(ragFieldsChanged.map((field) => FIELD_LABELS[field] ?? field))

  return (
    <Modal open={open} onClose={handleClose}>
      <div style={{ fontSize: 15, fontWeight: 600 }}>Chạy lại embedding ngay?</div>
      <div style={{ fontSize: 13, color: 'var(--t3)' }}>
        Bạn vừa sửa <strong>{changedNames}</strong>. Bot vẫn dùng nội dung cũ cho tới khi embedding lại.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="card" style={{ padding: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--t4)' }}>Phạm vi</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>1 khách sạn</div>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--t4)' }}>Chỉ nhúng lại khách sạn này — không ảnh hưởng các khách sạn còn lại.</div>

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
