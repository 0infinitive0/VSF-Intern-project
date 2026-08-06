import { useTranslation } from 'react-i18next'
import { formatTripDateRange } from '../lib/format-trip-dates'
import type { IntakeStatus, TripPlan } from '../types'

// intake.people is a formatted string like "2 người" (trip_intake.py's
// _format_people_count), not a bare number — pull the leading count back out.
function parseLeadingCount(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /^\d+/.exec(value)
  return match ? Number(match[0]) : null
}

/**
 * TripParametersCard — shows only backend-real fields: date range and adult
 * count. Renders nothing if neither is present (no empty card shell), and
 * never shows Budget Style/Preferences — the backend has no such fields.
 *
 * `tripPlan` only exists once a hotel is picked (trip_data is built in the
 * select_hotel tool). At the hotel_options stage — where the Stitch design
 * shows this card alongside the hotel picker — the only real source for
 * dates/guest count is the `intake` snapshot, so it's used as a fallback.
 */
export default function TripParametersCard({
  tripPlan,
  intake,
}: {
  tripPlan: TripPlan | null
  intake?: IntakeStatus | null
}) {
  const { t, i18n } = useTranslation()
  const dateRange =
    formatTripDateRange(tripPlan?.start_date, tripPlan?.end_date, i18n.language) ??
    formatTripDateRange(intake?.start_date, intake?.end_date, i18n.language)

  const adults = tripPlan?.number_of_adults ?? parseLeadingCount(intake?.people)

  if (!dateRange && !adults) return null

  return (
    <div className="bg-surface-background border border-outline-variant rounded-xl p-4 mb-3">
      <h3 className="text-sm font-medium text-on-surface mb-3 flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-sm" aria-hidden="true">
          tune
        </span>
        {t('tripParamsTitle')}
      </h3>
      {dateRange && (
        <div className="mb-2">
          <label className="text-xs text-on-surface-variant block mb-1">
            {t('tripParamsDatesLabel')}
          </label>
          <div className="flex items-center gap-2 bg-surface-muted p-2 rounded-lg">
            <span className="material-symbols-outlined text-on-surface-variant text-sm" aria-hidden="true">
              calendar_month
            </span>
            <span className="text-sm text-on-surface">{dateRange}</span>
          </div>
        </div>
      )}
      {adults != null && (
        <div>
          <label className="text-xs text-on-surface-variant block mb-1">
            {t('tripParamsGuestsLabel')}
          </label>
          <div className="flex items-center gap-2 bg-surface-muted p-2 rounded-lg">
            <span className="material-symbols-outlined text-on-surface-variant text-sm" aria-hidden="true">
              group
            </span>
            <span className="text-sm text-on-surface">
              {adults} {t('tripParamsAdultsSuffix')}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
