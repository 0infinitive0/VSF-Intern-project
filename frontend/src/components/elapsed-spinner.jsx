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
    <div className="elapsed-spinner" aria-live="polite" aria-busy="true">
      <span className="elapsed-spinner__ring" aria-hidden="true" />
      <span>
        {copy}
        {seconds > 0 && (
          <> ({seconds} {S.elapsedSuffix})</>
        )}
      </span>
    </div>
  )
}
