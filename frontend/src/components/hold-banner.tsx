import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { RoomHoldApi } from '../hooks/use-room-hold'

function mmss(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/**
 * HoldBanner — the workspace header's room-hold status (V-OTA Planner design
 * update, HELD/EXPIRED/BOOKED blocks). Mounted in stage-workspace.tsx's
 * header bar. Renders nothing outside those three states — HOLDING is
 * visible on hotel-detail-panel.tsx's own footer (still on screen at that
 * point), and IDLE/ERROR mean there's nothing to show at all.
 *
 * The countdown is a plain 1s re-render off `roomHold.holdLeftMs`, which
 * itself ticks off the group's real server `expires_at` (use-room-hold.ts) —
 * never a client-invented duration.
 *
 * `roomHold` is a single GLOBAL hold, not scoped per chat session (see
 * use-room-hold.ts's module doc comment) — `holdBelongsToSession` is what
 * keeps this banner honest about that: without it, switching the live hold
 * to a different hotel from a DIFFERENT session (hotel-detail-panel.tsx's
 * heldElsewhere -> switchHold flow) would leave THIS session's workspace
 * still showing the countdown and an enabled "Đặt phòng" button for a hold
 * it no longer owns — a real guest-facing bug (checking out for the wrong
 * hotel) this early-return exists specifically to prevent.
 *
 * `sessionBookedFromBackend` is the fallback for the one case that early
 * return would otherwise wrongly hide: a session that genuinely completed
 * payment, then later lost `holdBelongsToSession` because roomHold moved
 * on to a different session. Backend-sourced (the same per-session status
 * the sidebar badge reads — see App.tsx), so it survives roomHold being
 * overwritten, unlike `roomHold.status === 'BOOKED'` itself. Its "Xem đặt
 * phòng" button opens `onOpenReceipt`, not `onOpenBooking`: roomHold no
 * longer has this session's booking data (booking-modal.tsx only ever
 * reads off roomHold), so booking-receipt-modal.tsx fetches it fresh from
 * the backend by session_id instead (GET /chat/{id}/booking-receipt).
 */
export default function HoldBanner({
  roomHold,
  holdBelongsToSession,
  sessionBookedFromBackend,
  onOpenBooking,
  onOpenReceipt,
}: {
  roomHold: RoomHoldApi
  holdBelongsToSession: boolean
  sessionBookedFromBackend: boolean
  /** Opens booking-modal.tsx — it derives its own step from roomHold.status
   * (BOOKED always lands on the done screen), so this takes no arguments. */
  onOpenBooking: () => void
  /** Opens booking-receipt-modal.tsx for the ACTIVE session specifically —
   * only ever reachable from the sessionBookedFromBackend branch below. */
  onOpenReceipt: () => void
}) {
  const { t } = useTranslation()
  // Local re-render tick so the mm:ss label visibly counts down even though
  // holdLeftMs is only recomputed from `now`, which the hook already ticks —
  // this just forces THIS component to re-read it every second too.
  const [, forceTick] = useState(0)
  useEffect(() => {
    if (roomHold.status !== 'HELD') return
    const id = setInterval(() => forceTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [roomHold.status])

  if (!holdBelongsToSession) {
    if (!sessionBookedFromBackend) return null
    return (
      <div
        className="flex items-center gap-3 pl-3.5 pr-2.5 py-2 rounded-[14px] border"
        style={{ background: 'var(--ok-soft)', borderColor: 'rgba(42,145,135,.35)' }}
      >
        <div className="text-[12.5px] font-[590] tracking-[-0.1px]" style={{ color: 'var(--ok-ink)' }}>
          {t('holdBannerBookedTitle')}
        </div>
        <button
          type="button"
          onClick={onOpenReceipt}
          className="px-[15px] py-2.5 rounded-xl border text-[12.5px] font-[530] cursor-pointer transition-colors duration-200 hover:bg-white"
          style={{ borderColor: 'var(--stroke)', background: 'var(--g3)', color: 'var(--t1)' }}
        >
          {t('holdBannerViewBooking')}
        </button>
      </div>
    )
  }

  if (roomHold.status === 'HELD') {
    const warn = roomHold.holdLeftMs <= 5 * 60 * 1000
    const danger = roomHold.holdLeftMs <= 60 * 1000
    return (
      <div className="flex items-center gap-2.5">
        <div
          className="flex items-center gap-2 px-3.5 py-2 rounded-[13px] border whitespace-nowrap"
          style={{
            background: danger ? 'var(--err-soft, rgba(192,94,112,.14))' : warn ? 'var(--warn-soft)' : 'var(--fill)',
            borderColor: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--stroke)',
            animation: danger ? 'vPulse 1.6s ease-in-out infinite' : 'none',
          }}
        >
          <span
            className="material-symbols-outlined text-[16px] leading-none"
            style={{ color: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--t2)' }}
            aria-hidden="true"
          >
            schedule
          </span>
          <span className="text-[9.5px] font-[590] tracking-[0.09em] uppercase text-on-surface-muted">
            {t('holdBannerHeldLabel')}
          </span>
          <span
            className="text-[15px] font-[590] tracking-[-0.35px] tabular-nums"
            style={{ color: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--t2)' }}
          >
            {mmss(roomHold.holdLeftMs)}
          </span>
        </div>
        <button
          type="button"
          onClick={onOpenBooking}
          className="px-[22px] py-3 rounded-[14px] border-none text-[13px] font-[590] tracking-[-0.12px] cursor-pointer transition-all duration-200 hover:-translate-y-px active:scale-[0.97]"
          style={{
            background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
            color: 'var(--on-acc)',
            boxShadow: '0 14px 30px -14px rgba(44,95,201,.7)',
          }}
        >
          {t('holdBannerBook')}
        </button>
      </div>
    )
  }

  if (roomHold.status === 'EXPIRED') {
    return (
      <div
        className="flex items-center gap-3 pl-3.5 pr-2.5 py-2 rounded-[14px] border"
        style={{ background: 'var(--err-soft, rgba(192,94,112,.12))', borderColor: 'var(--err)' }}
      >
        <div>
          <div className="text-[12.5px] font-[590] tracking-[-0.1px]" style={{ color: 'var(--err)' }}>
            {t('holdBannerExpiredTitle')}
          </div>
          <div className="text-[11px] text-on-surface-muted">{t('holdBannerExpiredBody')}</div>
        </div>
        <button
          type="button"
          onClick={() => void roomHold.recheckRooms()}
          className="px-[15px] py-2.5 rounded-xl border-none text-[12.5px] font-[590] cursor-pointer transition-transform duration-200 active:scale-[0.97]"
          style={{ background: 'var(--err)', color: '#FCFDFE' }}
        >
          {t('holdBannerRecheck')}
        </button>
      </div>
    )
  }

  if (roomHold.status === 'BOOKED') {
    return (
      <div
        className="flex items-center gap-3 pl-3.5 pr-2.5 py-2 rounded-[14px] border"
        style={{ background: 'var(--ok-soft)', borderColor: 'rgba(42,145,135,.35)' }}
      >
        <div className="text-[12.5px] font-[590] tracking-[-0.1px]" style={{ color: 'var(--ok-ink)' }}>
          {t('holdBannerBookedTitle')}
        </div>
        <button
          type="button"
          onClick={onOpenBooking}
          className="px-[15px] py-2.5 rounded-xl border text-[12.5px] font-[530] cursor-pointer transition-colors duration-200 hover:bg-white"
          style={{ borderColor: 'var(--stroke)', background: 'var(--g3)', color: 'var(--t1)' }}
        >
          {t('holdBannerViewBooking')}
        </button>
      </div>
    )
  }

  return null
}
