import { useEffect, useRef } from 'react'

/**
 * ConfirmDialog — small reusable alert-dialog: backdrop + glass-card with a
 * message and two buttons. Replaces `window.confirm()` (unstyled, blocks the
 * main thread, can't be themed) for destructive actions like deleting a
 * history-rail conversation.
 *
 * Not tied to any one caller — `title`/`message`/labels are all props so a
 * future confirm (e.g. delete a hotel pick) can reuse it as-is.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel: string
  cancelLabel: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    confirmRef.current?.focus()
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(12,18,30,.34)', backdropFilter: 'blur(10px)', WebkitBackdropFilter: 'blur(10px)', animation: 'vFade .18s ease both' }}
      onClick={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="glass-card w-full max-w-[340px] p-5 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col gap-1.5">
          <div id="confirm-dialog-title" className="text-[14px] font-semibold text-on-surface">
            {title}
          </div>
          <div id="confirm-dialog-message" className="text-[12.5px] text-on-surface-muted leading-relaxed">
            {message}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="h-9 px-3.5 rounded-[10px] text-[12.5px] font-medium text-on-surface-variant hover:bg-glass-2 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            className={`h-9 px-3.5 rounded-[10px] text-[12.5px] font-semibold transition-colors ${
              destructive ? 'bg-error text-on-error hover:brightness-110' : 'bg-primary text-on-primary hover:brightness-110'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
