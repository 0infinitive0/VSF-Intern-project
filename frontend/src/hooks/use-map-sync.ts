/**
 * use-map-sync.ts — shared hover/focus state between the map (markers,
 * route segments) and the timeline/hotel-card list. Deliberately
 * stage-scoped: one instance per StageHotels/StageWorkspace, NOT app-wide
 * context — hoveredId changes on every mousemove, and putting it in a
 * broadly-shared context would force a re-render tree far wider than the
 * few components that actually care (phase-10 plan §"Đồng bộ hover").
 */
import { useCallback, useState } from 'react'

export function useMapSync() {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  // Scrolls the corresponding card/timeline row into view — used when a
  // marker is clicked. CSS.escape guards sync ids that aren't guaranteed
  // selector-safe (reference_id/hotel.id are opaque backend-generated
  // strings; itemSyncId's synthetic "day-N-item-I" keys, from
  // lib/map-sync-id.ts, are already safe).
  const focusOn = useCallback((id: string) => {
    document.querySelector(`[data-card="${CSS.escape(id)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [])

  return { hoveredId, setHoveredId, focusOn }
}
