/**
 * thinking-groups.ts — folds the backend's fine-grained `phase` keys into the
 * four steps a person actually wants to see.
 *
 * The backend reports where the code is (`compacting_history`, `intake_check`,
 * `routing`); a user wants to know what is being done for them. Nine keys become
 * seven steps — mostly one-to-one, since folding four of them into a single
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

import type { PhaseKey, ThinkingGroup, ThinkingGroupKey } from '../types'

const GROUP_BY_PHASE: Record<PhaseKey, ThinkingGroupKey> = {
  received: 'history',
  compacting_history: 'history',
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
  'history',
  'analyze',
  'route',
  'hotels',
  'itinerary',
  'save',
  'reply',
]

const GROUP_LABEL_I18N_KEY: Record<ThinkingGroupKey, string> = {
  history: 'thinkingGroupHistory',
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
): ThinkingGroup[] {
  const groupKey = groupForPhase(phaseKey)
  if (!groupKey) return groups

  const existing = groups.find((g) => g.key === groupKey)
  const next: ThinkingGroup[] = existing
    ? groups.map((g) =>
        g.key === groupKey ? { ...g, lines: appendNew(g.lines, lines) } : g,
      )
    : [
        ...groups,
        {
          key: groupKey,
          labelKey: GROUP_LABEL_I18N_KEY[groupKey],
          lines: [...lines],
          reasoning: '',
          done: false,
        },
      ]

  // Reaching a later group means every earlier one finished. Derived from
  // GROUP_ORDER rather than from arrival order, for the same reason as sorting.
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

/** Appends the model's own reasoning text to the group still in progress. */
export function appendReasoning(groups: ThinkingGroup[], text: string): ThinkingGroup[] {
  if (!text) return groups
  const active = [...groups].reverse().find((g) => !g.done)
  if (!active) return groups
  return groups.map((g) =>
    g === active ? { ...g, reasoning: g.reasoning + text } : g,
  )
}

/** Marks every group finished — the turn is over. */
export function completeGroups(groups: ThinkingGroup[]): ThinkingGroup[] {
  return groups.map((g) => (g.done ? g : { ...g, done: true }))
}
