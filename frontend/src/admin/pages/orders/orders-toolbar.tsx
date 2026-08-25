import { Input } from '../../ui/input'
import { Select } from '../../ui/select'
import type { BookingStatusKey, PaymentStatusKey } from './order-status-chip'

export interface HotelOption {
  id: string
  name: string
}

interface OrdersToolbarProps {
  q: string
  onQChange: (q: string) => void
  bookingStatus: BookingStatusKey | undefined
  onBookingStatusChange: (status: BookingStatusKey | undefined) => void
  paymentStatus: PaymentStatusKey | undefined
  onPaymentStatusChange: (status: PaymentStatusKey | undefined) => void
  hotelId: string | undefined
  onHotelIdChange: (hotelId: string | undefined) => void
  hotels: HotelOption[]
  from: string
  to: string
  onFromChange: (value: string) => void
  onToChange: (value: string) => void
  shownCount: number
  totalCount: number
}

/** D1's tab-1 toolbar (phase-04-orders-list.md). Tab 2 has no toolbar in the
 * design -- just a summary line -- so this component is only rendered for
 * the "Đơn hàng" tab. */
export function OrdersToolbar({
  q,
  onQChange,
  bookingStatus,
  onBookingStatusChange,
  paymentStatus,
  onPaymentStatusChange,
  hotelId,
  onHotelIdChange,
  hotels,
  from,
  to,
  onFromChange,
  onToChange,
  shownCount,
  totalCount,
}: OrdersToolbarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div style={{ flex: 1, minWidth: 220, maxWidth: 320 }}>
        <Input placeholder="⌕ Email hoặc số điện thoại khách…" value={q} onChange={(e) => onQChange(e.target.value)} />
      </div>

      <Select
        value={bookingStatus ?? 'all'}
        onChange={(e) => onBookingStatusChange(e.target.value === 'all' ? undefined : (e.target.value as BookingStatusKey))}
        style={{ width: 190 }}
      >
        <option value="all">Trạng thái đơn: Tất cả</option>
        <option value="PENDING">Trạng thái đơn: Chờ xác nhận</option>
        <option value="RESERVED">Trạng thái đơn: Đang giữ chỗ</option>
        <option value="CONFIRMED">Trạng thái đơn: Đã xác nhận</option>
        <option value="MIXED">Trạng thái đơn: Một phần</option>
        <option value="CANCELLED">Trạng thái đơn: Đã huỷ</option>
        <option value="EXPIRED">Trạng thái đơn: Hết hạn giữ</option>
      </Select>

      <Select
        value={paymentStatus ?? 'all'}
        onChange={(e) => onPaymentStatusChange(e.target.value === 'all' ? undefined : (e.target.value as PaymentStatusKey))}
        style={{ width: 170 }}
      >
        <option value="all">Thanh toán: Tất cả</option>
        <option value="PENDING">Thanh toán: Chờ thanh toán</option>
        <option value="PAID">Thanh toán: Đã thanh toán</option>
        <option value="FAILED">Thanh toán: Thất bại</option>
        <option value="CANCELLED">Thanh toán: Đã huỷ</option>
      </Select>

      <Select value={hotelId ?? 'all'} onChange={(e) => onHotelIdChange(e.target.value === 'all' ? undefined : e.target.value)} style={{ width: 190 }}>
        <option value="all">Khách sạn: Tất cả</option>
        {hotels.map((hotel) => (
          <option key={hotel.id} value={hotel.id}>
            {hotel.name}
          </option>
        ))}
      </Select>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <Input type="date" value={from} max={to || undefined} onChange={(e) => onFromChange(e.target.value)} style={{ width: 145 }} />
        <span style={{ color: 'var(--t4)' }}>–</span>
        <Input type="date" value={to} min={from || undefined} onChange={(e) => onToChange(e.target.value)} style={{ width: 145 }} />
      </div>

      <div style={{ flex: 1 }} />

      <span className="tabular-nums" style={{ fontSize: 12.5, color: 'var(--t3)', whiteSpace: 'nowrap' }}>
        Hiển thị {shownCount} / {totalCount} đơn
      </span>
    </div>
  )
}
