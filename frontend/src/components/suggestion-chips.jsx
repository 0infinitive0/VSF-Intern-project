/**
 * SuggestionChips — renders suggestions[] from any turn as tappable chips.
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
export default function SuggestionChips({ suggestions, onSelect, disabled }) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <div className="flex flex-wrap gap-2" role="group">
      {suggestions.map((s, i) => (
        <button
          key={i}
          className="px-3 py-1.5 bg-surface-background border border-border-subtle text-text-secondary hover:bg-surface-muted hover:text-text-primary rounded-full text-xs font-medium whitespace-nowrap transition-colors disabled:opacity-60"
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
