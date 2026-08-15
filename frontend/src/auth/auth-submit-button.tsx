/**
 * auth-submit-button.tsx — shared primary CTA. Design requirement (§4/§28 of
 * the Authentication docs): the button never disappears or changes size
 * while loading, it's disabled and shows a spinner in place of the label,
 * and submitting again mid-request is impossible.
 */
export default function SubmitButton({ loading, label }: { loading: boolean; label: string }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="h-12 mt-1 rounded-[15px] bg-button text-on-button text-[14.5px] font-semibold tracking-tight flex items-center justify-center gap-2 transition-[transform,box-shadow,opacity] duration-200 disabled:cursor-progress disabled:opacity-80 hover:not-disabled:-translate-y-px active:not-disabled:scale-[.985]"
    >
      {loading && (
        <span
          aria-hidden
          className="w-[15px] h-[15px] rounded-full border-2 border-white/30"
          style={{ borderTopColor: 'currentColor', animation: 'vSpin .7s linear infinite' }}
        />
      )}
      {loading ? '' : label}
    </button>
  )
}
