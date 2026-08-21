import { useTranslation } from 'react-i18next'
import MessageList from './message-list'
import Composer from './composer'
import StepNavigator from './step-navigator'
import SuggestionChips from './suggestion-chips'
import IntakeParametersForm from './intake-parameters-form'
import IntakeDestinationChips from './intake-destination-chips'
import { QUICK_START_DESTINATIONS } from '../lib/quick-start-destinations'
import { composeIntakeMessage, type IntakeFormState } from '../lib/compose-intake-message'
import type { PreferenceKey } from '../lib/intake-options'
import { buildIntakeChecklistRows } from '../lib/intake-checklist-rows'
import { currentIntakeField, locallyAdvancedField, type IntakeField } from '../lib/next-intake-field'
import type { StageView } from '../lib/derive-stage'
import { isTripFinalized } from '../lib/trip-finalize-state'
import type { ChatState } from '../types'

function lastAiStage(messages: ChatState['messages']): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'ai') return messages[i].stage
  }
  return null
}

// i18n key for each widget's question. Rendered as an AI bubble in the thread
// (MessageList), never inside the widget rail — see IntakeParametersForm's
// header. 'destination' has no entry: it is always the first field, so the
// backend's own reply (or the greeting, which asks exactly it) covers it and
// locallyAdvancedField can never surface it.
const INTAKE_QUESTION_KEY: Partial<Record<IntakeField, string>> = {
  people: 'intakePeopleQuestion',
  dates: 'intakeDatesQuestion',
  budget: 'intakeBudgetQuestion',
  preferences: 'intakePreferencesQuestion',
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
  onChangeHotel,
  stage,
  onViewStage,
  hotelOptionsAvailable,
  width,
  intakeForm,
  setIntakeForm,
  toggleIntakePreference,
  editingIntakeField,
  onDoneEditingIntakeField,
  serverAskedField,
}: {
  state: ChatState
  onSend: (text: string) => void
  /** Rebuilds the hotel list without a chat turn — see step-navigator.tsx. */
  onChangeHotel: () => void
  /** What's currently displayed in the stage panel — may be a client-side
   * view override (see App.tsx) rather than the live backend-derived stage. */
  stage: StageView
  onViewStage: (stage: StageView) => void
  hotelOptionsAvailable: boolean
  width: number
  intakeForm: IntakeFormState
  setIntakeForm: (updater: (prev: IntakeFormState) => IntakeFormState) => void
  toggleIntakePreference: (key: PreferenceKey) => void
  editingIntakeField: IntakeField | null
  onDoneEditingIntakeField: () => void
  /** Field the most recent real backend reply is (best-effort) about — see
   * use-intake-form.ts. Suppresses a redundant local question for the SAME
   * field (budget/preferences never appear in `intake.missing`, so the
   * resyncField/nextIntakeField check alone can't catch a duplicate there:
   * the backend's own ask_slot.py flow asks about budget in its own words
   * right after dates/people resolve, independent of this widget rail). */
  serverAskedField: IntakeField | null
}) {
  const { messages, suggestions, hotelOptions, tripPlan, intake, pending, hotelsLoading, streamingText, thinking } = state
  const { t, i18n } = useTranslation()

  const lastStage = lastAiStage(messages)
  // Real backend truth — independent of what's currently being viewed —
  // gates which steps are reachable at all.
  // `hotelOptionsAvailable` (App.tsx's RETAINED per-session list), never the
  // live `hotelOptions` off `state` (bug fix): the backend legitimately
  // returns no hotel_options on any turn that didn't re-run the hotel search
  // -- a question answered by qa_node, a hotel selection, an itinerary build
  // -- so the live list empties mid-conversation while the trip is plainly
  // past intake. Reading it here made `intakeComplete` flip back to false on
  // those turns, which resurfaced the terminal preferences card and dragged
  // the whole panel back to "Bước 1 · Thu thập thông tin".
  const intakeComplete = hotelOptionsAvailable || tripPlan != null
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

  // Progress dots — same five rows, same "collected" rule as the intake
  // checklist panel on the right (buildIntakeChecklistRows: server snapshot
  // UNION the local widget answers). Previously this had its own server-only
  // logic, so a dot stayed grey until a chat turn round-tripped — and the
  // budget dot was gated on `intakeComplete`, i.e. it could not light up until
  // hotels already existed, long after the user had answered it.
  const dotLabelKey = ['destLabel', 'peopleLabel', 'datesLabel', 'budgetLabel', 'interestLabel']
  const progressDots = buildIntakeChecklistRows(intake, i18n.language, intakeForm).map((row, i) => ({
    label: t(dotLabelKey[i]),
    done: row.collected || intakeComplete,
  }))

  const tripTitle = tripPlan?.destination || intake?.destination || t('chatPanelTitle')

  // Phase 8: hotel cards live in the hotels STAGE (stage-hotels.tsx), not in
  // this rail — the two-step pick (card → header confirm) needs a single
  // selectedIndex owner. The rail keeps the one-step path unchanged: the
  // suggestion chips ("1".."3") still pick a hotel in one tap.
  const inHotelStage = lastStage === 'hotel_options' && hotelOptions.length > 0
  // `lastStage === 'intake'` covers the live collection flow; `editingIntakeField`
  // covers a "Sửa" tap on the intake checklist while viewing it via a client-side
  // stage override (e.g. jumped back from Khách sạn to Thông tin) — the backend's
  // last stage there is whatever it actually was (e.g. 'hotel_options'), so that
  // alone would hide the edit widget the tap is supposed to open.
  // The `&& !intakeComplete` guard on the first branch is load-bearing for a
  // RESTORED session: `session_store.restored_messages` hardcodes every
  // restored message's `stage` to "intake" (see the RESTORE reducer case's
  // comment in use-chat-session.ts — a real backend limitation, no `stage`
  // column on `chat_messages` yet), so `lastStage` is ALWAYS 'intake' right
  // after a reload, even for a fully-planned trip. Without this guard the
  // terminal preferences card (or whatever currentIntakeField resolves to)
  // would resurrect itself over an already-completed trip on every reload.
  // `intakeComplete` (retained hotel options / tripPlan, real backend truth
  // untouched by the restored-stage bug) is the honest signal instead.
  // Before the first turn, offer the real, currently-covered destinations
  // (data/UX-improvements-doc #1) so the user isn't stuck facing a blank
  // composer — same tap-or-type-freely chip pattern as server suggestions.
  const isEmptyConversation = messages.length === 0
  const showIntakeForm =
    !pending &&
    (Boolean(intake)
      ? (lastStage === 'intake' && !intakeComplete) || editingIntakeField != null
      : // Pre-first-turn: once the quick-start destination chip is picked
        // locally, keep walking people/dates the same way — see
        // currentIntakeField's pre-intake doc.
        isEmptyConversation && Boolean(intakeForm.destination))

  const activeIntakeField = editingIntakeField ?? currentIntakeField(intake, intakeForm)
  // The widget's question, asked in the thread only when the backend's own
  // last reply didn't already ask it (progressive disclosure advances locally,
  // with no chat turn — see locallyAdvancedField) AND isn't the same field a
  // fresh real reply already asked about in its own words (budget/preferences
  // — see serverAskedField's doc on the ChatPanel props type).
  const rawQuestionField = showIntakeForm ? locallyAdvancedField(intake, activeIntakeField, intakeForm) : null
  const questionField = rawQuestionField === serverAskedField ? null : rawQuestionField
  const questionKey = questionField ? INTAKE_QUESTION_KEY[questionField] : undefined
  const intakeQuestion = questionKey ? t(questionKey) : null

  // While the intake widget rail owns the flow, destination/people/dates/
  // budget/preferences accumulate LOCALLY (progressive disclosure — see
  // next-intake-field.ts) and only reach the backend when the terminal
  // "Tìm khách sạn phù hợp" button fires composeIntakeMessage(form). A user
  // who types free text into the composer instead of using the widgets (e.g.
  // at the preferences step) must not have that text sent bare — the backend
  // never received the earlier local answers, so a bare typed message alone
  // can never look like "enough state to search hotels" (the exact bug this
  // guards). Folding the typed text in and sending the same
  // composeIntakeMessage sentence the widget's own submit button uses keeps
  // both paths byte-identical once the required fields are filled.
  //
  // Text typed while the sở thích step is the active widget goes into
  // `preferencesNotes` (rendered into the "Sở thích:" sentence) instead of
  // `notes` (its own unlabelled sentence) — no check against the closed
  // PreferenceKey label set, it's appended verbatim. Any other step still
  // folds typed text into `notes`, unchanged.
  const handleComposerSend = (text: string) => {
    if (!showIntakeForm) {
      onSend(text)
      return
    }
    const atPreferencesStep = activeIntakeField === 'preferences'
    onSend(
      composeIntakeMessage({
        ...intakeForm,
        ...(atPreferencesStep
          ? {
              preferencesNotes: intakeForm.preferencesNotes
                ? `${intakeForm.preferencesNotes} ${text}`
                : text,
            }
          : { notes: intakeForm.notes ? `${intakeForm.notes} ${text}` : text }),
      }),
    )
  }

  return (
    <section
      className="flex flex-col shrink-0 min-h-0 h-full glass-panel rounded-[26px] overflow-hidden"
      style={{ width }}
      aria-label={t('chatPanelTitle')}
    >
      {/* Header — status dot, trip title, step label, progress dots */}
      <div className="flex-none flex items-center gap-2.5 px-4.5 py-3.5 border-b border-line">
        <div
          className="w-[7px] h-[7px] rounded-full bg-success shadow-[0_0_0_3px_var(--color-success-soft)]"
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          <div className="text-[12.5px] font-[590] tracking-[-0.1px] text-on-surface truncate">
            {tripTitle}
          </div>
          <div className="text-[10.5px] tracking-[0.01em] text-on-surface-muted">{stepLabel}</div>
        </div>
        <div className="flex gap-[3px]" role="img" aria-label={t('progressDotsLabel')}>
          {progressDots.map((dot) => (
            <div
              key={dot.label}
              title={dot.label}
              className={`w-[13px] h-[4px] rounded-[3px] transition-colors duration-[400ms] ${
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
        hotelOptionsAvailable={hotelOptionsAvailable}
        hotelsLoading={hotelsLoading}
        // Backend's own /hotels/change route now 409s once finalized
        // (routes.py::change_hotel) — no-op here too, so the click doesn't
        // even round-trip to discover that (plan 260819-finalize-itinerary,
        // "never offer an action the graph guard will refuse").
        onChangeHotel={isTripFinalized(tripPlan) ? () => {} : onChangeHotel}
        onViewStage={onViewStage}
      />

      <MessageList
        messages={messages}
        pending={pending}
        streamingText={streamingText}
        thinking={thinking}
        intakeQuestion={intakeQuestion}
      />

      {/* Widget rail — fixed above the composer, never inside the scroll */}
      {!pending && (showIntakeForm || inHotelStage || suggestions.length > 0 || isEmptyConversation) && (
        <div className="flex-none max-h-[56vh] overflow-y-auto custom-scrollbar px-4 pb-1 flex flex-col gap-2.5">
          {showIntakeForm ? (
            <IntakeParametersForm
              intake={intake}
              form={intakeForm}
              setForm={setIntakeForm}
              togglePreference={toggleIntakePreference}
              onSubmit={onSend}
              disabled={false}
              editingField={editingIntakeField}
              onDoneEditing={onDoneEditingIntakeField}
            />
          ) : isEmptyConversation ? (
            // Local pick only — no chat turn (same as IntakeDestinationChips'
            // real, backend-fed sibling once `intake` exists). Storing it in
            // `intakeForm.destination` here means mergeIntakeIntoForm carries
            // it forward once the first real turn's intake snapshot lands, so
            // it isn't asked twice — see use-intake-form.ts's merge doc.
            <IntakeDestinationChips
              destinations={QUICK_START_DESTINATIONS.map((d) => d.value)}
              selected={intakeForm.destination}
              onPick={(destination) => setIntakeForm((prev) => ({ ...prev, destination }))}
              disabled={false}
              hint={t('quickSuggestionsHint')}
            />
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
        {/* Composer stays enabled once finalized (plan 260819-finalize-
         * itinerary decision: "chat still answers questions, refuses
         * edits") — this hint is what keeps the backend's refusal
         * (nodes/supervisor.py's lock guard) from reading as a bug. */}
        {isTripFinalized(tripPlan) && (
          <div className="mb-2 text-[11px] text-on-surface-muted">{t('finalizeLockedChatHint')}</div>
        )}
        <Composer onSend={handleComposerSend} disabled={pending} />
      </div>
    </section>
  )
}
