import { S } from '../strings.js'

/**
 * DayCard — one day of the trip plan with a timeline of activities.
 */
export default function DayCard({ day }) {
  return (
    <div className="day-card">
      <div className="day-card__header">
        <div className="day-card__day">{S.dayLabel(day.day_number)}</div>
        {day.theme && <div className="day-card__theme">{day.theme}</div>}
      </div>
      <div className="day-card__items">
        {(day.items || []).map((item, i) => (
          <div key={i} className="day-item">
            <div className="day-item__time">
              {item.start_time}
              {item.end_time && item.end_time !== item.start_time && (
                <div className="day-item__end-time">{item.end_time}</div>
              )}
            </div>
            <div className="day-item__dot" />
            <div className="day-item__body">
              <div className="day-item__activity">{item.activity}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
