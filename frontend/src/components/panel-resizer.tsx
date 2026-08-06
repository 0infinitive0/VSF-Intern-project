import type { MouseEvent } from 'react'

/**
 * Thin draggable divider between two side-by-side panels.
 */
export default function PanelResizer({
  onMouseDown,
}: {
  onMouseDown: (e: MouseEvent) => void
}) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="w-[2px] shrink-0 cursor-col-resize bg-surface-muted hover:bg-primary-fixed active:bg-primary transition-colors h-[calc(100%-52px)] translate-y-[26px]"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
    />
  )
}
