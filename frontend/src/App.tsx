import { useEffect, useState } from 'react'
import { deleteSession } from './api/session-client'
import { useChatSession } from './hooks/use-chat-session'
import { useIntakeForm } from './hooks/use-intake-form'
import { usePanelResize } from './hooks/use-panel-resize'
import { useSessionHistory } from './hooks/use-session-history'
import { deriveStageView, type StageView } from './lib/derive-stage'
import type { HotelOption } from './types'
import AppShell from './components/app-shell'

/**
 * App — thin composition layer. Owns session/panel-width state and derives
 * the stage view; all layout and shell mechanics live in AppShell so future
 * phases (6-10) only fill in the areas it creates, never touching this file
 * or AppShell's structure again.
 */
export default function App() {
  const { state, send, selectHotel: selectHotelDirect, startNew, restore, changeHotel } = useChatSession()
  const {
    form: intakeForm,
    setForm: setIntakeForm,
    togglePreference: toggleIntakePreference,
    resetForm: resetIntakeForm,
    editingField: editingIntakeField,
    setEditingField: setEditingIntakeField,
  } = useIntakeForm(state.intake)
  const [chatWidth, setChatWidth] = useState(380)
  const chatResize = usePanelResize(chatWidth, setChatWidth, { min: 300, max: 560 })
  const stage = deriveStageView(state)

  // StepNavigator can jump to a step whose data is already sitting in `state`
  // (e.g. hopping back to "Thông tin" while hotel options are still loaded)
  // as a pure client-side view swap — no chat turn. `viewOverride` holds that
  // choice; it's cleared whenever the real derived stage moves (a genuine
  // backend turn happened), so the view always snaps back to following the
  // live conversation once one does.
  const [viewOverride, setViewOverride] = useState<StageView | null>(null)
  useEffect(() => {
    setViewOverride(null)
  }, [stage])
  const displayStage = viewOverride ?? stage
  const [hotelOptionsBySession, setHotelOptionsBySession] = useState<Record<string, HotelOption[]>>({})
  const [selectedHotelIndexBySession, setSelectedHotelIndexBySession] = useState<Record<string, number | null>>({})
  const retainedHotelOptions = state.sessionId ? (hotelOptionsBySession[state.sessionId] ?? []) : []
  const selectedHotelIndex = state.sessionId ? (selectedHotelIndexBySession[state.sessionId] ?? null) : null

  useEffect(() => {
    if (!state.sessionId || state.hotelOptions.length === 0) return
    setHotelOptionsBySession((current) => ({ ...current, [state.sessionId!]: state.hotelOptions }))
    setSelectedHotelIndexBySession((current) => ({ ...current, [state.sessionId!]: null }))
  }, [state.sessionId, state.hotelOptions])

  function selectHotel(index: number) {
    if (!state.sessionId) return
    setSelectedHotelIndexBySession((current) => ({ ...current, [state.sessionId!]: index }))
  }

  function handleSend(text: string) {
    // Confirmation starts a real backend turn, so it must release the local
    // phase override and resume the server-derived flow from that point.
    setViewOverride(null)
    send(text)
  }

  function handleHotelSelection(hotel: HotelOption) {
    if (!hotel.id) return
    setViewOverride(null)
    selectHotelDirect(hotel.id, `Chọn khách sạn ${hotel.name}`)
  }

  const { sessions, removeLocal, refresh } = useSessionHistory(state.sessionId, state.pending)

  // No confirm() (design has none — a fresh trip destroys nothing now that
  // startNew() doesn't DELETE the old session). POST /chat/session now
  // persists immediately (routes.py's create_session), so refresh() here
  // pulls the new draft into the rail right away instead of waiting for the
  // next pending-edge refetch — otherwise several "+ Chuyến đi mới" clicks in
  // a row would only ever show the one optimistic row for whichever session
  // is currently active.
  async function handleNewTrip() {
    await startNew()
    resetIntakeForm()
    refresh()
  }

  async function handlePickSession(sessionId: string) {
    if (state.pending || sessionId === state.sessionId) return
    const restored = await restore(sessionId)
    if (restored) resetIntakeForm()
  }

  // deleteConvo semantics (V-OTA Planner.dc.html): closing the open
  // conversation moves to the next one left in the list, or a fresh trip
  // when none remain. Local list edit happens before the DELETE call —
  // deleteSession() is best-effort and never throws. If the fallback
  // restore() itself fails (that session is gone too), startNew() always
  // lands on a real session instead of leaving state pointed at nothing.
  async function handleDeleteSession(sessionId: string) {
    const wasActive = sessionId === state.sessionId
    const remaining = (sessions ?? []).filter((s) => s.session_id !== sessionId)
    removeLocal(sessionId)
    await deleteSession(sessionId)
    if (!wasActive) {
      refresh()
      return
    }
    const restored = remaining.length > 0 && (await restore(remaining[0].session_id))
    if (!restored) await startNew()
    resetIntakeForm()
    refresh()
  }

  return (
    <AppShell
      state={state}
      onSend={handleSend}
      onChangeHotel={changeHotel}
      onNewTrip={handleNewTrip}
      stage={displayStage}
      onViewStage={setViewOverride}
      hotelOptions={retainedHotelOptions}
      selectedHotelIndex={selectedHotelIndex}
      onSelectHotel={selectHotel}
      onConfirmHotel={handleHotelSelection}
      chatWidth={chatWidth}
      onChatResizeStart={chatResize}
      intakeForm={intakeForm}
      setIntakeForm={setIntakeForm}
      toggleIntakePreference={toggleIntakePreference}
      editingIntakeField={editingIntakeField}
      onEditIntakeField={setEditingIntakeField}
      onDoneEditingIntakeField={() => setEditingIntakeField(null)}
      sessions={sessions}
      activeSessionId={state.sessionId}
      onPickSession={handlePickSession}
      onDeleteSession={handleDeleteSession}
      turnPending={state.pending}
    />
  )
}
