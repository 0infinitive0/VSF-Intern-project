import { useCallback, useRef } from 'react'

/**
 * Drag-to-resize for a single panel edge.
 * Returns an onMouseDown handler to attach to the drag divider.
 */
export function usePanelResize(
  width: number,
  setWidth: (width: number) => void,
  { min, max }: { min: number; max: number },
) {
  const startX = useRef(0)
  const startWidth = useRef(0)

  const handleMove = useCallback(
    (e: MouseEvent) => {
      const delta = e.clientX - startX.current
      setWidth(Math.min(max, Math.max(min, startWidth.current + delta)))
    },
    [min, max, setWidth],
  )

  const handleUp = useCallback(() => {
    document.removeEventListener('mousemove', handleMove)
    document.removeEventListener('mouseup', handleUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [handleMove])

  const onMouseDown = useCallback(
    (e: { clientX: number }) => {
      startX.current = e.clientX
      startWidth.current = width
      document.addEventListener('mousemove', handleMove)
      document.addEventListener('mouseup', handleUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [width, handleMove, handleUp],
  )

  return onMouseDown
}
