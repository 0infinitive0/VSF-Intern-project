import type { MouseEvent, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import ItineraryPanel from './itinerary-panel'
import MapPanel from './map-panel'
import PanelResizer from './panel-resizer'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { StageView } from '../lib/derive-stage'
import type { ChatState } from '../types'

type FocusModeApi = ReturnType<typeof useFocusMode>

function StagePlaceholder({ icon, title, body, pending }: { icon: string; title: string; body: string; pending?: boolean }) {
  return (
    <div className="flex-1 flex items-center justify-center p-6">
      <div className="text-center text-on-surface-variant max-w-xs">
        <span
          className={`material-symbols-outlined text-4xl ${pending ? 'animate-pulse' : ''}`}
          aria-hidden="true"
        >
          {icon}
        </span>
        <div className="font-medium text-on-surface mt-2">{title}</div>
        <div className="text-sm mt-1">{body}</div>
      </div>
    </div>
  )
}

/**
 * StageRouter — renders one of the 4 stage views. intake/generating/hotels
 * are placeholders in Phase 5 (real content lands in Phase 7-8); workspace
 * reuses the existing ItineraryPanel + MapPanel so the app stays fully
 * runnable between phases.
 *
 * The map is wrapped in a transform-only container reacting to
 * `focusMode.focus` (scale/opacity, never unmount) — the same mechanism
 * app-shell.tsx uses for chat, applied here to the one real map instance
 * that exists in this phase. `focusMode` carries the full
 * open/close/setFocus API so a future phase's hotel/place cards can call it
 * from further down this tree without app-shell.tsx changing again.
 */
export default function StageRouter({
  stage,
  state,
  itineraryWidth,
  onItineraryResizeStart,
  focusMode,
}: {
  stage: StageView
  state: ChatState
  itineraryWidth: number
  onItineraryResizeStart: (e: MouseEvent) => void
  focusMode: FocusModeApi
}): ReactNode {
  const { t } = useTranslation()

  if (stage === 'intake') {
    return <StagePlaceholder icon="explore" title={t('stageIntakeTitle')} body={t('stageIntakeBody')} />
  }

  if (stage === 'generating') {
    return (
      <StagePlaceholder icon="auto_awesome" title={t('stageGeneratingTitle')} body={t('stageGeneratingBody')} pending />
    )
  }

  if (stage === 'hotels') {
    return <StagePlaceholder icon="hotel" title={t('stageHotelsTitle')} body={t('stageHotelsBody')} />
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
