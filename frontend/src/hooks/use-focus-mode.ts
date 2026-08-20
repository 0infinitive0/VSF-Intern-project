/**
 * use-focus-mode.ts — owns the hotel/place focus UI state. This is genuinely
 * new UI state (not derivable from ChatState), used by app-shell.tsx to
 * collapse chat+map and expand the stage.
 *
 * Switching the focused id while already focused (e.g. picking a different
 * hotel) must not close focus mode — setFocus replaces the object in place,
 * so `focus !== null` never toggles false in between and no exit/enter
 * transition re-triggers.
 */
import { useCallback, useState } from 'react'

export type Focus = { kind: 'hotel'; id: string } | { kind: 'place'; id: string } | null

export function useFocusMode() {
  const [focus, setFocus] = useState<Focus>(null)

  const openFocus = useCallback((next: NonNullable<Focus>) => {
    setFocus(next)
  }, [])

  const closeFocus = useCallback(() => {
    setFocus(null)
  }, [])

  return { focus, openFocus, closeFocus, setFocus }
}
