/**
 * next-intake-field.ts — the ONE place that maps the real `intake.missing`
 * keys to the progressive-disclosure widgets.
 *
 * Verification (see plan phase-06 step 1): `IntakeStatus.from_state`
 * (backend/src/models/schemas.py:163-204) only ever emits these real keys in
 * `missing`:
 *
 *     'destination', 'people', 'start_date', 'duration'
 *
 * `budget` and `preferences` are NEVER listed in `missing` — the backend does
 * not gate them. The phase-06 plan's assumed ORDER
 * `['destination','people','dates','budget','preferences']` therefore cannot be
 * matched directly against `missing`; this module is the sanctioned mapping
 * point ("nếu tên khác thì ánh xạ ngay tại đây, một chỗ duy nhất"). The
 * widget order still follows the plan/design; only the *source* differs.
 *
 * `isFieldMissing` + `currentIntakeField` are pure and unit-tested; the intake
 * orchestrator uses them and nothing else decides which card shows.
 */
import type { IntakeStatus } from '../types'

/**
 * The minimal subset of the intake form state these helpers read. Declared as a
 * structural shape (not importing `IntakeFormState`) so the widget-order module
 * stays decoupled from the wire-message module; `IntakeFormState` is
 * structurally assignable to it.
 */
export interface IntakeFormShape {
  destination?: string
  guests?: number
  startDate?: string
  endDate?: string
  budgetMinVnd?: number | null
  budgetMaxVnd?: number | null
  budgetSkipped?: boolean
  preferences?: unknown[]
}

export const INTAKE_FIELD_ORDER = [
  'destination',
  'people',
  'dates',
  'budget',
  'preferences',
] as const

export type IntakeField = (typeof INTAKE_FIELD_ORDER)[number]

// Real keys emitted in `intake.missing` for each widget field. Budget and
// preferences intentionally have no real keys (backend never gates them) —
// they surface only once every missing-gated field is answered.
export const FIELD_TO_REAL_KEYS: Record<IntakeField, readonly string[]> = {
  destination: ['destination'],
  people: ['people'],
  dates: ['start_date', 'duration'],
  budget: [],
  preferences: [],
}

export function isFieldMissing(intake: IntakeStatus | null, field: IntakeField): boolean {
  if (!intake) return false
  return FIELD_TO_REAL_KEYS[field].some((key) => intake.missing?.includes(key))
}

/**
 * First field the BACKEND still needs, in widget order, or null when every
 * missing-gated field is answered. This is the server-truth driver for the
 * first card shown on a given turn.
 */
export function nextIntakeField(intake: IntakeStatus | null): IntakeField | null {
  if (!intake) return null
  return INTAKE_FIELD_ORDER.find((field) => isFieldMissing(intake, field)) ?? null
}

/** Whether a widget field is already answered, considering both the local
 * form edits and the server snapshot the form was seeded from. */
/** Whether the backend already has a real budget answer from a plain-chat
 * reply — extract_patch's budget.min/max/target slots, echoed by respond.py
 * as intake.min_price/max_price/budget_skipped. Checked independently of the
 * local form so a budget answered via free-text chat (after the widget
 * already mounted, so the one-time form seed missed it) still suppresses the
 * redundant widget question instead of asking again. */
function isBudgetAnsweredOnServer(intake: IntakeStatus | null): boolean {
  if (!intake) return false
  return Boolean(intake.budget_skipped) || (intake.min_price != null && intake.max_price != null)
}

export function isFieldFilled(
  form: IntakeFormShape,
  field: IntakeField,
): boolean {
  switch (field) {
    case 'destination':
      return Boolean(form.destination)
    case 'people':
      return Number(form.guests) > 0
    case 'dates':
      return Boolean(
        form.startDate && form.endDate && String(form.endDate) > String(form.startDate),
      )
    case 'budget':
      return Boolean(form.budgetSkipped) || (form.budgetMinVnd != null && form.budgetMaxVnd != null)
    case 'preferences':
      return Array.isArray(form.preferences) && form.preferences.length > 0
  }
}

