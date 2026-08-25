import { useEffect, useState } from 'react'
import { DateText } from '../../ui/date-text'
import type { OrderTimelineEvent } from '../../api/orders-client'

const TITLE_BY_KIND: Record<OrderTimelineEvent['kind'], string> = {
  created: 'Đơn được tạo từ phiên chat',
  reserved: 'Giữ chỗ',
  paid: 'Thanh toán VNPay thành công',
  cancelled: 'Đã huỷ',
  expired: 'Hết hạn giữ chỗ',
  confirmed: 'Đã xác nhận đơn',
  awaiting_admin: 'Chờ admin xác nhận',
}

function pad2(n: number): string {
  return String(Math.max(n, 0)).padStart(2, '0')
}

/** `00:12:41` countdown to `expiresAt`, ticking every second (plan's exact
 * shape) -- once it reaches zero it freezes on "Đã hết hạn" instead of
 * calling any API (this screen is read-only). */
function HoldCountdown({ expiresAt }: { expiresAt: string }) {
  const [msLeft, setMsLeft] = useState(() => new Date(expiresAt).getTime() - Date.now())

  useEffect(() => {
    setMsLeft(new Date(expiresAt).getTime() - Date.now())
    const id = setInterval(() => {
      const remaining = new Date(expiresAt).getTime() - Date.now()
      setMsLeft(remaining)
      if (remaining <= 0) clearInterval(id)
    }, 1000)
    return () => clearInterval(id)
  }, [expiresAt])

  if (msLeft <= 0) {
    return <span style={{ color: 'var(--t3)' }}>Đã hết hạn</span>
  }
  const totalSeconds = Math.floor(msLeft / 1000)
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  return (
    <span className="tabular-nums">
      Hết hạn giữ chỗ sau {pad2(h)}:{pad2(m)}:{pad2(s)}
    </span>
  )
}

function elapsedLabel(since: string): string {
  const ms = Math.max(Date.now() - new Date(since).getTime(), 0)
  const totalMinutes = Math.floor(ms / 60000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours <= 0) return `${minutes} phút`
  return `${hours} giờ ${minutes} phút`
}

/** Live elapsed duration for the "đang chờ" milestone -- minute-granularity
 * is enough here (unlike HoldCountdown's second-precision), so a 60s tick
 * is enough to keep it from going stale on a long-open tab. */
function AwaitingSince({ since }: { since: string }) {
  const [, forceTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 60_000)
    return () => clearInterval(id)
  }, [])
  return <span className="tabular-nums">Đang chờ · {elapsedLabel(since)}</span>
}

function TimelineDot({ kind }: { kind: OrderTimelineEvent['kind'] }) {
  if (kind === 'awaiting_admin') {
    return <span className="order-timeline__dot" style={{ border: '2px solid var(--warn)', background: 'transparent' }} />
  }
  const color =
    kind === 'created' ? 'var(--t4)' : kind === 'reserved' ? 'var(--acc)' : kind === 'paid' || kind === 'confirmed' ? 'var(--ok)' : 'var(--err)'
  return <span className="order-timeline__dot" style={{ background: color }} />
}

function TimelineNote({ event }: { event: OrderTimelineEvent }) {
  if (event.kind === 'reserved' && event.expires_at) {
    return (
      <div className="order-timeline__note" style={{ background: 'var(--warn-soft)', color: 'var(--warn-ink)' }}>
        <HoldCountdown expiresAt={event.expires_at} />
      </div>
    )
  }
  if (event.kind === 'awaiting_admin') {
    return (
      <div className="order-timeline__note" style={{ background: 'var(--fill)', color: 'var(--t2)' }}>
        Bước tiếp theo: Xác nhận đơn hoặc Huỷ đơn
      </div>
    )
  }
  return null
}

function TimelineTime({ event }: { event: OrderTimelineEvent }) {
  if (event.kind === 'awaiting_admin') {
    return event.since ? <AwaitingSince since={event.since} /> : null
  }
  if (!event.at) return null
  return <DateText value={event.at} withTime />
}

function titleFor(event: OrderTimelineEvent): string {
  const base = TITLE_BY_KIND[event.kind]
  if (event.room_count != null && (event.kind === 'reserved' || event.kind === 'cancelled' || event.kind === 'expired')) {
    return `${base} ${event.room_count} phòng`
  }
  return base
}

/** order-timeline.tsx — D2's "Dòng thời gian" (phase-05-order-detail.md):
 * 11px dots + a 1px `--stroke` connector, the last (always "đang chờ") milestone
 * hollow with no trailing connector. */
export function OrderTimeline({ events }: { events: OrderTimelineEvent[] }) {
  return (
    <div className="order-timeline">
      {events.map((event, index) => (
        <div className="order-timeline__item" key={`${event.kind}-${index}`}>
          <div className="order-timeline__rail">
            <TimelineDot kind={event.kind} />
            {index < events.length - 1 && <span className="order-timeline__connector" />}
          </div>
          <div className="order-timeline__body">
            <div className="order-timeline__title">{titleFor(event)}</div>
            <div className="order-timeline__time">
              <TimelineTime event={event} />
            </div>
            <TimelineNote event={event} />
          </div>
        </div>
      ))}
    </div>
  )
}
