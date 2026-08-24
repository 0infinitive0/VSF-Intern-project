import { Button } from '../../../ui/button'

interface RoomsEmptyProps {
  onAddRoom: () => void
}

/** rooms-empty.tsx -- B5's 0-room empty state (phase-10-rooms.md). Names the
 * consequence ("chưa thể bán") instead of a generic "chưa có dữ liệu": a
 * hotel with zero rooms cannot be sold (`bookings.room_id` is
 * `NOT NULL`/`ON DELETE RESTRICT`) and the bot never recommends it. */
export function RoomsEmpty({ onAddRoom }: RoomsEmptyProps) {
  return (
    <div className="state-block">
      <div className="state-block__icon state-block__icon--warn">!</div>
      <div className="state-block__title">Khách sạn chưa có phòng — chưa thể bán</div>
      <div className="state-block__desc">
        Bot sẽ không gợi ý khách sạn này cho khách vì không có phòng nào để đặt. Thêm ít nhất một phòng kèm giá theo
        ngày.
      </div>
      <Button variant="primary" size="sm" onClick={onAddRoom}>
        + Thêm phòng đầu tiên
      </Button>
    </div>
  )
}
