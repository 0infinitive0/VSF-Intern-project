import { Button } from '../../ui/button'
import { Modal } from '../../ui/modal'

interface PipelineTriggerDialogProps {
  open: boolean
  label: string | null
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}

/** pipeline-trigger-dialog.tsx — "xác nhận đơn giản `Chạy pipeline {tên}?` +
 * hậu quả một dòng" (L59, phase-14-pipelines-list.md). Used for all 4 cards
 * today, Embedding included: Phase 15's richer options dialog (C2) doesn't
 * exist yet, and this endpoint already runs a full embed with `conf: {}`
 * (the DAG's own `only_null=true` default) -- a working simple confirm now,
 * not a dead end, and Phase 15 upgrades Embedding's dialog in place. */
export function PipelineTriggerDialog({ open, label, busy, onConfirm, onClose }: PipelineTriggerDialogProps) {
  return (
    <Modal open={open} onClose={onClose}>
      <div style={{ fontSize: 15, fontWeight: 600 }}>Chạy pipeline {label}?</div>
      <div style={{ fontSize: 13, color: 'var(--t3)' }}>Pipeline sẽ chạy ngay, không thể huỷ giữa chừng sau khi bắt đầu.</div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button variant="secondary" size="sm" onClick={onClose} disabled={busy}>
          Huỷ
        </Button>
        <Button variant="primary" size="sm" onClick={onConfirm} disabled={busy}>
          Chạy
        </Button>
      </div>
    </Modal>
  )
}
