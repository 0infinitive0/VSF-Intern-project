import { DateText } from '../../ui/date-text'
import { Money } from '../../ui/money'
import type { OrderDetailResponse, OrderRoomLine } from '../../api/orders-client'

/** Room-line status chip -- distinct wording from order-status-chip.tsx's
 * `BookingStatusChip` (design's D2 mock says "Còn phòng"/"Đang giữ", not
 * D1's "Đã xác nhận"/"Đang giữ chỗ") but reuses the same `.chip--*` tone
 * classes so the color vocabulary still matches everywhere else. */
const ROOM_CHIP: Record<OrderRoomLine['status'], { label: string; tone: 'ok' | 'held' | 'closed' | 'pending' }> = {
  CONFIRMED: { label: '✓ Còn phòng', tone: 'ok' },
  RESERVED: { label: '◑ Đang giữ', tone: 'held' },
  PENDING: { label: '◔ Chờ xử lý', tone: 'pending' },
  CANCELLED: { label: '✕ Đã huỷ', tone: 'closed' },
  EXPIRED: { label: '⏱ Hết hạn giữ', tone: 'closed' },
}

function RoomLine({ room }: { room: OrderRoomLine }) {
  const chip = ROOM_CHIP[room.status]
  // `≈` cue (risk table: VND has no smaller unit than đồng) -- shown only
  // when the rounded unit price doesn't reconstruct the exact total.
  const isApprox = Number(room.unit_price) * room.nights * room.room_count !== Number(room.total_amount)
  return (
    <div className="order-room-line">
      <div className="order-room-line__top">
        <div style={{ minWidth: 0 }}>
          <div className="order-room-line__hotel">{room.hotel_name || '—'}</div>
          <div className="order-room-line__room">
            {room.room_name || '—'}
            {room.max_guests != null && ` · ${room.max_guests} người`}
          </div>
          <div className="order-room-line__meta">
            <DateText value={room.check_in_date} /> → <DateText value={room.check_out_date} /> · {room.nights} đêm ·{' '}
            {isApprox && '≈'}
            <Money value={Number(room.unit_price)} />
            /đêm
          </div>
        </div>
        <div className="order-room-line__total">
          <Money value={Number(room.total_amount)} />
        </div>
      </div>
      <div style={{ marginTop: 8 }}>
        <span className={`chip chip--${chip.tone}`}>{chip.label}</span>
      </div>
    </div>
  )
}

export function OrderRoomsCard({ order }: { order: OrderDetailResponse }) {
  const nights = order.rooms.length > 0 ? Math.max(...order.rooms.map((r) => r.nights)) : 0
  // Sum of room_count, not the booking-line count -- matches the timeline's
  // "Giữ chỗ N phòng" and D1's list column, both of which sum room_count
  // too. A single line with room_count=2 must read "2 phòng" here as well,
  // not "1 phòng".
  const totalRoomCount = order.rooms.reduce((sum, r) => sum + r.room_count, 0)
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ fontSize: 13.5, fontWeight: 700 }}>Phòng trong đơn</div>
      <div style={{ fontSize: 11.5, color: 'var(--t4)', marginTop: 2 }}>
        {totalRoomCount} phòng · {nights} đêm
      </div>

      <div style={{ marginTop: 10 }}>
        {order.rooms.map((room) => (
          <RoomLine key={room.booking_id} room={room} />
        ))}
      </div>

      <div style={{ marginTop: 4, paddingTop: 4 }}>
        <div className="order-totals-row">
          <span>Tạm tính</span>
          <Money value={Number(order.totals.subtotal)} />
        </div>
        {order.totals.fee != null && (
          <div className="order-totals-row">
            <span>Thuế &amp; phí dịch vụ</span>
            <Money value={Number(order.totals.fee)} />
          </div>
        )}
        <div className="order-totals-row order-totals-row--total">
          <span>Tổng tiền</span>
          <Money value={Number(order.totals.total)} />
        </div>
      </div>
    </div>
  )
}
