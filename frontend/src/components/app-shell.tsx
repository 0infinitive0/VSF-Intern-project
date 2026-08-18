import { useEffect, useState, type MouseEvent } from 'react'
import ChatPanel from './chat-panel'
import PanelResizer from './panel-resizer'
import SidebarRail from './sidebar-rail'
import StageRouter from './stage-router'
import { useFocusMode } from '../hooks/use-focus-mode'
import type { RoomHoldApi } from '../hooks/use-room-hold'
import { useTheme } from '../hooks/use-theme'
import type { IntakeFormState } from '../lib/compose-intake-message'
import type { IntakeChecklistRowKey } from '../lib/intake-checklist-rows'
import type { PreferenceKey } from '../lib/intake-options'
import type { IntakeField } from '../lib/next-intake-field'
import type { StageView } from '../lib/derive-stage'
import type { ChatState, HotelOption, SessionSummary } from '../types'

const DESKTOP_BREAKPOINT_PX = 768 // Tailwind `md`
const SIDEBAR_PUSH_BREAKPOINT_PX = 1024 // Tailwind `lg`
const SIDEBAR_COLLAPSED_PX = 68

/** Tracks viewport width so chat-panel.tsx's own fixed-pixel `width` prop
 * (out of scope to modify this phase) can be given a sane value below `md`,
 * where the desktop chat/stage overlap layout gives way to a plain stack. */
function useViewportWidth() {
  const [width, setWidth] = useState(() => (typeof window === 'undefined' ? 1280 : window.innerWidth))
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return width
}

/**
 * AppShell — sidebar rail + fixed chat + stage. This is the one place that
 * owns the focus-mode transform mechanics: chat is siblings with stage
 * (never nested inside it, never unmounted across stage or focus changes),
 * and only `transform`/`opacity`/`pointer-events` are transitioned on it —
 * never `width`/`height`, and deliberately not `filter` either (animating
 * blur-radius forces a per-frame re-raster on top of the already-blurred
 * glass surfaces, exactly the jank the phase-05 risk register warns about)
 * — to keep the blurred glass surfaces from janking.
 *
 * Mechanically: chat is `position: absolute`, so it never consumes layout
 * space from its stage sibling — stage's `padding-left` snaps instantly
 * (no `transition`) to reserve/release that space, while chat's own
 * transform slides it away on top. That's a single one-time reflow per
 * toggle (not animated), not a per-frame cost. It also means entering/
 * exiting focus is a clip reveal rather than a synchronised expand; the
 * intended "stage mở rộng sang trái" motion is meant to come from the
 * hotel/place detail panel's own mirrored entrance transition (Phase 8/9),
 * not from tweening this container's box model.
 *
 * `focusMode` (the whole use-focus-mode.ts return value) is threaded down
 * to StageRouter as one object so Phase 7-10 can call openFocus/closeFocus
 * from deeper in the stage tree without ever touching this file again.
 */
