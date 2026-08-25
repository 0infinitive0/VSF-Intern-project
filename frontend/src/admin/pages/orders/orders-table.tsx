import { DataTable, type DataTableColumn } from '../../ui/data-table'
import { DateText } from '../../ui/date-text'
import { Money } from '../../ui/money'
import type { OrderRow } from '../../api/orders-client'
import { BookingStatusChip, PaymentStatusChip } from './order-status-chip'

interface OrdersTableProps {
  rows: OrderRow[]
  onOpenOrder: (paymentId: string) => void
  loading?: boolean
}

const _EXPIRING_SOON_MS = 30 * 60 * 1000

/** Left rail (plan's "Dải màu trái") -- `attention` (paid but booking not
 * fully confirmed, e.g. an IPN that never landed) takes priority over
 * `expiring` (a still-held room about to lose its hold): on this tab the
 * order is already paid, so an unresolved payment/booking mismatch is the
 * more urgent signal than a hold expiry (plan's Success Criteria explicitly
 * calls out the PAID+RESERVED case as the `--warn` rail). */
function rowRailClass(row: OrderRow): string | undefined {
  if (row.needs_attention) return 'row--attention'
  if (row.earliest_expires_at) {
    const msLeft = new Date(row.earliest_expires_at).getTime() - Date.now()
    if (msLeft > 0 && msLeft <= _EXPIRING_SOON_MS) return 'row--expiring'
  }
  return undefined
}

function HotelNamesCell({ names }: { names: string[] }) {
  if (names.length === 0) return <span style={{ color: 'var(--t4)' }}>—</span>
  const [first, ...rest] = names
  return (
    <span>
      {first}
      {rest.length > 0 && <span style={{ color: 'var(--t4)' }}> +{rest.length}</span>}
    </span>
  )
}

export function OrdersTable({ rows, onOpenOrder, loading }: OrdersTableProps) {
  const columns: DataTableColumn<OrderRow>[] = [
    {
      key: 'order_code',
      header: 'MÃ ĐƠN',
      width: 110,
      sortValue: (row) => row.order_code,
      render: (row) => (
        <span className="tabular-nums" title={row.payment_id}>
          {row.order_code}
        </span>
      ),
    },
    {
      key: 'guest',
      header: 'KHÁCH',
      width: 200,
      sortValue: (row) => row.guest_name || '',
      render: (row) => (
        <div style={{ minWidth: 0, padding: '8px 0' }}>
          <div style={{ fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.guest_name || '—'}</div>
          {row.guest_email && (
            <div style={{ fontSize: 11.5, color: 'var(--t3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.guest_email}</div>
          )}
        </div>
      ),
    },
    {
      key: 'hotel',
      header: 'KHÁCH SẠN',
      width: 260,
      sortValue: (row) => row.hotel_names[0] || '',
      render: (row) => <HotelNamesCell names={row.hotel_names} />,
    },
    {
      key: 'dates',
      header: 'NGÀY NHẬN – TRẢ',
      width: 190,
      sortValue: (row) => row.check_in_date || '',
      render: (row) =>
        row.check_in_date && row.check_out_date ? (
          <span className="tabular-nums">
            <DateText value={row.check_in_date} /> – <DateText value={row.check_out_date} />
          </span>
        ) : (
          '—'
        ),
    },
    { key: 'rooms', header: 'PHÒNG', width: 80, align: 'right', sortValue: (row) => row.room_count, render: (row) => row.room_count },
    {
      key: 'amount',
      header: 'TỔNG TIỀN',
      width: 130,
      align: 'right',
      sortValue: (row) => Number(row.amount),
      render: (row) => <Money value={Number(row.amount)} />,
    },
    {
      key: 'booking_status',
      header: 'ĐẶT PHÒNG',
      width: 140,
      sortValue: (row) => row.booking_status,
      render: (row) => <BookingStatusChip status={row.booking_status} />,
    },
    {
      key: 'payment_status',
      header: 'THANH TOÁN',
      width: 140,
      sortValue: (row) => row.payment_status,
      render: (row) => <PaymentStatusChip status={row.payment_status} />,
    },
    {
      key: 'created_at',
      header: 'TẠO LÚC',
      width: 150,
      sortValue: (row) => row.created_at,
      render: (row) => <DateText value={row.created_at} withTime />,
    },
    { key: 'menu', header: '', width: 32, align: 'right', render: () => <span style={{ color: 'var(--t4)' }}>⋯</span> },
  ]

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.payment_id}
      rowClassName={rowRailClass}
      onRowClick={(row) => onOpenOrder(row.payment_id)}
      loading={loading}
    />
  )
}
