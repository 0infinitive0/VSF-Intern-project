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
    <div className="suggestions" role="group">
      {suggestions.map((s, i) => (
        <button
          key={i}
          className="chip"
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
