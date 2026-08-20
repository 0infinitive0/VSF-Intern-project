# Phase 5 — Test và tài liệu

## Test backend (`backend/tests/`)

| File | Nội dung |
|---|---|
| `test_booking_intent.py` (mới) | `classify_booking_reply`: "ok", "đồng ý", "Đồng ý nhé", "yes" → `confirm`; "thôi", "không", "cancel" → `decline`; "ok cho tôi xem thêm khách sạn khác", "đồng ý với gợi ý ngày 2 nhưng đổi giờ" → `other`; chuỗi rỗng → `other` |
| `test_booking_resolver.py` (mới) | khớp khách sạn theo rank/tên; lấy ngày từ `previous_hotel_search_context` rồi `trip_data`; phòng hết → gap `sold_out`; không có giá → `total_amount is None` (không bịa 0) |
| `test_booking_node.py` (mới) | lượt đề nghị **không** gọi `booking_service` (spy zero-call); `confirm` gọi đúng một `reserve_booking` cho mỗi loại phòng với `session_id` của session; `decline` xoá `pending_booking`; thiếu `guest_ref` → không đặt; lỗi giữa chừng → mọi booking đã tạo đều bị `cancel_booking` |
| `test_graph_v2_skeleton.py` (sửa) | thay `test_booking_node_declines_explicitly` / `..._replies_in_english...` (dòng 196-212) bằng hành vi mới; giữ nguyên tinh thần "không bao giờ im lặng" |
| `test_routing.py` (sửa) | `booking_node` khả dụng khi có hotel options / trip; vẫn impossible khi không có gì để đặt |
| `test_request_field_passthrough.py` (sửa) | `temporary_user_ref` tới được graph state ở cả hai endpoint |
| `test_reply_contract.py` (sửa nếu cần) | `booking_hold` mặc định `None` trên mọi lượt khác |

Chạy: `cd backend && pytest tests -q` (thu hẹp trước, mở rộng sau khi đụng hợp
đồng chung).

## Test frontend

- `use-room-hold.test.ts`: `adoptHold` (Phase 4).
- `stream-client.test.ts` / `chat-client.test.ts`: body chứa `temporary_user_ref`.
- `use-chat-session.test.ts`: `booking_hold` từ frame `final` được đưa ra ngoài.

Chạy: `cd frontend && npm test`.

## Kiểm thử thủ công (không có DB thật thì bỏ qua, ghi rõ đã bỏ)

1. Tìm khách sạn → "đặt phòng Deluxe khách sạn 2" → thấy tóm tắt, DB chưa có row.
2. "đồng ý" → hold-banner hiện, đếm ngược, `bookings` có row `RESERVED`.
3. Bấm "Đặt phòng" → `BookingModal` chạy đúng luồng VNPay hiện tại.
4. Tab khác giữ khách sạn khác → chat báo `guest_already_holding_elsewhere`.
5. Xoá session đang giữ → hold được huỷ (đường sẵn có).

## Tài liệu

| File | Cập nhật |
|---|---|
| `docs/chat_api_contract.md` | `temporary_user_ref` trong request; `booking_hold` trong response + `BookingHoldPayload`; nêu rõ chat chỉ tạo `RESERVED`, `CONFIRMED` vẫn chỉ đến từ IPN VNPay. Nhân tiện sửa dòng 15 (bảng endpoint) đang liệt kê `stay_dates, min_price, max_price` — ba field này đã bị xoá khỏi `PlannerChatRequest` (xem docstring của class), nên tài liệu đang sai trước cả plan này |
| `README.md` / `ARCHITECTURE.md` | chỉ sửa nếu có mô tả "chatbot không đặt phòng được" cần đính chính (kiểm bằng grep trước khi sửa) |

Không viết tài liệu mới cho nội bộ node — docstring trong `booking_node.py`,
`booking_resolver.py`, `booking_intent.py` là nơi đúng, theo văn phong sẵn có của
`backend/src/agents/graph/`.

## Điều kiện hoàn thành

Toàn bộ acceptance criteria ở `index.md` được kiểm bằng test tự động hoặc bằng
kiểm thử thủ công có ghi lại kết quả.