/**
 * The field whose question the FRONTEND has to ask itself, or null when the
 * backend's own last reply already asked it.
 *
 * Progressive disclosure advances LOCALLY: answering the people stepper only
 * calls setForm, so the widget moves on to `dates` with no chat turn in
 * between — and therefore no AI message asking about dates. `nextIntakeField`
 * is what the BACKEND still considers first-missing (i.e. what its last reply
 * asked about), so a mismatch means the user has walked past the backend and
 * nobody has asked the active field's question yet.
 *
 * This is the anti-duplicate gate. An earlier attempt solved the same problem
 * from the wrong end — it DELETED the backend's last message from the thread
 * whenever a locally-rendered prompt existed (chat-panel's old
 * hideDuplicateIntakeReply), which made real answered questions vanish and
 * reappear depending on which widget happened to be open. Suppressing the
 * redundant question is safe; deleting a real message never is.
 *
 * A field the user has ALREADY answered locally is never asked about, whatever
 * the backend thinks. Without that clause the terminal `preferences` card —
 * which by design stays open after the user picks a chip, since its own button
 * is the only way to submit — re-rendered its question on every intake-stage
 * turn: `nextIntakeField` is null once the gated fields are answered, and
 * `'preferences' !== null` is true forever. That is the second bubble users
 * saw next to an unrelated reply.
 */
export function locallyAdvancedField(
  intake: IntakeStatus | null,
  activeField: IntakeField | null,
  form: IntakeFormShape,
): IntakeField | null {
  if (!activeField) return null
  if (isFieldFilled(form, activeField)) return null
  return activeField === nextIntakeField(intake) ? null : activeField
}

/**
 * The widget field to show RIGHT NOW.
 *
 * Progressive-disclosure driver: walk the missing-gated fields first
 * (destination → people → dates); once all of those are filled locally (the
 * form holds the server-seeded values plus in-progress edits), surface the two
 * optional fields the backend never gates but the design does ask — budget
 * (only if real `budget_options` exist) then preferences.
 *
 * `preferences` is the terminal field: it stays active once reached regardless
 * of how many chips are toggled, because it is a multi-select with its own
 * "Tìm khách sạn" submit button — the card must not disappear the instant the
 * user picks one interest (that button is the only way `submitAll` runs). The
 * card only goes away when the parent hides the whole form after a real
 * submission changes `intake`.
 */
export function currentIntakeField(
  intake: IntakeStatus | null,
  form: IntakeFormShape,
): IntakeField | null {
  if (!intake) return null
  for (const field of INTAKE_FIELD_ORDER) {
    if (isFieldMissing(intake, field)) {
      if (!isFieldFilled(form, field)) return field
      // Load-bearing: the backend emits every unfilled gated key at once
      // (respond.py's _intake_status_from_travel_state), not one per turn. So
      // "missing but already filled locally" is the normal state during
      // progressive disclosure — the user answered this widget without a chat
      // turn, and the next widget is what should open. Returning `field` here
      // instead would pin the widget on the first unsent answer until a chat
      // turn happens, which is the whole flow.
      continue
    }
  }
  if (
    !isFieldFilled(form, 'budget') &&
    !isBudgetAnsweredOnServer(intake) &&
    (intake.budget_options?.length ?? 0) > 0
  ) {
    return 'budget'
  }
  return 'preferences'
}

/**
 * The field to pin the widget rail back to when a FRESH real backend turn
 * (this is meant to be called only from the effect that fires on a new
 * `intake` snapshot, never on every local `setForm`) still has an open
 * question the progressive-disclosure walk has already answered-but-not-sent
 * and skipped past.
 *
 * Mixing answer channels is what triggers this: the user answers `people`
 * via the stepper (local only, no chat turn — the widget silently advances,
 * as designed, see `currentIntakeField`'s "Load-bearing" note), then answers
 * something else entirely via free-text chat instead of continuing the
 * widget flow. That chat turn's real reply is the backend re-asking about
 * `people` (it genuinely never received that answer) — a real message
 * appended permanently to the thread. Left alone, the widget rail would
 * still show whatever field the local walk had already reached (e.g. the
 * terminal `preferences` card) right next to that real, still-open
 * question: two different-looking questions back to back with no answer in
 * between.
 *
 * Pinning back to `nextIntakeField` re-opens ITS OWN widget, pre-filled with
 * the local answer already collected — confirming it (IntakeParametersForm's
 * `editingField` path, `commitEdit`) immediately resends the whole
 * accumulated form as one message, resolving the divergence in a single
 * real turn instead of leaving it stuck.
 *
 * Never fires while the user already has an explicit "Sửa" edit open on a
 * different field — that correction takes priority and must not be
 * silently swapped out from under them.
 */
export function resyncField(
  intake: IntakeStatus | null,
  form: IntakeFormShape,
  editingField: IntakeField | null,
): IntakeField | null {
  if (editingField || !intake) return null
  const nextField = nextIntakeField(intake)
  if (!nextField) return null
  return currentIntakeField(intake, form) !== nextField ? nextField : null
}
