/**
 * status-chip.tsx — the one status→color mapping every screen must use
 * (plan's "Bảng màu trạng thái", dùng nhất quán ở MỌI màn). Always renders
 * a text label alongside the color -- never color-only.
 */
export type ChipStatus =
  | 'PENDING'
  | 'RESERVED'
  | 'CONFIRMED'
  | 'PAID'
  | 'CANCELLED'
  | 'FAILED'
  | 'EXPIRED'

const TONE_BY_STATUS: Record<ChipStatus, 'pending' | 'held' | 'ok' | 'closed'> = {
  PENDING: 'pending',
  RESERVED: 'held',
  CONFIRMED: 'ok',
  PAID: 'ok',
  CANCELLED: 'closed',
  FAILED: 'closed',
  EXPIRED: 'closed',
}

interface StatusChipProps {
  status: ChipStatus
  label: string
}

export function StatusChip({ status, label }: StatusChipProps) {
  return <span className={`chip chip--${TONE_BY_STATUS[status]}`}>{label}</span>
}
