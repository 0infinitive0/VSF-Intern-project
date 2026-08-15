import { useEffect, useRef, useState } from 'react'

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

  const [render, setRender] = useState(open)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (open) {
      setRender(true)
      let raf2 = 0
      const raf1 = requestAnimationFrame(() => {
        raf2 = requestAnimationFrame(() => setVisible(true))
      })
      return () => {
        cancelAnimationFrame(raf1)
        cancelAnimationFrame(raf2)
      }
    } else {
      setVisible(false)
      const timer = setTimeout(() => setRender(false), 200)
      return () => clearTimeout(timer)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    confirmRef.current?.focus()
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onCancel])

  if (!render) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0"
        style={{
          background: 'rgba(12,18,30,.34)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          opacity: visible ? 1 : 0,
          transition: 'opacity .2s ease',
        }}
        onClick={onCancel}
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="glass-card relative z-10 w-full max-w-[340px] p-5 flex flex-col gap-4"
        style={{
          opacity: visible ? 1 : 0,
          transform: visible ? 'none' : 'scale(0.95)',
          transition: 'opacity .2s ease, transform .2s ease',
        }}
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
