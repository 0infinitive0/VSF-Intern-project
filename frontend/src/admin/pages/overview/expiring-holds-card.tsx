import { useEffect, useState } from 'react'
import type { OverviewExpiringHold } from '../../api/overview-client'
import { EmptyState } from '../../ui/empty-state'

interface ExpiringHoldsCardProps {
  holds: OverviewExpiringHold[] | null
}

const _TICK_MS = 30_000
const _WARN_THRESHOLD_MS = 30 * 60 * 1000

/** Same 3-state countdown chip as D1 tab 2's unpaid-holds-table.tsx
 * (⏱ đã hết hạn / ≤30 phút / >30 phút) -- kept local rather than imported
 * since that file doesn't export it, but the shapes and thresholds match
 * exactly. */
function SkeletonRows() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {Array.from({ length: 3 }, (_, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 0 }}>
            <div className="skeleton-bar" style={{ width: 140, height: 10 }} />
            <div className="skeleton-bar" style={{ width: 100, height: 9 }} />
          </div>
          <div className="skeleton-bar" style={{ width: 56, height: 18, borderRadius: 999 }} />
        </div>
      ))}
    </div>
  )
}

function ExpiresChip({ expiresAt, now }: { expiresAt: string | null | undefined; now: number }) {
  if (!expiresAt) return <span style={{ color: 'var(--t4)' }}>—</span>
  const msLeft = new Date(expiresAt).getTime() - now
  if (msLeft <= 0) return <span className="chip chip--closed">⏱ Đã hết hạn</span>
  const minutesLeft = Math.ceil(msLeft / 60_000)
  const tone = msLeft <= _WARN_THRESHOLD_MS ? 'err' : 'warn'
  return (
    <span className={`chip chip--${tone}`}>
      ⏱ {minutesLeft} phút
    </span>
  )
}

/** expiring-holds-card.tsx — A3's "Giữ chỗ sắp hết hạn" block (phase-17-
 * overview-kpi.md). Countdown ticks client-side every 30s, independent of
 * the page's own 60s data poll (plan's explicit split). */
export function ExpiringHoldsCard({ holds }: ExpiringHoldsCardProps) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), _TICK_MS)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>Giữ chỗ sắp hết hạn</div>
        {holds && holds.length > 0 && (
          <span className="tabular-nums" style={{ fontSize: 12, color: 'var(--t3)' }}>
            {holds.length}
          </span>
        )}
      </div>

      {holds === null && <SkeletonRows />}

      {holds !== null && holds.length === 0 && (
        <EmptyState title="✓ Không có giữ chỗ nào sắp hết hạn." description="Chưa có khách nào giữ chỗ sắp hết hạn." />
      )}

      {holds !== null &&
        holds.map((hold) => (
          <div key={hold.booking_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: 12.5 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 600 }}>
                {hold.hold_code} · {hold.guest_label ?? '—'}
              </div>
              <div style={{ color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {hold.hotel_name ?? '—'}
                {hold.room_name && ` · ${hold.room_name}`}
              </div>
            </div>
            <ExpiresChip expiresAt={hold.expires_at} now={now} />
          </div>
        ))}
    </div>
  )
}
