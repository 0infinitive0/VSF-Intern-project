import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPaymentStatus } from './api/payment-client'
import { deleteSession } from './api/session-client'
import { finalizeTrip } from './api/trip-client'
import { useAuth } from './auth/auth-context'
import { consumeOAuthRedirectError, isIdentityAlreadyLinkedError } from './auth/oauth-redirect-error'
import { translateAuthError } from './auth/translate-auth-error'
import { useChatSession } from './hooks/use-chat-session'
import { EMPTY_INTAKE_FORM, mergeIntakeIntoForm, useIntakeForm } from './hooks/use-intake-form'
import { usePanelResize } from './hooks/use-panel-resize'
import { shouldReleaseHoldForDeletedSession, useRoomHold } from './hooks/use-room-hold'
import { useSessionHistory } from './hooks/use-session-history'
import { composeIntakeMessage } from './lib/compose-intake-message'
import { deriveStageView, type StageView } from './lib/derive-stage'
import { isFieldFilled } from './lib/next-intake-field'
import { consumeVnpayReturn, isVnpayReturnPending } from './lib/vnpay-return'
import type { HotelFilterData, HotelOption } from './types'
import type { TabKey } from './components/stage-workspace'
import AppShell from './components/app-shell'
import AuthPanel from './auth/auth-panel'
import BookingModal from './components/booking-modal'
import BookingReceiptModal from './components/booking-receipt-modal'
import ConfirmDialog from './components/confirm-dialog'
import SessionExpiredModal from './components/session-expired-modal'
import BootSplash from './components/boot-splash'

/** Payment-status poll after a VNPay return (see the poll effect below):
 * `VNPAY_POLL_MAX_ATTEMPTS` checks, `VNPAY_POLL_DELAY_MS` apart. The
 * splash's own safety-ceiling timeout is derived from these same two
 * numbers plus a network-latency buffer, instead of its own independent
 * constant -- it used to be a hardcoded 15s against this poll's ~20s+
 * worst case, so the splash could disappear (revealing the ordinary app --
 * reads as "landed back on the homepage, nothing happened") several
 * seconds before the poll's real outcome opened the result modal. */
