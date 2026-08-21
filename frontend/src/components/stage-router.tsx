import type { ReactNode } from 'react'
import StageGenerating from './stage-generating'
import StageHotels from './stage-hotels'
import StageIntake from './stage-intake'
import StageWorkspace from './stage-workspace'
import type { useFocusMode } from '../hooks/use-focus-mode'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import type { Theme } from '../hooks/use-theme'
import type { IntakeFormState } from '../lib/compose-intake-message'
import type { IntakeChecklistRowKey } from '../lib/intake-checklist-rows'
import type { StageView } from '../lib/derive-stage'
import type { ChatState, HotelFilterData, HotelOption } from '../types'

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
 * No `onSend` prop — the only past consumer (workspace's "Tạo lại" button)
 * was removed (user decision 260818-booking-flow); re-add it here if a
 * future stage needs to post a chat message again.
 *
 * Stage swaps keep the outer flex-1 container stable and let each stage own
 * its entrance animation (vRise), so intake → generating → hotels → workspace
 * transitions don't jump layout.
 */
import type { TabKey } from './stage-workspace'

export default function StageRouter({
  stage,
  state,
  hotelOptions,
  hasMoreHotelOptions,
  hotelsLoading,
  hotelFilterData,
  selectedHotelIndex,
  onSelectHotel,
  onConfirmHotel,
  onExpandHotelOptions,
  focusMode,
  intakeForm,
  onEditIntakeField,
  theme,
  roomHold,
  holdBelongsToSession,
  sessionBookedFromBackend,
  onOpenBooking,
  onOpenReceipt,
  finalizing,
  finalizeError,
  onRequestFinalize,
  onDuplicateTrip,
  activeWorkspaceTab,
  onSelectWorkspaceTab,
}: {
  stage: StageView
  state: ChatState
  hotelOptions: HotelOption[]
  hasMoreHotelOptions: boolean
  hotelsLoading: boolean
  hotelFilterData: HotelFilterData
  selectedHotelIndex: number | null
  onSelectHotel: (index: number) => void
  onConfirmHotel: (hotel: HotelOption) => void
  onExpandHotelOptions: () => void
  focusMode: FocusModeApi
  intakeForm: IntakeFormState
  onEditIntakeField?: (key: IntakeChecklistRowKey) => void
  /** Phase 10: MapView's tile style follows light/dark. */
  theme: Theme
  /** Real room hold (use-room-hold.ts) — hotels stage uses it for the cart +
   * "Giữ phòng" CTA, workspace stage uses it for the header hold banner. */
  roomHold: RoomHoldApi
  /** Whether roomHold's current hold was created by `state.sessionId` (App.tsx)
   * — only the workspace stage's HoldBanner needs this (see app-shell.tsx's
   * doc comment on the same prop); the hotels stage's own heldHere/
   * heldElsewhere logic already scopes correctly by hotel, not session. */
  holdBelongsToSession: boolean
  /** See app-shell.tsx's doc comment on the same prop. Also threaded into
   * the 'hotels' branch below (plan 260819-lock-hotel-after-payment): once
   * THIS session's booking is paid, HotelDetailPanel's HoldFooter must lock
   * "Giữ phòng" for every hotel in the retained list, not only the workspace
   * stage's hold banner — re-picking a hotel here would rebuild the
   * itinerary and destroy the one already paid for. */
  sessionBookedFromBackend: boolean
  onOpenBooking: () => void
  /** See app-shell.tsx's doc comment on the same prop. */
  onOpenReceipt: () => void
  /** See app-shell.tsx's doc comment on the same prop group (finalize). */
  finalizing: boolean
  finalizeError: string | null
  onRequestFinalize: () => void
  onDuplicateTrip: () => void
  activeWorkspaceTab?: TabKey
  onSelectWorkspaceTab?: (tab: TabKey) => void
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
        hasMoreHotelOptions={hasMoreHotelOptions}
        hotelsLoading={hotelsLoading}
        hotelFilterData={hotelFilterData}
        selectedIndex={selectedHotelIndex}
        onSelectHotel={onSelectHotel}
        onConfirmHotel={onConfirmHotel}
        onExpandHotelOptions={onExpandHotelOptions}
        focusMode={focusMode}
        theme={theme}
        roomHold={roomHold}
        sessionBookedFromBackend={sessionBookedFromBackend}
      />
    )
  }

  return (
    <StageWorkspace
      state={state}
      focusMode={focusMode}
      theme={theme}
      roomHold={roomHold}
      holdBelongsToSession={holdBelongsToSession}
      sessionBookedFromBackend={sessionBookedFromBackend}
      onOpenBooking={onOpenBooking}
      onOpenReceipt={onOpenReceipt}
      finalizing={finalizing}
      finalizeError={finalizeError}
      onRequestFinalize={onRequestFinalize}
      onDuplicateTrip={onDuplicateTrip}
      activeTab={activeWorkspaceTab}
      onSelectTab={onSelectWorkspaceTab}
    />
  )
}
