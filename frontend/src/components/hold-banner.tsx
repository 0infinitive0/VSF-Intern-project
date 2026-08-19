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
        className="flex items-center gap-2 pl-3 pr-1.5 py-1 rounded-full border border-edge transition-all duration-200"
        style={{
          background: 'var(--g1)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 8px 24px -12px rgb(var(--shadow-rgb) / 0.35)',
        }}
      >
        <div className="flex items-center gap-2 pr-0.5">
          <span
            className="w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-bold flex-none text-white"
            style={{
              background: 'linear-gradient(145deg, #4FB3A5, #2A9187)',
              boxShadow: '0 4px 10px -3px rgba(42, 145, 135, 0.6)',
            }}
            aria-hidden="true"
          >
            ✓
          </span>
          <span className="text-[12.5px] font-[590] tracking-[-0.2px] text-on-surface whitespace-nowrap">
            {t('checkoutDoneTitle')}
          </span>
        </div>

        <div className="w-px h-3.5" style={{ background: 'var(--stroke)' }} />

        <button
          type="button"
          onClick={onOpenReceipt}
          className="group flex items-center gap-1 pl-2.5 pr-2 py-1 rounded-full border border-transparent hover:border-edge bg-glass-2 hover:bg-glass-3 text-[12px] font-[590] text-on-surface tracking-[-0.1px] cursor-pointer transition-all duration-200 active:scale-[0.97]"
          style={{ boxShadow: '0 2px 8px -4px rgb(var(--shadow-rgb) / 0.2)' }}
        >
          <span>{t('holdBannerViewBooking')}</span>
          <span
            className="material-symbols-outlined text-[15px] text-on-surface-muted group-hover:text-on-surface group-hover:translate-x-0.5 transition-transform duration-200 leading-none"
            aria-hidden="true"
          >
            arrow_forward
          </span>
        </button>
      </div>
    )
  }

  if (roomHold.status === 'HELD') {
    const warn = roomHold.holdLeftMs <= 5 * 60 * 1000
    const danger = roomHold.holdLeftMs <= 60 * 1000
    return (
      <div
        className="flex items-center gap-2 pl-3 pr-1.5 py-1 rounded-full border transition-all duration-200"
        style={{
          background: danger ? 'var(--err-soft, rgba(192,94,112,.14))' : warn ? 'var(--warn-soft)' : 'var(--g1)',
          borderColor: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--edge)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 8px 24px -12px rgb(var(--shadow-rgb) / 0.35)',
          animation: danger ? 'vPulse 1.6s ease-in-out infinite' : 'none',
        }}
      >
        <div className="flex items-center gap-2 pr-1">
          <span
            className="material-symbols-outlined text-[16px] leading-none"
            style={{ color: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--t2)' }}
            aria-hidden="true"
          >
            schedule
          </span>
          <span className="text-[10px] font-[590] tracking-[0.09em] uppercase text-on-surface-muted">
            {t('holdBannerHeldLabel')}
          </span>
          <span
            className="text-[14px] font-[600] tracking-[-0.2px] tabular-nums"
            style={{ color: danger ? 'var(--err)' : warn ? 'var(--warn)' : 'var(--t1)' }}
          >
            {mmss(roomHold.holdLeftMs)}
          </span>
        </div>

        <div className="w-px h-3.5" style={{ background: 'var(--stroke)' }} />

        <button
          type="button"
          onClick={onOpenBooking}
          className="group flex items-center gap-1 px-3 py-1.5 rounded-full border-none text-[12px] font-[590] tracking-[-0.1px] text-white cursor-pointer transition-all duration-200 hover:opacity-95 hover:shadow-md active:scale-[0.97]"
          style={{
            background: 'linear-gradient(135deg,#3A73DE,#2C5FC9)',
            boxShadow: '0 4px 12px -3px rgba(44,95,201,.55)',
          }}
        >
          <span>{t('holdBannerBook')}</span>
          <span
            className="material-symbols-outlined text-[14px] leading-none group-hover:translate-x-0.5 transition-transform duration-200"
            aria-hidden="true"
          >
            arrow_forward
          </span>
        </button>
      </div>
    )
  }

  if (roomHold.status === 'EXPIRED') {
    return (
      <div
        className="flex items-center gap-2 pl-3 pr-1.5 py-1 rounded-full border border-err/30 transition-all duration-200"
        style={{
          background: 'var(--err-soft, rgba(192,94,112,.12))',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 8px 24px -12px rgb(var(--shadow-rgb) / 0.35)',
        }}
      >
        <div className="flex items-center gap-2 pr-1">
          <span className="material-symbols-outlined text-[16px] text-err leading-none" aria-hidden="true">
            timer_off
          </span>
          <span className="text-[12px] font-[590] text-err tracking-[-0.1px]">
            {t('holdBannerExpiredTitle')}
          </span>
        </div>

        <div className="w-px h-3.5" style={{ background: 'var(--stroke)' }} />

        <button
          type="button"
          onClick={() => void roomHold.recheckRooms()}
          className="flex items-center gap-1 px-3 py-1.5 rounded-full border-none text-[12px] font-[590] tracking-[-0.1px] text-white cursor-pointer transition-all duration-200 hover:opacity-95 active:scale-[0.97]"
          style={{ background: 'var(--err)', boxShadow: '0 4px 12px -3px rgba(192,94,112,.5)' }}
        >
          {t('holdBannerRecheck')}
        </button>
      </div>
    )
  }

  if (roomHold.status === 'BOOKED') {
    return (
      <div
        className="flex items-center gap-2 pl-3 pr-1.5 py-1 rounded-full border border-edge transition-all duration-200"
        style={{
          background: 'var(--g1)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          boxShadow: '0 8px 24px -12px rgb(var(--shadow-rgb) / 0.35)',
        }}
      >
        <div className="flex items-center gap-2 pr-0.5">
          <span
            className="w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-bold flex-none text-white"
            style={{
              background: 'linear-gradient(145deg, #4FB3A5, #2A9187)',
              boxShadow: '0 4px 10px -3px rgba(42, 145, 135, 0.6)',
            }}
            aria-hidden="true"
          >
            ✓
          </span>
          <span className="text-[12.5px] font-[590] tracking-[-0.2px] text-on-surface whitespace-nowrap">
            {t('checkoutDoneTitle')}
          </span>
        </div>

        <div className="w-px h-3.5" style={{ background: 'var(--stroke)' }} />

        <button
          type="button"
          onClick={onOpenBooking}
          className="group flex items-center gap-1 pl-2.5 pr-2 py-1 rounded-full border border-transparent hover:border-edge bg-glass-2 hover:bg-glass-3 text-[12px] font-[590] text-on-surface tracking-[-0.1px] cursor-pointer transition-all duration-200 active:scale-[0.97]"
          style={{ boxShadow: '0 2px 8px -4px rgb(var(--shadow-rgb) / 0.2)' }}
        >
          <span>{t('holdBannerViewBooking')}</span>
          <span
            className="material-symbols-outlined text-[15px] text-on-surface-muted group-hover:text-on-surface group-hover:translate-x-0.5 transition-transform duration-200 leading-none"
            aria-hidden="true"
          >
            arrow_forward
          </span>
        </button>
      </div>
    )
  }

  return null
}
