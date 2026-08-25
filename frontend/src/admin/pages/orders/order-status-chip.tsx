/**
 * order-status-chip.tsx — D1's `BK`/`PAY` status vocabulary (phase-04-
 * orders-list.md), copied verbatim from the design's chip table: same
 * labels, same tone. Reuses the existing `.chip`/`.chip--*` classes from
 * status-chip.tsx's stylesheet (admin.css) — this file only adds the
 * label/tone mapping specific to bookings and payments, plus the two
 * one-off treatments (line-through, soft border) the shared `.chip--*`
 * classes don't cover.
 *
 * Two additions beyond the design mock, both called out in the plan:
 * - `BK.MIXED` ("⚠ Một phần") — a multi-room order partially cancelled is a
 *   real state the design never drew a chip for.
 * - `PAY.CANCELLED` (L1) — the design's `PAY.REFUNDED` chip has no backing
 *   column (`payments.status` CHECK has no REFUNDED); `CANCELLED` is the
 *   real value that needs a chip instead.
 */
export type BookingStatusKey = 'PENDING' | 'RESERVED' | 'CONFIRMED' | 'CANCELLED' | 'EXPIRED' | 'MIXED' | 'UNKNOWN'
export type PaymentStatusKey = 'PAID' | 'PENDING' | 'FAILED' | 'NONE' | 'CANCELLED'

interface ChipDef {
  label: string
  tone: 'pending' | 'held' | 'ok' | 'closed'
  lineThrough?: boolean
  softBorder?: boolean
}

export const BK: Record<BookingStatusKey, ChipDef> = {
  PENDING: { label: '◔ Chờ xác nhận', tone: 'pending' },
  RESERVED: { label: '◑ Đang giữ chỗ', tone: 'held' },
  CONFIRMED: { label: '✓ Đã xác nhận', tone: 'ok' },
  CANCELLED: { label: '✕ Đã huỷ', tone: 'closed', lineThrough: true },
  EXPIRED: { label: '⏱ Hết hạn giữ', tone: 'closed' },
  MIXED: { label: '⚠ Một phần', tone: 'pending' },
  // The view's CASE falls through to UNKNOWN only when a payment's
  // booking_ids point at zero live booking rows -- not in the design mock
  // (shouldn't happen given payments' own CHECK constraint), kept here so a
  // stray row renders a chip instead of crashing the table.
  UNKNOWN: { label: '? Không rõ', tone: 'closed' },
}

export const PAY: Record<PaymentStatusKey, ChipDef> = {
  PAID: { label: '✓ Đã thanh toán', tone: 'ok' },
  PENDING: { label: '◔ Chờ thanh toán', tone: 'pending' },
  FAILED: { label: '✕ Thất bại', tone: 'closed', softBorder: true },
  NONE: { label: '— Chưa có', tone: 'closed' },
  CANCELLED: { label: '✕ Đã huỷ', tone: 'closed' },
}

function renderChip(def: ChipDef) {
  return (
    <span
      className={`chip chip--${def.tone}`}
      style={{
        textDecoration: def.lineThrough ? 'line-through' : undefined,
        boxShadow: def.softBorder ? 'inset 0 0 0 1px rgba(192,94,112,.35)' : undefined,
      }}
    >
      {def.label}
    </span>
  )
}

export function BookingStatusChip({ status }: { status: BookingStatusKey }) {
  // Falls back rather than throwing on a value outside the known set (e.g.
  // a future bookings.status this file hasn't been updated for yet) -- a
  // degraded chip beats crashing the whole table.
  return renderChip(BK[status] ?? BK.UNKNOWN)
}

export function PaymentStatusChip({ status }: { status: PaymentStatusKey }) {
  return renderChip(PAY[status] ?? PAY.NONE)
}