const VNPAY_POLL_MAX_ATTEMPTS = 10
const VNPAY_POLL_DELAY_MS = 2000
const VNPAY_POLL_SAFETY_CEILING_MS =
  VNPAY_POLL_MAX_ATTEMPTS * VNPAY_POLL_DELAY_MS + 8_000

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
  const [hotelOptionsBySession, setHotelOptionsBySession] = useState<Record<string, HotelOption[]>>({})
  // Retained alongside hotelOptions, same lifetime, same trigger (bug fix):
  // a turn that doesn't re-run the hotel search (selecting a hotel, building
  // the itinerary, a qa_node answer) comes back with an empty
  // hotel_amenities catalog even though the retained hotel cards above are
  // still showing the PREVIOUS search's hotels — without this, those cards'
  // amenity tags fall back to raw canonical ids (e.g. "swimming_pool")
  // because displayAmenityLabels has nothing to resolve them against.
  const [hotelFilterDataBySession, setHotelFilterDataBySession] = useState<Record<string, HotelFilterData>>({})
  const [selectedHotelIndexBySession, setSelectedHotelIndexBySession] = useState<Record<string, number | null>>({})
  const [workspaceTabBySession, setWorkspaceTabBySession] = useState<Record<string, TabKey>>({})
  const retainedHotelOptions = state.sessionId ? (hotelOptionsBySession[state.sessionId] ?? []) : []
  const retainedHotelFilterData =
    (state.sessionId ? hotelFilterDataBySession[state.sessionId] : undefined) ?? state.hotelFilterData

  // Declared above `stage` on purpose: the retained list is an INPUT to stage
  // derivation, not just a render prop — a turn that returns no hotel_options
  // (a qa_node answer, a hotel selection) must not read as "back to intake".
  const stage = deriveStageView(state, intakeReady, retainedHotelOptions.length > 0)

  // StepNavigator can jump to a step whose data is already sitting in `state`
  // (e.g. hopping back to "Thông tin" while hotel options are still loaded)
  // as a pure client-side view swap — no chat turn. `viewOverride` holds that
  // choice, per session, so hopping between chats doesn't lose it. It's
  // cleared whenever the real derived stage moves FOR THE SESSION CURRENTLY
  // BEING VIEWED (a genuine backend turn happened), so the view always snaps
  // back to following the live conversation once one does.
  const [viewOverrideBySession, setViewOverrideBySession] = useState<Record<string, StageView | null>>({})
  const viewOverride = state.sessionId ? (viewOverrideBySession[state.sessionId] ?? null) : null
  const handleSetViewOverride = (v: StageView | null) => {
    if (state.sessionId) {
      setViewOverrideBySession((prev) => ({ ...prev, [state.sessionId!]: v }))
    }
  }
  // `stage` also changes when the guest SWITCHES to a different session
  // (each session derives its own stage from its own state) — that must NOT
  // clear the just-restored override for the newly active session, or a
  // step manually picked earlier for that session is forgotten every time
  // its chat is reopened. Only clear when `stage` changed while the active
  // session itself stayed the same, i.e. a real turn happened for the
  // session currently on screen.
  const stageClearSessionRef = useRef<string | null>(null)
  useEffect(() => {
    const sameSessionAsLastCheck = stageClearSessionRef.current === state.sessionId
    stageClearSessionRef.current = state.sessionId
    if (sameSessionAsLastCheck && state.sessionId) {
      setViewOverrideBySession((prev) => ({ ...prev, [state.sessionId!]: null }))
    }
  }, [stage, state.sessionId])
  const displayStage = viewOverride ?? stage

  const activeWorkspaceTab = state.sessionId ? (workspaceTabBySession[state.sessionId] ?? 'overview') : 'overview'
  const handleSelectWorkspaceTab = (tab: TabKey) => {
    if (state.sessionId) {
      setWorkspaceTabBySession((prev) => ({ ...prev, [state.sessionId!]: tab }))
    }
  }

  // Real room hold (use-room-hold.ts) — owned here (not lower in the tree)
  // because it must survive across the hotels/workspace stage swap AND be
  // reachable from BookingModal, which is mounted as a sibling of AppShell
  // for the same "escape any backdrop-filter ancestor" reason
  // profile-password-modal.tsx documents for its own portal.
  const roomHold = useRoomHold(state.sessionId)
  const explicitSelectedHotelIndex = state.sessionId ? (selectedHotelIndexBySession[state.sessionId] ?? null) : null
  const selectedHotelIndex = useMemo(() => {
    if (explicitSelectedHotelIndex != null) return explicitSelectedHotelIndex

    if (state.tripPlan?.hotel) {
      const planHotel = state.tripPlan.hotel
      const match = retainedHotelOptions.find(
        (h) =>
          (planHotel.id && h.id === planHotel.id) ||
          (planHotel.name && h.name && h.name.toLowerCase().trim() === planHotel.name.toLowerCase().trim()),
      )
      if (match != null && match.index != null) return match.index
    }

    if (roomHold.heldHotelId) {
      const match = retainedHotelOptions.find((h) => h.id === roomHold.heldHotelId)
      if (match != null && match.index != null) return match.index
    }

    return null
  }, [explicitSelectedHotelIndex, state.tripPlan?.hotel, roomHold.heldHotelId, retainedHotelOptions])

  const [bookingModalOpen, setBookingModalOpen] = useState(false)
  // Separate from bookingModalOpen: opened via hold-banner.tsx's fallback
  // "Xem đặt phòng" (the sessionBookedFromBackend branch, below) for a
  // session whose booking is confirmed but no longer owns roomHold —
  // booking-receipt-modal.tsx fetches its own data by session_id rather
  // than reading roomHold, so it needs no data threaded in here.
  const [receiptModalOpen, setReceiptModalOpen] = useState(false)
  // roomHold is a single GLOBAL hold, not scoped per chat session (see
  // use-room-hold.ts's module doc comment) — this is what keeps every
  // hold-facing UI honest about whether the CURRENTLY ACTIVE session is
  // actually the one that owns it. Without this check, switching the live
  // hold to a different hotel from a different session (hotel-detail-
  // panel.tsx's heldElsewhere -> switchHold flow) would leave the
  // now-unrelated session's workspace still showing a countdown and an
  // enabled "Đặt phòng" button for a hold it no longer owns. Same
  // heldSessionId comparison handleDeleteSession already makes below (via
  // shouldReleaseHoldForDeletedSession) — this is the display-side twin.
  const holdBelongsToSession = roomHold.heldSessionId === state.sessionId
  const heldHotel =
    retainedHotelOptions.find((h) => h.id === roomHold.heldHotelId) ?? null
  const bookingHotelName = heldHotel?.name ?? state.tripPlan?.hotel?.name ?? ''
  const bookingHotelArea = heldHotel?.area_name ?? null

  // Ref-to-latest-refresh, same "cache without an Effect" pattern as
  // handleNewTripRef below: the consumeVnpayReturn effect right after this
  // (deliberately [] deps, fires once on boot) is declared BEFORE
  // useSessionHistory() below provides the real `refresh`, so it can't
  // close over that value directly. Assigned right after useSessionHistory
  // is called.
  const refreshRef = useRef<() => void>(() => {})

  // True only when the URL says the guest just landed back from VNPay
  // (lazy init: a plain, non-consuming read of the same marker
  // consumeVnpayReturn() below strips — see isVnpayReturnPending's own doc
  // comment). Gates the render below: while true, PlannerApp shows a
  // processing splash instead of the real UI, so the guest never sees the
  // brief "back to intake" flash a full page reload causes here (state.
  // sessionId/tripPlan both start out empty on every mount until
  // use-chat-session.ts's async bootstrap resolves — see sessionResolved's
  // own doc comment on BookingModal for the same underlying gap).
  const [paymentReturnPending, setPaymentReturnPending] = useState(isVnpayReturnPending)
  // Flips true once the payment-status poll below reaches ANY terminal
  // outcome (paid, failed/cancelled, or its own ~20s timeout — see
  // pollUntilSettled). Session bootstrap resolving alone isn't enough to
  // reveal the app: the guest came back specifically to see the payment
  // outcome, so the splash should outlast whichever of the two is slower.
  const [paymentPollDone, setPaymentPollDone] = useState(false)
  // Set on a FAILED/CANCELLED verdict, OR when the poll below exhausts its
  // ~20s budget with the payment still PENDING ('pending' — VNPay's IPN
  // webhook hasn't reached the backend yet, e.g. a slow/misconfigured
  // callback URL rather than any real decline). Read once by booking-
  // modal.tsx to land on the Payment step (not its default Guest step —
  // this IS a fresh mount, the full-page VNPay redirect wiped every local
  // state there) with a visible notice, instead of silently reopening on
  // step 1 with no explanation at all.
  const [paymentReturnOutcome, setPaymentReturnOutcome] = useState<'failed' | 'cancelled' | 'pending' | null>(null)

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
    if (!paymentId) {
      setPaymentPollDone(true)
      return
    }
    let cancelled = false
    const guestRef = roomHold.guestRef

    async function pollUntilSettled() {
      const maxAttempts = VNPAY_POLL_MAX_ATTEMPTS
      const delayMs = VNPAY_POLL_DELAY_MS
      for (let attempt = 0; attempt < maxAttempts && !cancelled; attempt++) {
        try {
          const payment = await getPaymentStatus(paymentId!, guestRef)
          if (payment.status === 'PAID') {
            roomHold.markBooked()
            setBookingModalOpen(true)
            // sessionBookedFromBackend's source (the sessions list) only
            // ever refetches on mount or when a chat turn finishes — a
            // payment completing is neither, so without this the session
            // being paid right now wouldn't read back as "paid" from a
            // DIFFERENT session's workspace until some unrelated refetch
            // happened to occur later.
            refreshRef.current()
            setPaymentPollDone(true)
            return
          }
          if (payment.status === 'FAILED' || payment.status === 'CANCELLED') {
            // Hold is untouched by a failed payment (see use-room-hold.ts) —
            // reopening the modal lands back on the Payment step (via
            // paymentReturnOutcome below) so the guest can try again.
            setPaymentReturnOutcome(payment.status === 'CANCELLED' ? 'cancelled' : 'failed')
            setBookingModalOpen(true)
            setPaymentPollDone(true)
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
      // to check again from there once they notice nothing happened. Says
      // so explicitly (paymentReturnOutcome) instead of silently reopening
      // on the Payment step with no explanation, same as a real FAILED/
      // CANCELLED verdict gets.
      if (!cancelled) {
        setPaymentReturnOutcome('pending')
        setBookingModalOpen(true)
        setPaymentPollDone(true)
      }
    }

    void pollUntilSettled()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Reveals the app once BOTH the session has actually resolved
  // (state.sessionId past its initial null — see sessionResolved's own doc
  // comment on BookingModal for why every mount starts there) AND the
  // payment poll above reached a terminal outcome — whichever is slower
  // gates the other.
  useEffect(() => {
    if (!paymentReturnPending) return
    if (paymentPollDone && state.sessionId != null) setPaymentReturnPending(false)
  }, [paymentReturnPending, paymentPollDone, state.sessionId])

  // Safety ceiling: the payment poll above always resolves paymentPollDone
  // within VNPAY_POLL_SAFETY_CEILING_MS no matter what, but session
  // bootstrap has no such ceiling of its own — this is the "never leave the
  // guest stuck" backstop if that somehow hangs, matching this same file's
  // own posture on the poll. Deliberately >= the poll's own worst-case
  // budget (see VNPAY_POLL_SAFETY_CEILING_MS's doc comment) so this timeout
  // never fires while the poll is still legitimately running.
  useEffect(() => {
    if (!paymentReturnPending) return
    const timeout = setTimeout(() => setPaymentReturnPending(false), VNPAY_POLL_SAFETY_CEILING_MS)
    return () => clearTimeout(timeout)
  }, [paymentReturnPending])

  useEffect(() => {
    if (!state.sessionId || state.hotelOptions.length === 0) return
    setHotelOptionsBySession((current) => ({ ...current, [state.sessionId!]: state.hotelOptions }))
    setHotelFilterDataBySession((current) => ({ ...current, [state.sessionId!]: state.hotelFilterData }))
    setSelectedHotelIndexBySession((current) => ({ ...current, [state.sessionId!]: null }))
  }, [state.sessionId, state.hotelOptions, state.hotelFilterData])

  function selectHotel(index: number) {
    if (!state.sessionId) return
    setSelectedHotelIndexBySession((current) => ({ ...current, [state.sessionId!]: index }))
  }

  function handleSend(text: string) {
    // Confirmation starts a real backend turn, so it must release the local
    // phase override and resume the server-derived flow from that point.
    handleSetViewOverride(null)
    send(text)
  }

  function handleHotelSelection(hotel: HotelOption) {
    if (!hotel.id) return
    handleSetViewOverride(null)
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
    // Defensive — not the primary guard (step-navigator.tsx's own
    // canChangeHotel already makes this effectively unreachable once a
    // session has ever had a hotel list, since its pill prefers
    // onViewStage('hotels') over calling this at all), but this is the
    // one remaining call site that reaches changeHotel() directly, and
    // the hotel_node backend guard (plan 260819-lock-hotel-after-payment)
    // means calling it on a paid session would just come back with a
    // decline reply anyway — no reason to ever start that turn.
    if (sessionBookedFromBackend) return
    if (roomHold.status === 'HELD') {
      setConfirmChangeHotelOpen(true)
      return
    }
    changeHotel()
  }

  const { sessions, removeLocal, refresh } = useSessionHistory(state.sessionId, state.pending)
  // Backend-sourced twin of holdBelongsToSession: once a booking is paid,
  // it must keep reading as "đã đặt phòng" from THIS session's own
  // workspace forever after — even once roomHold (the single global hold)
  // has moved on to a different session and holdBelongsToSession goes
  // false (known limitation from the previous fix). Sourced from the same
  // per-session status the sidebar badge already shows
  // (session-status-badge.ts/session_store.py's booking_states_for_
  // sessions), not from roomHold, so it survives roomHold being
  // overwritten. roomHold.status === 'BOOKED' (while holdBelongsToSession)
  // stays the PRIMARY signal for the session that just paid — instant, no
  // fetch lag — this is only consulted as the fallback for every other
  // session (see hold-banner.tsx).
  const sessionBookedFromBackend = sessions?.find((s) => s.session_id === state.sessionId)?.status === 'paid'
  refreshRef.current = refresh

  // ── Finalize itinerary (plan 260819-finalize-itinerary) ─────────────────
  // Confirm dialog + the actual mutation live here (not in finalize-
  // action.tsx) so the dialog can mount as a sibling of <AppShell>, escaping
  // this tree's glass-panel `backdrop-filter` ancestors — same reason
  // BookingModal/the change-hotel ConfirmDialog live here.
  const [finalizeConfirmOpen, setFinalizeConfirmOpen] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [finalizeError, setFinalizeError] = useState<string | null>(null)

  async function handleConfirmFinalize() {
    if (!state.sessionId) return
    setFinalizeConfirmOpen(false)
    setFinalizing(true)
    setFinalizeError(null)
    try {
      await finalizeTrip(state.sessionId)
      // Pulls the fresh `status: "Finalized"` trip plan + the updated
      // sidebar badge from the backend, rather than optimistically patching
      // local state — the same "re-fetch, don't guess" convention the
      // VNPay-return flow already uses (roomHold.markBooked() -> refresh()).
      await restore(state.sessionId)
      refresh()
    } catch (err) {
      setFinalizeError(err instanceof Error ? err.message : String(err))
    } finally {
      setFinalizing(false)
    }
  }

  // The composed duplicate-trip message, staged here until the brand-new
  // session from startNew() is actually ready — send() resolves its target
  // session id from THIS render's closure (use-chat-session.ts), so calling
  // it synchronously right after `await startNew()` would still address the
  // OLD session. The effect below fires once state.sessionId has genuinely
  // moved to the new one, by which point `send` closes over it correctly.
  const duplicateIntentRef = useRef<string | null>(null)

  async function handleDuplicateTrip() {
    if (!state.intake) return
    const form = mergeIntakeIntoForm(EMPTY_INTAKE_FORM, state.intake, null, null)
    duplicateIntentRef.current = composeIntakeMessage(form)
    await startNew()
    resetIntakeForm()
    refresh()
  }

  useEffect(() => {
    if (!duplicateIntentRef.current || !state.sessionId) return
    const message = duplicateIntentRef.current
    duplicateIntentRef.current = null
    void send(message)
  }, [state.sessionId, send])

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
    // Deleting the chat that created the CURRENT live hold must release it
    // too — otherwise the room stays reserved with no UI left anywhere to
    // show or release it (roomHold is a single global hold per tab; only
    // one session can ever be the one holding it — see use-room-hold.ts's
    // heldSessionId). Only HELD, never BOOKED: a paid/confirmed booking is
    // a real transaction that must survive its chat session being deleted
    // (bookings.session_id is ON DELETE SET NULL, not CASCADE, for exactly
    // this reason) — deletion is already behind conversation-list.tsx's own
    // confirm dialog, so no separate hold-specific prompt here.
    if (shouldReleaseHoldForDeletedSession(roomHold.status, roomHold.heldSessionId, sessionId)) {
      await roomHold.releaseHold()
    }
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

  // Hides the session-bootstrap flash specifically for the VNPay-return
  // case (paymentReturnPending's own doc comment above) — every hook above
  // this point still runs normally either way (roomHold's markBooked()/
  // setPendingPayment side effects must fire regardless of what's on
  // screen), only the JSX below is swapped.
  if (paymentReturnPending) {
    return <BootSplash messageKey="paymentReturnProcessing" />
  }

  return (
    <>
      <AppShell
        state={state}
        onSend={handleSend}
        onChangeHotel={handleChangeHotelClick}
        onNewTrip={handleNewTrip}
        stage={displayStage}
        onViewStage={handleSetViewOverride}
        hotelOptions={retainedHotelOptions}
        hotelFilterData={retainedHotelFilterData}
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
        holdBelongsToSession={holdBelongsToSession}
        sessionBookedFromBackend={sessionBookedFromBackend}
        onOpenBooking={() => setBookingModalOpen(true)}
        onOpenReceipt={() => setReceiptModalOpen(true)}
        finalizing={finalizing}
        finalizeError={finalizeError}
        onRequestFinalize={() => setFinalizeConfirmOpen(true)}
        onDuplicateTrip={handleDuplicateTrip}
        activeWorkspaceTab={activeWorkspaceTab}
        onSelectWorkspaceTab={handleSelectWorkspaceTab}
      />
      <BookingModal
        open={bookingModalOpen}
        onClose={() => setBookingModalOpen(false)}
        roomHold={roomHold}
        holdBelongsToSession={holdBelongsToSession}
        sessionResolved={state.sessionId != null}
        hotelName={bookingHotelName}
        hotelArea={bookingHotelArea}
        checkInDate={state.intake?.start_date ?? null}
        checkOutDate={state.intake?.end_date ?? null}
        guestsLabel={state.intake?.people ?? null}
        paymentReturnOutcome={paymentReturnOutcome}
      />
      <BookingReceiptModal
        open={receiptModalOpen}
        onClose={() => setReceiptModalOpen(false)}
        sessionId={state.sessionId}
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
      <ConfirmDialog
        open={finalizeConfirmOpen}
        title={t('finalizeConfirmTitle')}
        message={t('finalizeConfirmBody')}
        confirmLabel={t('finalizeConfirmAction')}
        cancelLabel={t('finalizeConfirmCancel')}
        onConfirm={() => void handleConfirmFinalize()}
        onCancel={() => setFinalizeConfirmOpen(false)}
      />
    </>
  )
}
