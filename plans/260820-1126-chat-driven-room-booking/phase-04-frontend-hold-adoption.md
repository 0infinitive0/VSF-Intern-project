# Phase 4 — Frontend nhận nuôi hold do chat tạo

## Bối cảnh

`use-room-hold.ts` hiện là nơi duy nhất tạo hold: `runReservation` gọi
`reserveBooking` rồi set `bookings`/`heldHotelId`/`heldSessionId`/`status='HELD'`
và ghi sessionStorage. Khi chat tạo hold ở server, FE có sẵn kết quả — chỉ cần
một đường vào state y hệt, không gọi mạng lần nữa.

Nếu bỏ qua bước này: hold vẫn tồn tại trong DB nhưng UI không thấy → không có
banner đếm ngược, không mở được `BookingModal`, và hold nằm chờ hết hạn 15 phút.
(Vẫn an toàn — `delete_session` dọn hold RESERVED qua
`booking_service.cancel_reserved_bookings_for_session` — nhưng vô dụng với user.)

## Yêu cầu

1. `useRoomHold` có `adoptHold(hotelId, bookings, sessionId)` đặt state đúng như
   `runReservation` thành công, không gọi mạng.
2. Giỏ phòng (`cartByHotel`) đồng bộ theo số phòng đã giữ để
   `hotel-detail-panel` không hiện 0 phòng cho khách sạn đang giữ.
3. `App.tsx` gọi `adoptHold` khi response chat có `booking_hold`, đúng một lần
   cho mỗi hold (id không đổi → không nhận nuôi lại).
4. Không tự mở `BookingModal`: hold-banner đã đủ, và mở modal đè lên hội thoại
   là hành vi người dùng không yêu cầu.

## File

| File | Việc |
|---|---|
| `frontend/src/hooks/use-room-hold.ts` | `adoptHold` + đồng bộ cart |
| `frontend/src/App.tsx` | gọi `adoptHold` từ `booking_hold` |
| `frontend/src/hooks/use-chat-session.ts` | đưa `booking_hold` của lượt cuối ra ngoài (nếu state chat chưa có chỗ) |

## Các bước

### 4.1 `adoptHold`

```ts
/** Nhận nuôi một hold do BACKEND tạo trong lượt chat (booking_node) — đặt
 * state y như runReservation vừa thành công, không gọi mạng: reservation đã
 * xảy ra thật rồi, gọi lại sẽ tạo hold thứ hai và đụng guard
 * guest_already_holding_elsewhere. Đây là lý do runReservation và hook này
 * không có nhánh chung: một bên tạo hold, một bên chỉ tiếp nhận. */
const adoptHold = useCallback((hotelId: string, incoming: Booking[], sessionId: string | null) => {
  if (incoming.length === 0) return
  setBookings(incoming)
  setHeldHotelId(hotelId)
  setHeldSessionId(sessionId)
  setStatus('HELD')
  setError(null)
  setPaymentId(null)
  setNow(Date.now())
  setCartByHotel((prev) =>
    incoming.reduce((acc, b) => applyCartQty(acc, hotelId, b.room_id, b.room_count, hotelId), prev),
  )
}, [])
```

Effect ghi sessionStorage sẵn có (`use-room-hold.ts:214-220`) tự chạy theo, nên
hold nhận nuôi cũng sống sót qua vòng redirect VNPay như hold tạo từ panel.

### 4.2 `App.tsx`

Sau mỗi lượt chat, nếu `response.booking_hold` khác null và
`booking_hold.bookings[0].id` chưa từng nhận nuôi (ref lưu id cuối) → gọi
`roomHold.adoptHold(...)`. `heldSessionId` lấy từ `booking_hold.session_id` để
`holdBelongsToSession` (`App.tsx:247`) đúng ngay lập tức.

Nếu FE đang giữ hold khác lúc chat trả về hold mới: không xảy ra trong thực tế —
RPC guard chặn hold thứ hai khác khách sạn, và cùng khách sạn thì `booking_node`
đã báo lỗi trước khi đặt. Vẫn ghi đè state theo dữ liệu server (server là trọng
tài), kèm comment nêu rõ.

### 4.3 Thông điệp trong hội thoại

Không thêm nút xác nhận trong chat: theo yêu cầu, xác nhận là **tin nhắn** của
người dùng. Chip gợi ý sẵn có (`services/suggestions.py`) có thể tự đề xuất
"Đồng ý" — không cần code riêng, vì chip chỉ điền sẵn text vào ô nhập.

## Validation

```bash
cd frontend && npm test -- use-room-hold
```

Test: `adoptHold` cho `status='HELD'`, đếm ngược chạy theo `expires_at` sớm nhất,
cart khớp `room_count`, và **không** có `fetch` nào được gọi.

## Rủi ro & rollback

- Nhận nuôi trùng khi user gửi lại tin nhắn: chặn bằng ref id hold cuối.
- Rollback: bỏ lời gọi `adoptHold` ở `App.tsx` — chat vẫn giữ phòng thật, chỉ là
  UI không phản ánh cho tới khi user thao tác ở panel.
