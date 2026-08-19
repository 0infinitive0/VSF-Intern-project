import { useTranslation } from 'react-i18next'
import { finalizeBlockedReason, isTripFinalized } from '../lib/trip-finalize-state'
import type { TripPlan } from '../types'

/**
 * FinalizeAction — the workspace header's "Hoàn tất lịch trình" control
 * (plan 260819-finalize-itinerary), mounted beside `HoldBanner` in the same
 * `<div className="flex-1" />` right-hand slot (stage-workspace.tsx).
 *
 * Purely presentational, matching `HoldBanner`'s split: this component only
 * renders state and calls `onRequestFinalize` when clicked — the confirm
 * dialog and the actual `finalizeTrip()` call live in `PlannerApp` (App.tsx),
 * mounted as a sibling of `<AppShell>` so its backdrop can escape this
 * header's `glass-panel` ancestor's `backdrop-filter` (the same reason
 * `booking-modal.tsx`/`ConfirmDialog` are placed there, not inline).
 *
 * `finalizeBlockedReason` is the single source of truth for which of the
 * five states below is shown — never re-derived inline here, so the button
 * and any other locked-state UI (App.tsx's composer hint) can't drift.
 */
export default function FinalizeAction({
  tripPlan,
  sessionBookedFromBackend,
  finalizing,
  error,
  onRequestFinalize,
  onDuplicateTrip,
}: {
  tripPlan: TripPlan | null
  sessionBookedFromBackend: boolean
  /** A finalize request is currently in flight — distinct from the chat's
   * own `state.pending`, which covers ordinary turns. */
  finalizing: boolean
  error: string | null
  onRequestFinalize: () => void
  /** The escape hatch (plan's "no unlock" decision): starts a brand-new
   * session pre-filled from this finalized trip's own facts
   * (App.tsx::handleDuplicateTrip). No clone endpoint — `startNew()` +
   * `send(composeIntakeMessage(...))`, both of which already exist. */
  onDuplicateTrip: () => void
}) {
  const { t } = useTranslation()

  if (isTripFinalized(tripPlan)) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onDuplicateTrip}
          className="px-3.5 py-2 rounded-[12px] border text-[12px] font-[530] cursor-pointer transition-colors duration-200 hover:bg-white"
          style={{ borderColor: 'var(--stroke)', background: 'var(--g3)', color: 'var(--t1)' }}
        >
          {t('duplicateTripCta')}
        </button>
        <div
          className="flex items-center gap-2 pl-3.5 pr-3.5 py-2 rounded-[14px] border"
          style={{ background: 'var(--ok-soft)', borderColor: 'rgba(42,145,135,.35)' }}
        >
          <span
            className="material-symbols-outlined text-[16px] leading-none"
            style={{ color: 'var(--ok-ink)' }}
            aria-hidden="true"
          >
            check_circle
          </span>
          <span className="text-[12.5px] font-[590] tracking-[-0.1px]" style={{ color: 'var(--ok-ink)' }}>
            {t('finalizeDoneBadge')}
          </span>
        </div>
      </div>
    )
  }

  const reason = finalizeBlockedReason({ tripPlan, sessionBookedFromBackend, pending: finalizing })
  if (reason === 'no-plan') return null

  if (finalizing) {
    return (
      <button
        type="button"
        disabled
        className="px-[22px] py-3 rounded-[14px] border-none text-[13px] font-[590] tracking-[-0.12px] cursor-not-allowed opacity-70"
        style={{ background: 'var(--fill)', color: 'var(--t2)' }}
      >
        {t('finalizeSaving')}
      </button>
    )
  }

  if (reason === 'not-paid') {
    return (
      <button
        type="button"
        disabled
        title={t('finalizeNotPaidHint')}
        className="px-[22px] py-3 rounded-[14px] border-none text-[13px] font-[590] tracking-[-0.12px] cursor-not-allowed"
        style={{ background: 'var(--fill)', color: 'var(--t2)' }}
      >
        {t('finalizeNotPaidHint')}
      </button>
    )
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={onRequestFinalize}
        className="px-[22px] py-3 rounded-[14px] border-none text-[13px] font-[590] tracking-[-0.12px] cursor-pointer transition-all duration-200 hover:-translate-y-px active:scale-[0.97]"
        style={{
          background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
          color: 'var(--on-acc)',
          boxShadow: '0 14px 30px -14px rgba(44,95,201,.7)',
        }}
      >
        {t('finalizeCta')}
      </button>
      {error && (
        <div role="alert" className="text-[11px]" style={{ color: 'var(--err)' }}>
          {error}
        </div>
      )}
    </div>
  )
}
