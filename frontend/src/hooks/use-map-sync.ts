/**
 * use-map-sync.ts — shared hover/preview state between the map (markers,
 * route segments) and the timeline/hotel-card list. Deliberately
 * stage-scoped: one instance per StageHotels/StageWorkspace, NOT app-wide
 * context — hoveredId changes on every mousemove, and putting it in a
 * broadly-shared context would force a re-render tree far wider than the
 * few components that actually care (phase-10 plan §"Đồng bộ hover").
 *
 */
import { useCallback, useEffect, useRef, useState } from 'react'

// Dwell time before a marker hover triggers auto-scroll (UI-fix §9): the
// pointer must rest on the SAME marker for this long before its card
// scrolls into view. Sweeping across several markers in quick succession —
// each hover living far less than this — never fires a scroll at all,
// which is exactly the "no continuous/thrashing scroll" requirement; only a
// hover the user actually settles on does.
const SCROLL_DWELL_MS = 220

export function useMapSync() {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const scrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (scrollTimerRef.current != null) clearTimeout(scrollTimerRef.current)
    }
  }, [])

  // Scrolls the corresponding card/timeline row into view — used when a
  // marker is clicked. CSS.escape guards sync ids that aren't guaranteed
  // selector-safe (reference_id/hotel.id are opaque backend-generated
  // strings; itemSyncId's synthetic "day-N-item-I" keys, from
  // lib/map-sync-id.ts, are already safe).
  const focusOn = useCallback((id: string) => {
    document.querySelector(`[data-card="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [])

  // Hover that originated on a MARKER (not a card/timeline row, which is
  // already visible to whoever is hovering it) — sets hoveredId
  // IMMEDIATELY (the marker/route highlight must react instantly), but
  // defers the scrollIntoView side effect behind SCROLL_DWELL_MS so rapidly
  // sweeping the cursor across many markers doesn't thrash-scroll the list
  // (Phase 10.5 §3/§9, tightened by the UI-fix pass). Any pending scroll is
  // cancelled the moment hover moves to a different target (or clears).
  const hoverMarker = useCallback(
    (id: string | null) => {
      setHoveredId(id)
      if (scrollTimerRef.current != null) {
        clearTimeout(scrollTimerRef.current)
        scrollTimerRef.current = null
      }
      if (id) {
        scrollTimerRef.current = setTimeout(() => {
          scrollTimerRef.current = null
          focusOn(id)
        }, SCROLL_DWELL_MS)
      }
    },
    [focusOn],
  )

  return { hoveredId, setHoveredId, focusOn, hoverMarker }
}
