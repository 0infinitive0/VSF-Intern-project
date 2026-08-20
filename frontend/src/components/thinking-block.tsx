import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ThinkingGroup, ThinkingGroupKey } from '../types'

/**
 * ThinkingBlock — the turn's reasoning, listed above the reply.
 *
 * Deliberately unframed: no avatar, no bubble, no card. It is not something the
 * assistant said, it is a record of what it did, so it sits on the page rather
 * than in the conversation. The reply below keeps its own card and stays the
 * thing being read.
 *
 * The running step opens itself, and any step can be opened by clicking it —
 * including finished ones, so a reader can go back and see what a step actually
 * did. Only one is open at a time: keeping them all open would push the reply
 * off screen by the end of a long turn.
 *
 * The block stays after the turn ends (collapsed to ticks), so a user can look
 * back at what produced the answer they are reading.
 */
export default function ThinkingBlock({ groups }: { groups: ThinkingGroup[] }) {
  const { t } = useTranslation()
  // Null until the user touches the toggle. After that their choice wins —
  // auto-collapse must never fight someone reading.
  const [manualOpen, setManualOpen] = useState<boolean | null>(null)
  // Null means "follow whichever step is running". A click pins one instead,
  // and pinning the already-open step closes it.
  const [pinnedStep, setPinnedStep] = useState<ThinkingGroupKey | null | false>(null)

  const allDone = groups.length > 0 && groups.every((g) => g.done)
  const open = manualOpen ?? true
  const runningKey = groups.find((g) => !g.done)?.key ?? null
  // The newest step that has something to show, falling back to the running one.
  //
  // Not simply the running step: facts arrive when a step FINISHES, so a step
  // that reported something is already done by the time it has anything to
  // display. Following the running step made those lines flash for the few
  // milliseconds before the next step opened.
  const lastWithDetail =
    [...groups].reverse().find((g) => g.lines.length > 0 || g.reasoning)?.key ?? null
  // Once the turn has answered, every step closes: the reply is what the reader
  // came for, and a step left open pushes it down the page — or, when the
  // model's reasoning ran long, right off it. Clicking still opens any step.
  const openStep =
    pinnedStep === null ? (allDone ? null : lastWithDetail ?? runningKey) : pinnedStep || null

  if (groups.length === 0) return null

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={() => setManualOpen(!open)}
        aria-expanded={open}
        className="min-h-[44px] flex items-center gap-1.5 text-left text-[14px] font-[590] text-on-surface cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        <span>{allDone ? t('thinkingHeaderDone') : t('thinkingHeaderRunning')}</span>
        <span
          className={`text-[13px] text-on-surface-muted transition-transform motion-reduce:transition-none ${
            open ? '' : 'rotate-180'
          }`}
          aria-hidden="true"
        >
          ⌃
        </span>
      </button>

      {open && (
        <div
          // Focusable on purpose: an overflow container with no tabindex cannot
          // be scrolled by keyboard at all.
          tabIndex={0}
          role="region"
          aria-label={t('thinkingStepsRegion')}
          aria-live="polite"
          aria-busy={!allDone}
          // No height cap and no inner scroll: `max-h` with `overflow-visible` let
          // long reasoning spill out of the box and run under the reply below.
          // The block stays short on its own — one step is open at a time, and
          // every step closes once the turn has answered — so the page's own
          // scroll is the only one needed.
          className="flex flex-col gap-2 pb-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          {groups.map((group) => (
            <Step
              key={group.key}
              group={group}
              expanded={group.key === openStep}
              onToggle={() =>
                setPinnedStep(group.key === openStep ? false : group.key)
              }
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function Step({
  group,
  expanded,
  onToggle,
  t,
}: {
  group: ThinkingGroup
  expanded: boolean
  onToggle: () => void
  t: (key: string) => string
}) {
  const hasDetail = group.lines.length > 0 || Boolean(group.reasoning)

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={hasDetail ? onToggle : undefined}
        aria-expanded={hasDetail ? expanded : undefined}
        disabled={!hasDetail}
        className={`min-h-[22px] flex items-center gap-2.5 text-left text-[13.5px] text-on-surface rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary ${
          hasDetail ? 'cursor-pointer' : 'cursor-default'
        }`}
      >
        {group.done ? <CheckIcon /> : <SpinnerIcon />}
        <span className="min-w-0">{t(group.labelKey)}</span>
      </button>

      {/* `grid-rows: 0fr → 1fr` animates to the content's real height without
          anyone having to measure it, so the reveal works for one line or ten
          and never clips. */}
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none ${
          expanded && hasDetail ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="overflow-hidden">
          {/* Indented to the label, not the icon, so the detail reads as
              belonging to the step above it. */}
          <div className="pl-[26px] pt-0.5 pb-1 flex flex-col gap-0">
            {group.lines.map((line) => (
              <p
                key={line}
                className="text-[13px] leading-[1.65] text-on-surface-muted motion-safe:animate-[vRise_.26s_ease-out]"
              >
                {line}
              </p>
            ))}

            {/* The model's own words, kept visibly apart from the product's.
                Always English (docs/chat_api_contract.md), so it is labelled
                rather than translated, and only present when it produced any. */}
            {group.reasoning && (
              <>
                <p className="text-[13px] leading-[1.65] text-on-surface-muted whitespace-pre-wrap">
                  {group.reasoning}
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * The design's check: a bold stroke mark, not the `✓` character.
 *
 * The rest of this codebase uses the glyph, but a font character cannot carry
 * the weight and proportions this list needs — it renders thin and sits off the
 * text baseline. Drawn here so the mark is the same on every platform.
 */
function CheckIcon() {
  return (
    <svg
      className="w-[18px] h-[18px] flex-none text-on-surface"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 10.5 8 15 16 5" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <span
      className="w-[18px] h-[18px] flex-none rounded-full border-2 border-primary border-t-transparent animate-spin motion-reduce:animate-none"
      aria-hidden="true"
    />
  )
}
