import { S } from './strings.js'
import { useChatSession } from './hooks/use-chat-session.js'
import ChatPanel from './components/chat-panel.jsx'
import ItineraryPanel from './components/itinerary-panel.jsx'
import MapPanel from './components/map-panel.jsx'

/**
 * App — top-level component.
 * Owns the top nav bar and lays out chat, itinerary, and map panels.
 */
export default function App() {
  const { state, send, reset } = useChatSession()

  async function handleReset() {
    if (!window.confirm(S.newChatConfirm)) return
    await reset()
  }

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-surface-background text-on-surface font-sans">
      <header className="flex justify-between items-center w-full px-4 h-16 bg-surface-background border-b border-border-subtle shadow-sm z-50 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="w-8 h-8 shrink-0 rounded-lg bg-primary text-on-primary font-display font-bold flex items-center justify-center"
            aria-hidden="true"
          >
            V
          </div>
          <div className="min-w-0">
            <div className="font-display font-semibold text-text-primary leading-tight truncate">
              {S.appTitle}
            </div>
            <div className="text-xs text-text-secondary leading-tight truncate">
              {S.appSubtitle}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <button
            id="new-chat-btn"
            className="px-3 py-1.5 text-sm font-medium text-text-secondary hover:bg-surface-muted rounded-md transition-colors"
            onClick={handleReset}
            type="button"
            title={S.resetTitle}
          >
            {S.newChatBtn}
          </button>
        </div>
      </header>

      <main className="flex-1 flex overflow-hidden">
        <ChatPanel state={state} onSend={send} />
        <ItineraryPanel tripPlan={state.tripPlan} />
        <MapPanel />
      </main>
    </div>
  )
}
