import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatSession } from './hooks/use-chat-session'
import { usePanelResize } from './hooks/use-panel-resize'
import ChatPanel from './components/chat-panel'
import ItineraryPanel from './components/itinerary-panel'
import MapPanel from './components/map-panel'
import PanelResizer from './components/panel-resizer'
import LanguageToggle from './components/language-toggle'

/**
 * App — top-level component.
 * Owns the top nav bar and lays out chat, itinerary, and map panels.
 */
export default function App() {
  const { t } = useTranslation()
  const { state, send, reset } = useChatSession()
  const [chatWidth, setChatWidth] = useState(380)
  const [itineraryWidth, setItineraryWidth] = useState(420)
  const chatResize = usePanelResize(chatWidth, setChatWidth, { min: 300, max: 560 })
  const itineraryResize = usePanelResize(itineraryWidth, setItineraryWidth, { min: 320, max: 640 })

  async function handleReset() {
    if (!window.confirm(t('newChatConfirm'))) return
    await reset()
  }

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-surface-background text-on-surface font-sans">
      <header className="flex justify-between items-center w-full px-4 h-16 bg-surface-background border-b border-border-subtle shadow-sm z-50 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-display text-lg font-bold text-primary tracking-tight truncate">
            {t('navBrand')}
          </span>
        </div>

        <nav className="hidden md:flex items-center gap-8 h-full" aria-label={t('navBrand')}>
          <button
            type="button"
            className="text-on-surface-variant h-full flex items-center px-2 text-sm opacity-60 cursor-not-allowed"
            disabled
            title={t('navExplorer')}
          >
            {t('navExplorer')}
          </button>
          <span className="text-primary border-b-2 border-primary font-semibold h-full flex items-center px-2 text-sm">
            {t('navTrips')}
          </span>
          <button
            type="button"
            className="text-on-surface-variant h-full flex items-center px-2 text-sm opacity-60 cursor-not-allowed"
            disabled
            title={t('navConcierge')}
          >
            {t('navConcierge')}
          </button>
        </nav>

        <div className="flex items-center gap-4 shrink-0">
          <LanguageToggle />

          <button
            id="new-chat-btn"
            className="hidden md:flex items-center gap-2 bg-primary text-on-primary px-5 py-2.5 rounded-lg text-sm font-medium hover:opacity-90 transition-opacity shadow-sm"
            onClick={handleReset}
            type="button"
            title={t('resetTitle')}
          >
            {t('newChatBtn')}
          </button>

          <div className="flex items-center gap-2">
            <span
              className="material-symbols-outlined text-on-surface-variant opacity-60 cursor-not-allowed text-[20px]"
              title={t('navNotifications')}
              aria-hidden="true"
            >
              notifications
            </span>
            <span
              className="material-symbols-outlined text-on-surface-variant opacity-60 cursor-not-allowed text-[20px]"
              title={t('navHelp')}
              aria-hidden="true"
            >
              help
            </span>
          </div>

          <span
            className="material-symbols-outlined text-on-surface-variant text-[28px]"
            aria-hidden="true"
          >
            account_circle
          </span>
        </div>
      </header>

      <main className="flex-1 flex overflow-hidden">
        <ChatPanel state={state} onSend={send} width={chatWidth} />
        <PanelResizer onMouseDown={chatResize} />
        <ItineraryPanel tripPlan={state.tripPlan} width={itineraryWidth} />
        <PanelResizer onMouseDown={itineraryResize} />
        <MapPanel />
      </main>
    </div>
  )
}
