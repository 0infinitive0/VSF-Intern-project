import type { IntakeFormState } from '../lib/compose-intake-message'
import { composeIntakeMessage } from '../lib/compose-intake-message'
import type { PreferenceKey } from '../lib/intake-options'
import { currentIntakeField, type IntakeField } from '../lib/next-intake-field'
import { QUICK_START_DESTINATIONS } from '../lib/quick-start-destinations'
import type { IntakeStatus } from '../types'
import IntakeDestinationChips from './intake-destination-chips'
import IntakePeopleStepper from './intake-people-stepper'
import IntakeDateRange from './intake-date-range'
import IntakeBudgetSlider from './intake-budget-slider'
import IntakePreferenceChips from './intake-preference-chips'

/**
 * IntakeParametersForm — thin orchestrator (phase-06). Renders exactly ONE
 * intake widget at a time, driven by `currentIntakeField` (which walks the
 * real `intake.missing` keys in widget order and surfaces optional budget/
 * preferences only once the required fields are filled). The widgets collect
 * into `form` (owned by the caller via useIntakeForm — lifted so IntakeChecklist
 * can reflect the same in-progress answers); the final widget's button submits
 * ONE full composeIntakeMessage sentence — byte-identical to the pre-refactor
 * wire protocol (regression guarded by compose-intake-message.test.ts).
 *
 * This component renders the WIDGET ONLY. The question that goes with it is an
 * AI bubble in the chat thread (MessageList), never a bubble nested inside the
 * widget rail — matching the design, whose ask(step) pushes each intake
 * question into `messages` and leaves the rail for input alone.
 *
 * `editingField` (set by IntakeChecklist's "Sửa" button, via App.tsx's
 * useIntakeForm) overrides `currentIntakeField` and forces that one widget
 * open, pre-filled with the current value. A commit made while editing does
 * not fall through to the next progressive-disclosure field — there is
 * nothing "next" about a correction — it resends the full intake sentence
 * immediately (same composeIntakeMessage the initial flow uses) and calls
 * `onDoneEditing`. The backend's existing trip-preference-update path
 * (`_looks_like_trip_preference_change` / `TripPreferenceUpdate`,
 * backend/src/agents/session.py) is what actually applies the change and
 * decides whether hotels/itinerary need rerunning — this component never
 * fabricates that verdict itself.
 */
export default function IntakeParametersForm({
  intake,
  form,
  setForm,
  togglePreference,
  onSubmit,
  disabled,
  editingField = null,
  onDoneEditing,
}: {
  intake: IntakeStatus | null
  form: IntakeFormState
  setForm: (updater: (prev: IntakeFormState) => IntakeFormState) => void
  togglePreference: (key: PreferenceKey) => void
  onSubmit: (message: string) => void
  disabled: boolean
  editingField?: IntakeField | null
  onDoneEditing?: () => void
}) {
  // Pre-first-turn (`intake` still null — the local-only quick-start pick),
  // there is no real backend destination list yet to re-derive from: fall
  // back to the same static snapshot chat-panel.tsx's isEmptyConversation
  // branch offered originally, so re-opening "Sửa" on that row isn't a blank
  // widget just because no chat turn has happened yet.
  const destinations = intake?.available_destinations ?? QUICK_START_DESTINATIONS.map((d) => d.value)

  const activeField = editingField ?? currentIntakeField(intake, form)

  // Required fields are filled and the final optional card is confirmed — submit
  // the full sentence through the unchanged composeIntakeMessage.
  //
  // This is the one caller that states an empty preferences pick as an
  // explicit opt-out: it is the terminal submit, so "no chips selected" here
  // really is the user's answer, not a step they have yet to reach. Without
  // it the backend's required `preferences.themes` slot stays unanswered and
  // gets asked again in chat, right after this widget asked it.
  const submitAll = () => onSubmit(composeIntakeMessage(form, { includePreferencesOptOut: true }))

  // A single-field correction: apply it to `form`, resend the whole sentence
  // right away (there's no next widget to advance to), and close edit mode.
  const commitEdit = (next: IntakeFormState) => {
    setForm(() => next)
    onSubmit(composeIntakeMessage(next))
    onDoneEditing?.()
  }

  // The preferences card is terminal and stays mounted (with its own submit
  // button) until submitAll actually sends — see currentIntakeField's doc.
  // `intake` may be null pre-first-turn (empty-conversation destination pick
  // already happened, walking people/dates locally with no backend contact
  // yet) — currentIntakeField never returns 'budget'/'preferences' in that
  // case, so those two cases below are unreachable without a real `intake`.
  if (disabled) return null

  switch (activeField) {
    case 'destination':
      return (
        <IntakeDestinationChips
          destinations={destinations}
          selected={form.destination}
          onPick={(destination) =>
            editingField
              ? commitEdit({ ...form, destination })
              : setForm((prev) => ({ ...prev, destination }))
          }
          disabled={false}
        />
      )
    case 'people':
      return (
        <IntakePeopleStepper
          value={form.guests}
          onCommit={(guests) =>
            editingField ? commitEdit({ ...form, guests }) : setForm((prev) => ({ ...prev, guests }))
          }
          disabled={false}
        />
      )
    case 'dates':
      return (
        <IntakeDateRange
          start={form.startDate}
          end={form.endDate}
          onCommit={({ start, end }) =>
            editingField
              ? commitEdit({ ...form, startDate: start, endDate: end })
              : setForm((prev) => ({ ...prev, startDate: start, endDate: end }))
          }
          disabled={false}
        />
      )
    case 'budget':
      return (
        <IntakeBudgetSlider
          min={form.budgetMinVnd}
          max={form.budgetMaxVnd}
          onCommit={(min, max) =>
            editingField
              ? commitEdit({ ...form, budgetMinVnd: min, budgetMaxVnd: max, budgetSkipped: false })
              : setForm((prev) => ({ ...prev, budgetMinVnd: min, budgetMaxVnd: max, budgetSkipped: false }))
          }
          onSkip={() =>
            editingField
              ? commitEdit({ ...form, budgetMinVnd: null, budgetMaxVnd: null, budgetSkipped: true })
              : setForm((prev) => ({ ...prev, budgetMinVnd: null, budgetMaxVnd: null, budgetSkipped: true }))
          }
          disabled={false}
        />
      )
    case 'preferences':
      return (
        <IntakePreferenceChips
          selected={form.preferences}
          onToggle={togglePreference}
          onSubmit={() => {
            submitAll()
            if (editingField) onDoneEditing?.()
          }}
          disabled={false}
        />
      )
    default:
      return null
  }
}
