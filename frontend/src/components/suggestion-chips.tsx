import type { Suggestion } from '../types'

/**
 * SuggestionChips — renders suggestions[] from any turn as tappable glass chips.
 *
 * Per the contract and the comment in chat.html:
 *   "Chips come from the server's `suggestions` field, never from scanning
 *    the reply for lines like '1. ...'. The model writes numbered lists in
 *    ordinary prose, and a scanner turns those into buttons that send a bare
 *    '1' into a turn that wanted free text."
 *
 * This component is generic — it renders on ANY turn that returns suggestions[],
 * not only hotel_options turns.
 */
export default function SuggestionChips({
  suggestions,
  onSelect,
  disabled,
}: {
  suggestions: Suggestion[]
  onSelect: (value: string) => void
  disabled: boolean
}) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2" role="group">
      {suggestions.map((s, i) => (
        <button
          key={i}
          className="rounded-full px-[13px] py-2 text-[12.5px] font-normal text-on-surface bg-glass-2 border border-stroke hover:bg-primary! hover:text-on-primary! hover:border-primary! hover:-translate-y-0.5! transition-all duration-[220ms] ease-[cubic-bezier(0.34,1.4,0.64,1)] disabled:opacity-60 cursor-pointer"
          disabled={disabled}
          onClick={() => onSelect(s.value)}
          type="button"
        >
          {s.label}
        </button>
      ))}
    </div>
  )
}
