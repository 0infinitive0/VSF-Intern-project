import { useEffect, useState } from 'react'
import { DataTable, type DataTableColumn } from '../../ui/data-table'
import type { UnpaidBookingRow } from '../../api/orders-client'

interface UnpaidHoldsTableProps {
  rows: UnpaidBookingRow[]
}

const _TICK_MS = 30_000
const _WARN_THRESHOLD_MS = 30 * 60 * 1000

/** `⏱ 4 phút` — plan's three-state chip (đã hết hạn / ≤30 phút / >30 phút).
 * `now` is passed in so every row in one render tick shares the same clock
 * instead of drifting a few ms apart from calling Date.now() per row. */
function ExpiresChip({ expiresAt, now }: { expiresAt: string | null | undefined; now: number }) {
  if (!expiresAt) return <span style={{ color: 'var(--t4)' }}>—</span>
  const msLeft = new Date(expiresAt).getTime() - now
  if (msLeft <= 0) {
    return <span className="chip chip--closed">⏱ Đã hết hạn</span>
  }
  const minutesLeft = Math.ceil(msLeft / 60_000)
  const tone = msLeft <= _WARN_THRESHOLD_MS ? 'err' : 'warn'
  return (
    <span
      className="chip"
      style={{ background: `var(--${tone}-soft)`, color: tone === 'err' ? 'var(--err)' : 'var(--warn-ink)' }}
    >
      ⏱ {minutesLeft} phút
    </span>
  )
}

export function UnpaidHoldsTable({ rows }: UnpaidHoldsTableProps) {
  // Client-side countdown tick -- plan explicitly says this must not
  // re-fetch from the API (`orders-page.tsx`'s own poll stays on its
  // separate 60s stats interval).
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), _TICK_MS)
    return () => clearInterval(timer)
  }, [])

  const columns: DataTableColumn<UnpaidBookingRow>[] = [
    {
      key: 'hold_code',
      header: 'MÃ GIỮ CHỖ',
      render: (row) => (
        <span className="tabular-nums" title={row.booking_id}>
          {row.hold_code}
        </span>
      ),
    },
    { key: 'guest', header: 'KHÁCH', render: (row) => row.guest_label ?? <span style={{ color: 'var(--t4)' }}>—</span> },
    {
      key: 'hotel_room',
      header: 'KHÁCH SẠN · PHÒNG',
      render: (row) => (
        <span>
          {row.hotel_name ?? '—'}
          {row.room_name && <span style={{ color: 'var(--t3)' }}> · {row.room_name}</span>}
        </span>
      ),
    },
    { key: 'expires', header: 'HẾT HẠN SAU', render: (row) => <ExpiresChip expiresAt={row.expires_at} now={now} /> },
    {
      key: 'source',
      header: 'NGUỒN',
      render: (row) =>
        // No admin chat-session viewer exists yet to link to (out of this
        // phase's scope) -- shown as an inert label with the full id in the
        // tooltip rather than a dead link (same "no ngõ cụt" posture as L2).
        row.session_id ? (
          <span title={row.session_id} style={{ color: 'var(--t3)' }}>
            Phiên chat
          </span>
        ) : (
          <span style={{ color: 'var(--t4)' }}>—</span>
        ),
    },
  ]

  return <DataTable columns={columns} rows={rows} rowKey={(row) => row.booking_id} />
}
