import { S } from '../strings.js'

/**
 * ElapsedSpinner — shows while a request is in-flight.
 * Displays a rotating ring + copy that changes after 10s.
 */
export default function ElapsedSpinner({ elapsedMs }) {
  const seconds = Math.floor(elapsedMs / 1000)
  let copy = S.pendingDefault
  if (seconds >= 10) copy = S.pendingBuildingPlan
  else if (seconds >= 3) copy = S.pendingSearchingHotels

  return (
    <div
      className="flex items-center gap-2 text-sm text-text-secondary"
      aria-live="polite"
      aria-busy="true"
    >
      <span
        className="elapsed-spinner__ring w-4 h-4 rounded-full border-2 border-border-subtle border-t-primary shrink-0"
        aria-hidden="true"
      />
      <span>
        {copy}
        {seconds > 0 && (
          <> ({seconds} {S.elapsedSuffix})</>
        )}
      </span>
    </div>
  )
}
