import { useEffect, useRef, useState } from 'react'

/**
 * useMountTransition — gives a modal that's always rendered by its parent
 * (driven by a boolean `open` prop, e.g. AuthPanel) a real closing
 * transition instead of `if (!open) return null` snapping it away.
 *
 * `mounted` stays true for `exitDurationMs` after `open` goes false, so the
 * caller can keep rendering while it plays a fade/scale-out; `visible` is
 * the flag to drive that transition off (starts false, flips true a frame
 * later on open so the "hidden" state paints once before transitioning —
 * without that a same-frame flip can get coalesced and skip the animation
 * entirely — then flips back to false immediately on close).
 *
 * Not a fit for a modal whose parent conditionally mounts it (e.g.
 * ProfilePasswordModal, portaled in only while its own `open` state is
 * true) — there the delay has to happen before the parent calls its own
 * unmounting `onClose`, which is a different shape than this "stay mounted
 * longer than the prop says" pattern.
 */
export function useMountTransition(open: boolean, exitDurationMs: number) {
  const [mounted, setMounted] = useState(open)
  const [visible, setVisible] = useState(false)
  const exitTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => {
    clearTimeout(exitTimerRef.current)
    if (open) {
      setMounted(true)
      let raf2 = 0
      const raf1 = requestAnimationFrame(() => {
        raf2 = requestAnimationFrame(() => setVisible(true))
      })
      return () => {
        cancelAnimationFrame(raf1)
        cancelAnimationFrame(raf2)
      }
    }
    setVisible(false)
    exitTimerRef.current = setTimeout(() => setMounted(false), exitDurationMs)
    return () => clearTimeout(exitTimerRef.current)
  }, [open, exitDurationMs])

  return { mounted, visible }
}
