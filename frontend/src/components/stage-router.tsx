import type { MouseEvent, ReactNode } from 'react'
import ItineraryPanel from './itinerary-panel'
import MapPanel from './map-panel'
import PanelResizer from './panel-resizer'
import StageGenerating from './stage-generating'
import StageHotels from './stage-hotels'
import StageIntake from './stage-intake'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { StageView } from '../lib/derive-stage'
import type { ChatState } from '../types'

type FocusModeApi = ReturnType<typeof useFocusMode>

/**
 * StageRouter — renders one of the 4 stage views. intake/generating are real
 * since Phase 7 (hero + live intake checklist; processing state + real elapsed
 * seconds + skeletons); hotels is the Phase 8 split view (card list | map |
 * detail) with the two-step pick wired to onSend; workspace reuses the
 * existing ItineraryPanel + MapPanel so the app stays fully runnable between
 * phases.
 *
 * The map is wrapped in a transform-only container reacting to
 * `focusMode.focus` (scale/opacity, never unmount) — the same mechanism
 * app-shell.tsx uses for chat, applied here to the one real map instance
 * that exists in this phase. `focusMode` carries the full
 * open/close/setFocus API so a future phase's hotel/place cards can call it
 * from further down this tree without app-shell.tsx changing again.
 *
 * Stage swaps keep the outer flex-1 container stable and let each stage own
 * its entrance animation (vRise), so intake → generating → hotels transitions
 * don't jump layout.
 */
export default function StageRouter({
  stage,
  state,
  itineraryWidth,
  onItineraryResizeStart,
  focusMode,
  onSend,
}: {
  stage: StageView
  state: ChatState
  itineraryWidth: number
  onItineraryResizeStart: (e: MouseEvent) => void
  focusMode: FocusModeApi
  onSend: (text: string) => void
}): ReactNode {
  if (stage === 'intake') {
    return <StageIntake intake={state.intake} />
  }

  if (stage === 'generating') {
    return <StageGenerating elapsedMs={state.elapsedMs} />
  }

  if (stage === 'hotels') {
    return <StageHotels state={state} focusMode={focusMode} onSend={onSend} />
  }

  const focused = focusMode.focus !== null

  return (
    <div className="flex-1 flex overflow-hidden min-w-0">
      <ItineraryPanel tripPlan={state.tripPlan} width={itineraryWidth} />
      <PanelResizer onMouseDown={onItineraryResizeStart} />
      <div
        className="flex-1 min-w-0"
        style={{
          transform: focused ? 'scale(.94)' : 'none',
          opacity: focused ? 0 : 1,
          pointerEvents: focused ? 'none' : 'auto',
          transition: 'transform .5s var(--ease-glide), opacity .38s ease',
        }}
      >
        <MapPanel />
      </div>
    </div>
  )
}