export default function AppShell({
  state,
  onSend,
  onChangeHotel,
  onNewTrip,
  stage,
  onViewStage,
  hotelOptions,
  selectedHotelIndex,
  onSelectHotel,
  onConfirmHotel,
  chatWidth,
  onChatResizeStart,
  intakeForm,
  setIntakeForm,
  toggleIntakePreference,
  editingIntakeField,
  onEditIntakeField,
  onDoneEditingIntakeField,
  serverAskedField,
  sessions,
  activeSessionId,
  onPickSession,
  onDeleteSession,
  turnPending,
  restoringSessionId,
  onOpenAuthPanel,
  roomHold,
  onOpenBooking,
}: {
  state: ChatState
  onSend: (text: string) => void
  /** Rebuilds the hotel list without a chat turn — see step-navigator.tsx. */
  onChangeHotel: () => void
  onNewTrip: () => void
  stage: StageView
  onViewStage: (stage: StageView) => void
  hotelOptions: HotelOption[]
  selectedHotelIndex: number | null
  onSelectHotel: (index: number) => void
  onConfirmHotel: (hotel: HotelOption) => void
  chatWidth: number
  onChatResizeStart: (e: MouseEvent) => void
  intakeForm: IntakeFormState
  setIntakeForm: (updater: (prev: IntakeFormState) => IntakeFormState) => void
  toggleIntakePreference: (key: PreferenceKey) => void
  editingIntakeField: IntakeField | null
  onEditIntakeField: (key: IntakeChecklistRowKey) => void
  onDoneEditingIntakeField: () => void
  /** Field the most recent real backend reply is (best-effort) about —
   * ChatPanel uses it to suppress a redundant same-field local question. */
  serverAskedField: IntakeField | null
  sessions: SessionSummary[] | null
  activeSessionId: string | null
  onPickSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
  turnPending: boolean
  /** Session id currently being fetched by restore(), or null — drives the
   * spinner ConversationList shows on that row while awaiting the response. */
  restoringSessionId: string | null
  onOpenAuthPanel: () => void
  /** Real room hold (use-room-hold.ts), owned by App.tsx and threaded through
   * to StageRouter — see its own doc comment for why. */
  roomHold: RoomHoldApi
  onOpenBooking: () => void
}) {
  const { theme, toggleTheme } = useTheme()
  const focusMode = useFocusMode()
  const { closeFocus } = focusMode
  const focused = focusMode.focus !== null

  // A stage change (e.g. picking a hotel moves hotels → generating → workspace)
  // must not carry a focus panel from the previous stage along with it — the
  // panel it pointed at (a hotel card) no longer exists in the new stage's
  // tree, which would otherwise leave chat/map permanently collapsed with no
  // way back (review finding H3). `closeFocus` is a stable useCallback ref.
  useEffect(() => {
    closeFocus()
  }, [stage, closeFocus])
  const viewportWidth = useViewportWidth()
  const isDesktop = viewportWidth >= DESKTOP_BREAKPOINT_PX
  const isLgUp = viewportWidth >= SIDEBAR_PUSH_BREAKPOINT_PX
  const effectiveChatWidth = isDesktop ? chatWidth : viewportWidth
  // +14 compensates the chat panel's own 14px left margin below (design
  // dc.html:125 `margin:14px 0 14px 14px`) so the stage's reserved gutter and
  // the resizer both line up with the panel's actual right edge.
  const chatGutter = focused ? 0 : chatWidth + 6 + 14

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => viewportWidth < SIDEBAR_PUSH_BREAKPOINT_PX)
  // Below `lg` the rail is `position: fixed` (an overlay, see sidebar-rail.tsx) and
  // contributes 0 to this row's flex layout. When collapsed it still renders as a
  // persistent 76px icon strip, so content needs a matching gutter reserved here —
  // when expanded it's a true overlay (with its own dismiss backdrop) and reserves
  // nothing. At `lg`+ the rail is a real flex sibling and already pushes content,
  // so no manual gutter is needed.
  const sidebarGutter = isLgUp ? 0 : sidebarCollapsed ? SIDEBAR_COLLAPSED_PX : 0

  // Step 2 (hotel selection) is a 3-panel split (list | map | detail) that
  // wants all the horizontal room it can get — auto-collapse the rail once
  // on ARRIVING at that stage. Only fires when `stage` actually changes to
  // 'hotels' (the effect's dependency), not on every render while it stays
  // 'hotels', so the user can freely re-expand the rail afterwards without
  // this fighting them back.
  useEffect(() => {
    if (stage === 'hotels') setSidebarCollapsed(true)
  }, [stage])

  return (
    <div className="h-screen overflow-hidden flex text-on-surface font-sans">
      {/* Ambient background blobs (design dc.html:53-55): float behind all
          glass panels via negative z-index; pointer-events pass through. */}
      <div
        aria-hidden
        className="pointer-events-none fixed -z-10 rounded-full"
        style={{
          top: '-14%',
          left: '-6%',
          width: '46vw',
          height: '46vw',
          background: 'radial-gradient(circle at 35% 35%, rgba(47,124,246,.34), rgba(47,124,246,0) 68%)',
          filter: 'blur(20px)',
          animation: 'vFloat 22s ease-in-out infinite',
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none fixed -z-10 rounded-full"
        style={{
          bottom: '-22%',
          right: '-8%',
          width: '52vw',
          height: '52vw',
          background: 'radial-gradient(circle at 50% 50%, rgba(238,139,60,.26), rgba(238,139,60,0) 66%)',
          filter: 'blur(24px)',
          animation: 'vFloat 28s ease-in-out infinite reverse',
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none fixed -z-10 rounded-full"
        style={{
          top: '22%',
          right: '18%',
          width: '26vw',
          height: '26vw',
          background: 'radial-gradient(circle at 50% 50%, rgba(18,165,148,.22), rgba(18,165,148,0) 68%)',
          filter: 'blur(20px)',
          animation: 'vFloat 19s ease-in-out infinite',
        }}
      />
      <SidebarRail
        theme={theme}
        onToggleTheme={toggleTheme}
        onNewTrip={onNewTrip}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((c) => !c)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onPickSession={onPickSession}
        onDeleteSession={onDeleteSession}
        turnPending={turnPending}
        restoringSessionId={restoringSessionId}
        onOpenAuthPanel={onOpenAuthPanel}
      />

      <div
        className="relative flex-1 flex flex-col md:flex-row overflow-y-auto overflow-x-hidden md:overflow-hidden min-w-0"
        style={{ paddingLeft: sidebarGutter }}
      >
        <div
          className="flex h-[55vh] shrink-0 md:h-auto md:absolute md:top-0 md:bottom-0 md:left-0 md:z-20 md:mt-3.5 md:mb-3.5 md:ml-3.5"
          style={{
            transform: focused ? 'translateX(calc(-100% - 14px))' : 'none',
            opacity: focused ? 0 : 1,
            pointerEvents: focused ? 'none' : 'auto',
            transition: 'transform .62s var(--ease-glide), opacity .38s ease',
          }}
        >
          <ChatPanel
            state={state}
            onSend={onSend}
            onChangeHotel={onChangeHotel}
            stage={stage}
            onViewStage={onViewStage}
            hotelOptionsAvailable={hotelOptions.length > 0}
            width={effectiveChatWidth}
            intakeForm={intakeForm}
            setIntakeForm={setIntakeForm}
            toggleIntakePreference={toggleIntakePreference}
            editingIntakeField={editingIntakeField}
            onDoneEditingIntakeField={onDoneEditingIntakeField}
            serverAskedField={serverAskedField}
          />
        </div>

        <div
          className="hidden md:flex md:absolute md:top-0 md:bottom-0 md:z-20 md:my-3.5"
          style={{
            left: chatWidth + 14,
            opacity: focused ? 0 : 1,
            pointerEvents: focused ? 'none' : 'auto',
            transition: 'opacity .3s ease',
          }}
        >
          <PanelResizer onMouseDown={onChatResizeStart} />
        </div>

        <div
          className="flex-1 min-h-[70vh] md:min-h-0 md:h-full flex overflow-hidden"
          style={{
            paddingLeft: isDesktop ? chatGutter : 0,
            // Was un-transitioned on purpose (see the file doc comment: "a
            // single one-time reflow per toggle, not animated, not a
            // per-frame cost") — but that made every stage panel (header,
            // list, map, detail) snap sideways instantly the moment focus
            // opens/closes, while the chat panel next to it is still
            // sliding away over .62s. Same duration/easing as chat's own
            // transform below, so the stage's left edge recedes in step
            // with chat leaving instead of jumping ahead of it. Trade-off
            // accepted: this reflows the stage subtree every frame for
            // .62s now, not once — revisit if that turns out janky on
            // lower-end devices.
            transition: isDesktop ? 'padding-left .62s var(--ease-glide)' : undefined,
          }}
        >
          <StageRouter
            stage={stage}
            state={state}
            hotelOptions={hotelOptions}
            selectedHotelIndex={selectedHotelIndex}
            onSelectHotel={onSelectHotel}
            onConfirmHotel={onConfirmHotel}
            focusMode={focusMode}
            intakeForm={intakeForm}
            onEditIntakeField={onEditIntakeField}
            theme={theme}
            roomHold={roomHold}
            onOpenBooking={onOpenBooking}
          />
        </div>
      </div>
    </div>
  )
}
