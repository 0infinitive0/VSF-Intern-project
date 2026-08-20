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
import { useCallback, useMemo, useState } from 'react'

export type Focus = { kind: 'hotel'; id: string } | { kind: 'place'; id: string } | null

export function useFocusMode() {
  const [focus, setFocus] = useState<Focus>(null)

  const openFocus = useCallback((next: NonNullable<Focus>) => {
    setFocus(next)
  }, [])

  const closeFocus = useCallback(() => {
    setFocus(null)
  }, [])

  // Memoized so this hook's return value keeps its identity across renders
  // where focus state hasn't changed — openFocus/closeFocus are already
  // stable, setFocus is stable by React contract, so `focus` is the only
  // field that ever actually changes this.
  return useMemo(() => ({ focus, openFocus, closeFocus, setFocus }), [focus, openFocus, closeFocus, setFocus])
}
