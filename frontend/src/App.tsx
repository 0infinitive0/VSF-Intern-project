import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatSession } from './hooks/use-chat-session'
import { usePanelResize } from './hooks/use-panel-resize'
import { deriveStageView } from './lib/derive-stage'
import AppShell from './components/app-shell'

/**
 * App — thin composition layer. Owns session/panel-width state and derives
 * the stage view; all layout and shell mechanics live in AppShell so future
 * phases (6-10) only fill in the areas it creates, never touching this file
 * or AppShell's structure again.
 */
export default function App() {
  const { t } = useTranslation()
  const { state, send, reset } = useChatSession()
  const [chatWidth, setChatWidth] = useState(380)
  const [itineraryWidth, setItineraryWidth] = useState(420)
  const chatResize = usePanelResize(chatWidth, setChatWidth, { min: 300, max: 560 })
  const itineraryResize = usePanelResize(itineraryWidth, setItineraryWidth, { min: 320, max: 640 })
  const stage = deriveStageView(state)

  async function handleReset() {
    if (!window.confirm(t('newChatConfirm'))) return
    await reset()
  }

  return (
    <AppShell
      state={state}
      onSend={send}
      onNewTrip={handleReset}
      stage={stage}
      chatWidth={chatWidth}
      onChatResizeStart={chatResize}
      itineraryWidth={itineraryWidth}
      onItineraryResizeStart={itineraryResize}
    />
  )
}
