import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPaymentStatus } from './api/payment-client'
import { deleteSession } from './api/session-client'
import { useAuth } from './auth/auth-context'
import { consumeOAuthRedirectError, isIdentityAlreadyLinkedError } from './auth/oauth-redirect-error'
import { translateAuthError } from './auth/translate-auth-error'
import { useChatSession } from './hooks/use-chat-session'
import { useIntakeForm } from './hooks/use-intake-form'
import { usePanelResize } from './hooks/use-panel-resize'
import { useRoomHold } from './hooks/use-room-hold'
import { useSessionHistory } from './hooks/use-session-history'
import { deriveStageView, type StageView } from './lib/derive-stage'
import { isFieldFilled } from './lib/next-intake-field'
import { consumeVnpayReturn } from './lib/vnpay-return'
import type { HotelOption } from './types'
import AppShell from './components/app-shell'
import AuthPanel from './auth/auth-panel'
import BookingModal from './components/booking-modal'
import ConfirmDialog from './components/confirm-dialog'
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
  // True for the brief window between "this Google identity already belongs
  // to a real, pre-existing account" being detected and the resulting
  // retryGoogleSignIn() redirect actually navigating the browser away —
  // every RETURNING Google user hits this path (their identity is always
  // already linked to their own account by the time they come back on a
  // fresh anonymous session), so it's the common case, not an edge case.
  // Without this flag, PlannerApp/AppShell render normally in that window —
  // a guest's empty history flashes on screen for a moment before the
  // second redirect fires — which is exactly the "results flash empty,
  // then reload again with the real history" you saw. Showing BootSplash
  // instead keeps that window looking like ordinary loading, not a broken
  // flash of the wrong account's (empty) state. The second redirect itself
  // is unavoidable — Supabase has no way to "just sign in" without a fresh
  // OAuth round-trip once the link attempt has already failed.
  const [retryingGoogleSignIn, setRetryingGoogleSignIn] = useState(false)

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
      setRetryingGoogleSignIn(true)
      retryGoogleSignIn().then(({ error }) => {
        // Success navigates the browser away — nothing left to do here, and
        // retryingGoogleSignIn never needs to go false in that case.
        if (!error) return
        setRetryingGoogleSignIn(false)
        setAuthPanelError(translateAuthError(error, t))
        setAuthPanelOpen(true)
      })
      return
    }
    setAuthPanelError(translateAuthError(oauthError, t))
    setAuthPanelOpen(true)
  }, [retryGoogleSignIn, t])

  if (auth.status === 'loading' || retryingGoogleSignIn) {
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
  const auth = useAuth()
  const { t } = useTranslation()
  const { state, send, selectHotel: selectHotelDirect, startNew, restore, changeHotel } = useChatSession()
  const {
    form: intakeForm,
    setForm: setIntakeForm,
    togglePreference: toggleIntakePreference,
    resetForm: resetIntakeForm,
    editingField: editingIntakeField,
    setEditingField: setEditingIntakeField,
    serverAskedField,
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

  // Real room hold (use-room-hold.ts) — owned here (not lower in the tree)
  // because it must survive across the hotels/workspace stage swap AND be
  // reachable from BookingModal, which is mounted as a sibling of AppShell
  // for the same "escape any backdrop-filter ancestor" reason
  // profile-password-modal.tsx documents for its own portal.
  const roomHold = useRoomHold()
  const [bookingModalOpen, setBookingModalOpen] = useState(false)
  const heldHotel =
    retainedHotelOptions.find((h) => h.id === roomHold.heldHotelId) ?? null
  const bookingHotelName = heldHotel?.name ?? state.tripPlan?.hotel?.name ?? ''
  const bookingHotelArea = heldHotel?.area_name ?? null

  // Runs once on boot: the guest may have just been bounced back from
  // VNPay's hosted payment page (plan 260818-vnpay-payment-and-email-
  // confirmation). consumeVnpayReturn() only tells us THAT — never the
  // outcome, which VNPay's redirect query params can't be trusted for (see
  // vnpay-return.ts). The real verdict is GET /payments/{id}, backed by the
  // IPN webhook the backend already processed (or is about to — it can
  // land a beat after the browser's own redirect, hence the short poll
  // rather than a single check). roomHold.paymentId is read from
  // sessionStorage, not the URL — it was stashed there by booking-modal.tsx
  // right before the redirect away (use-room-hold.ts's setPendingPayment).
  useEffect(() => {
    if (!consumeVnpayReturn()) return
    const paymentId = roomHold.paymentId
    if (!paymentId) return
    let cancelled = false
    const guestRef = roomHold.guestRef

    async function pollUntilSettled() {
      const maxAttempts = 10
      const delayMs = 2000
      for (let attempt = 0; attempt < maxAttempts && !cancelled; attempt++) {
        try {
          const payment = await getPaymentStatus(paymentId!, guestRef)
          if (payment.status === 'PAID') {
            roomHold.markBooked()
            setBookingModalOpen(true)
            return
          }
          if (payment.status === 'FAILED' || payment.status === 'CANCELLED') {
            // Hold is untouched by a failed payment (see use-room-hold.ts) —
            // reopening the modal just lands back on the Payment step so
            // the guest can try again.
            setBookingModalOpen(true)
            return
          }
        } catch {
          // Transient network hiccup — worth another attempt rather than
          // giving up on the guest's very first request back into the app.
        }
        await new Promise((resolve) => setTimeout(resolve, delayMs))
      }
      // IPN still hasn't landed after ~20s — open the modal anyway rather
      // than leave the guest on a blank page; GET /payments/{id} is cheap
      // to check again from there once they notice nothing happened.
      if (!cancelled) setBookingModalOpen(true)
    }

    void pollUntilSettled()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  // "Đổi khách sạn" (step-navigator.tsx, only enabled post-itinerary) used to
  // call changeHotel() directly with zero regard for roomHold — a live HELD
  // hold just kept counting down in the background while the guest browsed a
  // brand new hotel list, fully blocked from acting on any of it by
  // hotel-detail-panel.tsx's heldElsewhere check (plan
  // 260818-vnpay-payment-and-email-confirmation's addendum). Intercepted
  // here, the one place that already owns both changeHotel and roomHold,
  // rather than threading a new prop down through AppShell/step-navigator.tsx.
  const [confirmChangeHotelOpen, setConfirmChangeHotelOpen] = useState(false)
  function handleChangeHotelClick() {
    if (roomHold.status === 'HELD') {
      setConfirmChangeHotelOpen(true)
      return
    }
    changeHotel()
  }

  const { sessions, removeLocal, refresh } = useSessionHistory(state.sessionId, state.pending)

  // restoreSession() has no in-flight signal of its own (session-client.ts's
  // fetch just resolves or doesn't) — this is purely a UI-visible "which row
  // is loading" flag so ConversationList can show a spinner instead of
  // looking unresponsive for however long that GET takes.
  const [restoringSessionId, setRestoringSessionId] = useState<string | null>(null)

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

  // Resets the active chat session + history rail whenever the signed-in
  // identity actually changes — sign-out (real user -> a new anonymous
  // user), or signing into a different pre-existing account (email/password
  // or Google). Reuses handleNewTrip() verbatim rather than a bespoke reset:
  // same "fresh session + cleared intake + refetched history" outcome the
  // "+ Chuyến đi mới" button already produces.
  //
  // Deliberately does NOT fire on the very first render (guarded by
  // identityInitializedRef) — that's just normal boot, not a switch — and
  // deliberately does NOT fire when an anonymous session is upgraded in
  // place (register / link Google from a guest session): that keeps the
  // same auth.users id throughout (see auth-context.tsx's module doc
  // comment), so this effect never sees a change and the guest's chat
  // history correctly carries over instead of getting wiped.
  //
  // Also covers the Google OAuth redirect case where the first render after
  // landing back can still be transiently un-settled (the code/token
  // exchange finishing a beat after mount): whenever auth.user?.id lands on
  // its real final value, this fires and re-syncs — no manual refresh
  // needed, regardless of exactly how long that settling takes.
  //
  // Skips a null auth.user?.id entirely — signOut() (auth-context.tsx) goes
  // real-user -> null -> new-anonymous-user, awaiting supabase.auth.signOut()
  // and supabase.auth.signInAnonymously() in sequence; auth.user is
  // genuinely absent for that brief real window, not just an intermediate
  // render. Firing handleNewTrip() (and therefore a session-creating fetch)
  // right then sends it with no Authorization header — AUTH_REQUIRED=true
  // in this project's backend .env, so that request gets a real 401, which
  // session-expired-bus.ts reads as "your login died", surfacing the
  // "Phiên làm việc đã hết hạn" modal on every sign-out. Waiting for the
  // *next* non-null id (the new anonymous session) instead means this only
  // ever fires once auth-headers.ts has a real token to attach, and still
  // catches the net change (old real id -> new anonymous id) correctly.
  const identityInitializedRef = useRef(false)
  const previousUserIdRef = useRef<string | null>(null)
  // Ref-to-latest-closure rather than a dep-array entry: handleNewTrip is
  // recreated every render (it closes over resetIntakeForm, itself
  // unmemoized in use-intake-form.ts), so putting it directly in the effect
  // below would re-run on every render instead of only when the identity
  // actually changes — same "cache without an Effect" ref pattern already
  // used in use-session-history.ts's optimisticRowCreatedAtRef.
  const handleNewTripRef = useRef(handleNewTrip)
  handleNewTripRef.current = handleNewTrip
  useEffect(() => {
    const currentUserId = auth.user?.id ?? null
    if (!identityInitializedRef.current) {
      identityInitializedRef.current = true
      previousUserIdRef.current = currentUserId
      return
    }
    if (currentUserId === null) return
    if (previousUserIdRef.current === currentUserId) return
    previousUserIdRef.current = currentUserId
    handleNewTripRef.current()
  }, [auth.user?.id])

  async function handlePickSession(sessionId: string) {
    if (state.pending || restoringSessionId || sessionId === state.sessionId) return
    setRestoringSessionId(sessionId)
    try {
      const restored = await restore(sessionId)
      if (restored) resetIntakeForm()
    } finally {
      setRestoringSessionId(null)
    }
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
    <>
      <AppShell
        state={state}
        onSend={handleSend}
        onChangeHotel={handleChangeHotelClick}
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
        serverAskedField={serverAskedField}
        sessions={sessions}
        activeSessionId={state.sessionId}
        onPickSession={handlePickSession}
        onDeleteSession={handleDeleteSession}
        turnPending={state.pending}
        restoringSessionId={restoringSessionId}
        onOpenAuthPanel={onOpenAuthPanel}
        roomHold={roomHold}
        onOpenBooking={() => setBookingModalOpen(true)}
      />
      <BookingModal
        open={bookingModalOpen}
        onClose={() => setBookingModalOpen(false)}
        roomHold={roomHold}
        hotelName={bookingHotelName}
        hotelArea={bookingHotelArea}
        checkInDate={state.intake?.start_date ?? null}
        checkOutDate={state.intake?.end_date ?? null}
        guestsLabel={state.intake?.people ?? null}
      />
      <ConfirmDialog
        open={confirmChangeHotelOpen}
        title={t('holdChangeHotelConfirmTitle')}
        message={t('holdChangeHotelConfirmMessage', {
          minutes: Math.max(1, Math.ceil(roomHold.holdLeftMs / 60_000)),
        })}
        confirmLabel={t('holdChangeHotelConfirmAction')}
        cancelLabel={t('holdChangeHotelConfirmCancel')}
        destructive
        onConfirm={() => {
          setConfirmChangeHotelOpen(false)
          void roomHold.releaseHold().then(changeHotel)
        }}
        onCancel={() => setConfirmChangeHotelOpen(false)}
      />
    </>
  )
}
