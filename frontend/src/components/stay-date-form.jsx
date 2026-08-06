import { useId, useMemo, useState } from 'react'
import { S } from '../strings.js'

/** Collect the check-in and exclusive checkout date outside of free-form chat. */
export default function StayDateForm({ onSubmit, disabled }) {
  const startId = useId()
  const endId = useId()
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [error, setError] = useState('')
  const today = useMemo(() => new Date().toISOString().slice(0, 10), [])

  function handleSubmit(event) {
    event.preventDefault()
    if (!startDate || !endDate) {
      setError(S.stayDatesRequired)
      return
    }
    if (endDate <= startDate) {
      setError(S.stayDatesOrderError)
      return
    }
    setError('')
    onSubmit({ startDate, endDate })
  }

  return (
    <form className="stay-date-form" onSubmit={handleSubmit} aria-label={S.stayDatesTitle}>
      <div className="stay-date-form__heading">
        <strong>{S.stayDatesTitle}</strong>
        <span>{S.stayDatesHint}</span>
      </div>
      <div className="stay-date-form__fields">
        <label htmlFor={startId}>
          {S.stayStartDate}
          <input
            id={startId}
            type="date"
            value={startDate}
            disabled={disabled}
            onChange={(event) => setStartDate(event.target.value)}
          />
        </label>
        <label htmlFor={endId}>
          {S.stayEndDate}
          <input
            id={endId}
            type="date"
            min={startDate}
            value={endDate}
            disabled={disabled}
            onChange={(event) => setEndDate(event.target.value)}
          />
        </label>
      </div>
      {error ? <p className="stay-date-form__error" role="alert">{error}</p> : null}
      <button className="stay-date-form__submit" type="submit" disabled={disabled}>
        {S.stayDatesSubmit}
      </button>
    </form>
  )
}
