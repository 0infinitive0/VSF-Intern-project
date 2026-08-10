import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatSession } from './hooks/use-chat-session'
import { useIntakeForm } from './hooks/use-intake-form'
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

  async function handleReset() {
    if (!window.confirm(t('newChatConfirm'))) return
    await reset()
    resetIntakeForm()
  }

  return (
    <AppShell
      state={state}
      onSend={send}
      onNewTrip={handleReset}
      stage={stage}
      chatWidth={chatWidth}
      onChatResizeStart={chatResize}
      intakeForm={intakeForm}
      setIntakeForm={setIntakeForm}
      toggleIntakePreference={toggleIntakePreference}
      editingIntakeField={editingIntakeField}
      onEditIntakeField={setEditingIntakeField}
      onDoneEditingIntakeField={() => setEditingIntakeField(null)}
    />
  )
}
