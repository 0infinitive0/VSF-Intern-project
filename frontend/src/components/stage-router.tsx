import type { ReactNode } from 'react'
import StageGenerating from './stage-generating'
import StageHotels from './stage-hotels'
import StageIntake from './stage-intake'
import StageWorkspace from './stage-workspace'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { Theme } from '../hooks/use-theme'
import type { IntakeFormState } from '../lib/compose-intake-message'
import type { IntakeChecklistRowKey } from '../lib/intake-checklist-rows'
import type { StageView } from '../lib/derive-stage'
import type { ChatState, HotelOption } from '../types'

type FocusModeApi = ReturnType<typeof useFocusMode>

/**
 * StageRouter — renders one of the 4 stage views. intake/generating are real
 * since Phase 7 (hero + live intake checklist; processing state + real elapsed
 * seconds + skeletons); hotels is the Phase 8 split view (card list | map |
 * detail) with the two-step pick wired to onSend; workspace is the Phase 9
 * trip view (header, Tổng quan/day tabs, timeline) with Place Detail Focus
 * Mode — the map and detail panel live inside StageWorkspace, which owns its
 * own focus transforms so app-shell.tsx never changes again for Phase 10.
 *
 * `focusMode` carries the full open/close/setFocus API so future phases can
 * call it from deeper in the stage tree without touching app-shell.tsx.
 *
 * Stage swaps keep the outer flex-1 container stable and let each stage own
 * its entrance animation (vRise), so intake → generating → hotels → workspace
 * transitions don't jump layout.
 */
export default function StageRouter({
  stage,
  state,
  hotelOptions,
  selectedHotelIndex,
  onSelectHotel,
  onConfirmHotel,
  focusMode,
  onSend,
  intakeForm,
  onEditIntakeField,
  theme,
}: {
  stage: StageView
  state: ChatState
  hotelOptions: HotelOption[]
  selectedHotelIndex: number | null
  onSelectHotel: (index: number) => void
  onConfirmHotel: (hotel: HotelOption) => void
  focusMode: FocusModeApi
  onSend: (text: string) => void
  intakeForm: IntakeFormState
  onEditIntakeField?: (key: IntakeChecklistRowKey) => void
  /** Phase 10: MapView's tile style follows light/dark. */
  theme: Theme
}): ReactNode {
  if (stage === 'intake') {
    return <StageIntake intake={state.intake} form={intakeForm} onEditField={onEditIntakeField} />
  }

  if (stage === 'generating') {
    return <StageGenerating elapsedMs={state.elapsedMs} phases={state.phases} />
  }

  if (stage === 'hotels') {
    return (
      <StageHotels
        state={state}
        hotelOptions={hotelOptions}
        selectedIndex={selectedHotelIndex}
        onSelectHotel={onSelectHotel}
        onConfirmHotel={onConfirmHotel}
        focusMode={focusMode}
        theme={theme}
      />
    )
  }

  return <StageWorkspace state={state} focusMode={focusMode} onSend={onSend} theme={theme} />
}
