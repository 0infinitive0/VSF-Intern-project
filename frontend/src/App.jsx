import { S } from './strings.js'
import { useChatSession } from './hooks/use-chat-session.js'
import ChatPanel from './components/chat-panel.jsx'
import ItineraryPanel from './components/itinerary-panel.jsx'

/**
 * App — top-level component.
 * Owns the header, new-chat button, and lays out chat + itinerary panels.
 */
export default function App() {
  const { state, send, reset } = useChatSession()

  async function handleReset() {
    if (!window.confirm(S.newChatConfirm)) return
    await reset()
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__logo" aria-hidden="true">V</div>
        <div className="app-header__info">
          <div className="app-header__title">{S.appTitle}</div>
          <div className="app-header__subtitle">{S.appSubtitle}</div>
        </div>
        <div className="app-header__actions">
          <button
            id="new-chat-btn"
            className="btn-ghost"
            onClick={handleReset}
            type="button"
            title={S.resetTitle}
          >
            {S.newChatBtn}
          </button>
        </div>
      </header>

      <div className="app-body">
        <ChatPanel state={state} onSend={send} />
        <ItineraryPanel tripPlan={state.tripPlan} />
      </div>
    </div>
  )
}
