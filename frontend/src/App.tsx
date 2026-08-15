import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { deleteSession } from './api/session-client'
import { useAuth } from './auth/auth-context'
import { consumeOAuthRedirectError, isIdentityAlreadyLinkedError } from './auth/oauth-redirect-error'
import { translateAuthError } from './auth/translate-auth-error'
import { useChatSession } from './hooks/use-chat-session'
import { useIntakeForm } from './hooks/use-intake-form'
import { usePanelResize } from './hooks/use-panel-resize'
import { useSessionHistory } from './hooks/use-session-history'
import { deriveStageView, type StageView } from './lib/derive-stage'
import { isFieldFilled } from './lib/next-intake-field'
import type { HotelOption } from './types'
import AppShell from './components/app-shell'
import AuthPanel from './auth/auth-panel'
import SessionExpiredModal from './components/session-expired-modal'
import BootSplash from './components/boot-splash'

/**
 * App — the auth boot gate (plan 260814-supabase-auth-and-per-user-history).
 * Every visitor gets a real Supabase session (anonymous or permanent) before
 * anything below this line mounts: PlannerApp — and therefore
 * use-chat-session.ts's own bootstrap effect, and every api/*-client.ts call
 * it triggers — is not created as a component instance at all until
 * `auth.status === 'ready'`, so no request ever goes out with no
 * Authorization header; PlannerApp below is the original App component,
 * verbatim, renamed. The other auth-related piece living here is the
 * consumeOAuthRedirectError() effect below — the one place in the boot
 * sequence positioned to catch a Google redirect landing back with an
 * error before any other component has mounted.
 */
export default function App() {
  const auth = useAuth()
  const { retryGoogleSignIn } = auth
  const { t } = useTranslation()
  const [authPanelOpen, setAuthPanelOpen] = useState(false)
  const [authPanelError, setAuthPanelError] = useState('')

  // Runs once on mount, independent of auth.status: a failed OAuth link
  // shows up as error params on the very first render after Google
  // redirects back, not as something signInWithGoogle()'s own await ever
  // sees — see oauth-redirect-error.ts. "This Google email already belongs
  // to a different account" is not shown as an error here — from the
  // visitor's side, clicking "Continue with Google" for an account that
  // already exists should just sign them in, so this silently retries as a
  // plain sign-in instead (auth-context.tsx's retryGoogleSignIn). Any other
  // OAuth failure still surfaces through AuthPanel as before.
  useEffect(() => {
    const oauthError = consumeOAuthRedirectError()
    if (!oauthError) return
    if (isIdentityAlreadyLinkedError(oauthError)) {
      retryGoogleSignIn().then(({ error }) => {
        if (!error) return
        setAuthPanelError(translateAuthError(error, t))
        setAuthPanelOpen(true)
      })
      return
    }
    setAuthPanelError(translateAuthError(oauthError, t))
    setAuthPanelOpen(true)
  }, [retryGoogleSignIn, t])

  if (auth.status === 'loading') {
    return <BootSplash />
  }

  return (
    <>
      <PlannerApp onOpenAuthPanel={() => setAuthPanelOpen(true)} />
      <AuthPanel
        open={authPanelOpen}
        initialError={authPanelError}
        onClose={() => {
          setAuthPanelOpen(false)
          setAuthPanelError('')
        }}
      />
      <SessionExpiredModal
        onSignInAgain={() => {
          auth.dismissSessionExpired()
          setAuthPanelOpen(true)
        }}
      />
    </>
  )
}

/**
 * PlannerApp — thin composition layer. Owns session/panel-width state and
 * derives the stage view; all layout and shell mechanics live in AppShell so
 * future phases (6-10) only fill in the areas it creates, never touching
 * this file or AppShell's structure again.
 */
function PlannerApp({ onOpenAuthPanel }: { onOpenAuthPanel: () => void }) {
  const { state, send, selectHotel: selectHotelDirect, startNew, restore, changeHotel } = useChatSession()
  const {
    form: intakeForm,
    setForm: setIntakeForm,
    togglePreference: toggleIntakePreference,
    resetForm: resetIntakeForm,
    editingField: editingIntakeField,
    setEditingField: setEditingIntakeField,
  } = useIntakeForm(state.intake)
  const [chatWidth, setChatWidth] = useState(352)
  const chatResize = usePanelResize(chatWidth, setChatWidth, { min: 300, max: 560 })
  // The three fields the backend actually gates on (next-intake-field.ts). All
  // answered => a pending turn is the hotel search, not one more intake reply,
  // so the right-hand panel may switch to the generating view.
  const intakeReady =
    isFieldFilled(intakeForm, 'destination') &&
    isFieldFilled(intakeForm, 'people') &&
    isFieldFilled(intakeForm, 'dates')
  const stage = deriveStageView(state, intakeReady)

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
      onOpenAuthPanel={onOpenAuthPanel}
    />
  )
}
