/**
 * thinking-groups.ts — folds the backend's fine-grained `phase` keys into the
 * four steps a person actually wants to see.
 *
 * The backend reports where the code is (`intake_check`, `routing`,
 * `persisting`); a user wants to know what is being done for them. Nine keys
 * become six steps — mostly one-to-one, since folding four of them into a single
 * "understanding" step made the whole block read as one trivial stage for most
 * of a turn.
 *
 * The order they render in is fixed rather than taken from the order frames
 * arrive: `persisting` can land before `routing_legs` on some branches, and
 * "Saving" must never appear above "Building the itinerary".
 *
 * Steps are NOT pre-drawn. A turn that answers a question never touches hotel
 * search, so listing it greyed out would describe work that will not happen.
 */

import type { PhaseFacts, PhaseKey, PhaseTraceEntry, ThinkingGroup, ThinkingGroupKey } from '../types'

//: `received` and `compacting_history` are absent on purpose. They report the
//: turn opening and the transcript being trimmed to fit — real work, but the
//: system's own housekeeping rather than anything done for the person waiting.
//: An unmapped key is dropped silently, the same as one shipped after this build.
const GROUP_BY_PHASE: Partial<Record<PhaseKey, ThinkingGroupKey>> = {
  intake_check: 'analyze',
  routing: 'route',
  hotel_search: 'hotels',
  itinerary_build: 'itinerary',
  routing_legs: 'itinerary',
  persisting: 'save',
  generating: 'reply',
}

/** Render order. Not the arrival order — see the module docstring. */
export const GROUP_ORDER: ThinkingGroupKey[] = [
  'analyze',
  'route',
  'hotels',
  'itinerary',
  'save',
  'reply',
]

const GROUP_LABEL_I18N_KEY: Record<ThinkingGroupKey, string> = {
  analyze: 'thinkingGroupAnalyze',
  route: 'thinkingGroupRoute',
  hotels: 'thinkingGroupHotels',
  itinerary: 'thinkingGroupItinerary',
  save: 'thinkingGroupSave',
  reply: 'thinkingGroupReply',
}

/** The group a phase key belongs to, or null if the key is unknown to us. */
export function groupForPhase(key: string): ThinkingGroupKey | null {
  return (GROUP_BY_PHASE as Record<string, ThinkingGroupKey>)[key] ?? null
}

/**
 * Adds one phase frame's contribution to the group list.
 *
 * Returns a new array; never mutates. An unknown key is ignored silently — the
 * backend may ship a phase key before the frontend knows it, and a progress
 * strip is the wrong place to surface that.
 *
 * `lines` are appended rather than replaced, because a key can arrive more than
 * once: the supervisor re-routes, and each hop emits `routing` again. The group
 * itself is only created once.
 */
export function applyPhaseToGroups(
  groups: ThinkingGroup[],
  phaseKey: string,
  lines: string[],
  status?: 'started' | 'completed',
): ThinkingGroup[] {
  const groupKey = groupForPhase(phaseKey)
  if (!groupKey) return groups

  // A step is finished when the node says so, not when a later step happens to
  // start. The old inference spun on a step that had already ended.
  const finished = status === 'completed'

  const existing = groups.find((g) => g.key === groupKey)
  const next: ThinkingGroup[] = existing
    ? groups.map((g) =>
        g.key === groupKey
          ? { ...g, lines: appendNew(g.lines, lines), done: finished }
          : g,
      )
    : [
        ...groups,
        {
          key: groupKey,
          labelKey: GROUP_LABEL_I18N_KEY[groupKey],
          lines: [...lines],
          reasoning: '',
          done: finished,
        },
      ]

  // Still a safety net: a step emitted from inside a service never reports a
  // completion, so reaching a later one is the only signal it can get.
  const reachedIndex = GROUP_ORDER.indexOf(groupKey)
  return next
    .map((g) =>
      GROUP_ORDER.indexOf(g.key) < reachedIndex ? { ...g, done: true } : g,
    )
    .sort((a, b) => GROUP_ORDER.indexOf(a.key) - GROUP_ORDER.indexOf(b.key))
}

/** Appends only lines the group does not already show. */
function appendNew(current: string[], incoming: string[]): string[] {
  const additions = incoming.filter((line) => !current.includes(line))
  return additions.length ? [...current, ...additions] : current
}

/**
 * Appends the model's reasoning to the step that produced it.
 *
 * Routed by the frame's own `key`, never by "whichever step is open": a
 * reasoning frame is sent WHILE its node runs, and that node's `phase` frame
 * only lands once it finishes — so the step it belongs to usually does not
 * exist yet. It is created here rather than dropped.
 */
export function appendReasoning(
  groups: ThinkingGroup[],
  phaseKey: string,
  text: string,
): ThinkingGroup[] {
  if (!text) return groups
  const groupKey = groupForPhase(phaseKey)
  if (!groupKey) return groups

  const withGroup = groups.some((g) => g.key === groupKey)
    ? groups
    : applyPhaseToGroups(groups, phaseKey, [])

  return withGroup.map((g) =>
    g.key === groupKey ? { ...g, reasoning: g.reasoning + text } : g,
  )
}

/** Marks every group finished — the turn is over. */
export function completeGroups(groups: ThinkingGroup[]): ThinkingGroup[] {
  return groups.map((g) => (g.done ? g : { ...g, done: true }))
}

/**
 * Rebuilds a finished block from the trace stored with a reply.
 *
 * Sentences are composed now, not read back, so a conversation held in
 * Vietnamese reads in English if that is the language the user is in today —
 * and a change to the wording updates history rather than leaving it frozen.
 *
 * Every step is closed: this is a record of work already done, so nothing in it
 * may spin.
 */
export function groupsFromTrace(
  trace: PhaseTraceEntry[] | undefined,
  buildLines: (phaseKey: string, facts: PhaseFacts) => string[],
): ThinkingGroup[] {
  if (!trace?.length) return []
  const groups = trace.reduce(
    (acc, entry) =>
      applyPhaseToGroups(acc, entry.phase_key, buildLines(entry.phase_key, entry.facts), 'completed'),
    [] as ThinkingGroup[],
  )
  return completeGroups(groups)
}
