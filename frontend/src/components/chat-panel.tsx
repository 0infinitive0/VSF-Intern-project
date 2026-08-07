import { useTranslation } from 'react-i18next'
import MessageList from './message-list'
import Composer from './composer'
import StepNavigator from './step-navigator'
import SuggestionChips from './suggestion-chips'
import IntakeParametersForm from './intake-parameters-form'
import { deriveStageView } from '../lib/derive-stage'
import type { ChatState } from '../types'

function lastAiStage(messages: ChatState['messages']): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'ai') return messages[i].stage
  }
  return null
}

/**
 * ChatPanel — the chat column, restyled to the Claude Design glassmorphism
 * export (dc.html:125-302): status dot + trip title + step label + progress
 * dots header, the three-step navigator, the thread (MessageList), a FIXED
 * widget rail above the composer (intake cards / hotel cards / suggestion
 * chips), and the pill-glass composer.
 *
 * Phase-06 contract: this panel is never unmounted (app-shell.tsx owns that),
 * and it renders the stage widgets in the rail — not inside the scroll.
 */
export default function ChatPanel({
  state,
  onSend,
  width,
}: {
  state: ChatState
  onSend: (text: string) => void
  width: number
}) {
  const { messages, suggestions, hotelOptions, tripPlan, intake, pending, streamingText } = state
  const { t } = useTranslation()

  const stage = deriveStageView(state)
  const lastStage = lastAiStage(messages)
  const intakeComplete = stage === 'hotels' || stage === 'workspace'
  const hotelPicked = Boolean(tripPlan)

  // Header step label — design dc.html:2506 (stepEditing not tracked client-side;
  // the intake form pre-fills instead, so "step1Full" is the honest label).
  const stepLabel =
    stage === 'hotels'
      ? t('step2Full')
      : stage === 'workspace'
        ? t('step3Full')
        : stage === 'intake'
          ? t('step1Full')
          : t('aiWorking')

  // Progress dots — server-confirmed intake collection (5 widget steps).
  const progressDots = [
    { label: t('destLabel'), done: Boolean(intake?.destination) || intakeComplete },
    { label: t('peopleLabel'), done: Boolean(intake?.people) || intakeComplete },
    { label: t('datesLabel'), done: Boolean(intake?.start_date) || intakeComplete },
    { label: t('budgetLabel'), done: intakeComplete },
    { label: t('interestLabel'), done: (intake?.preferences?.length ?? 0) > 0 || intakeComplete },
  ]

  const tripTitle = tripPlan?.destination || intake?.destination || t('chatPanelTitle')

  // Phase 8: hotel cards live in the hotels STAGE (stage-hotels.tsx), not in
  // this rail — the two-step pick (card → header confirm) needs a single
  // selectedIndex owner. The rail keeps the one-step path unchanged: the
  // suggestion chips ("1".."3") still pick a hotel in one tap.
  const inHotelStage = lastStage === 'hotel_options' && hotelOptions.length > 0
  const showIntakeForm = lastStage === 'intake' && Boolean(intake) && !pending

  return (
    <section
      className="flex flex-col shrink-0 min-h-0 h-full glass-panel rounded-[26px] overflow-hidden"
      style={{ width }}
      aria-label={t('chatPanelTitle')}
    >
      {/* Header — status dot, trip title, step label, progress dots */}
      <div className="flex-none flex items-center gap-2.5 px-4.5 py-3.5 border-b border-line">
        <div
          className="w-[7px] h-[7px] rounded-full bg-success shadow-[0_0_0_3px_rgba(42,145,135,0.18)]"
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          <div className="text-[12.5px] font-semibold tracking-[-0.1px] text-on-surface truncate">
            {tripTitle}
          </div>
          <div className="text-[10.5px] tracking-[0.01em] text-on-surface-muted">{stepLabel}</div>
        </div>
        <div className="flex gap-[3px]" role="img" aria-label={t('progressDotsLabel')}>
          {progressDots.map((dot) => (
            <div
              key={dot.label}
              title={dot.label}
              className={`w-[13px] h-[4px] rounded-[3px] transition-colors duration-500 ${
                dot.done ? 'bg-primary' : 'bg-fill2'
              }`}
            />
          ))}
        </div>
      </div>

      <StepNavigator
        stage={stage}
        intakeComplete={intakeComplete}
        hotelPicked={hotelPicked}
        onSend={onSend}
      />

      <MessageList
        messages={messages}
        pending={pending}
        streamingText={streamingText}
      />

      {/* Widget rail — fixed above the composer, never inside the scroll */}
      {!pending && (showIntakeForm || inHotelStage || suggestions.length > 0) && (
        <div className="flex-none max-h-[56vh] overflow-y-auto custom-scrollbar px-4 pb-1 flex flex-col gap-2.5">
          {showIntakeForm ? (
            <IntakeParametersForm intake={intake!} onSubmit={onSend} disabled={false} />
          ) : (
            <>
              {lastStage !== 'intake' && (
                <SuggestionChips
                  suggestions={suggestions}
                  onSelect={onSend}
                  disabled={false}
                />
              )}
            </>
          )}
        </div>
      )}

      <div className="flex-none px-4 pb-4 pt-2">
        <Composer onSend={onSend} disabled={pending} />
      </div>
    </section>
  )
}
