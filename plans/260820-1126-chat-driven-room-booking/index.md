# Đặt phòng qua chatbot (có cổng xác nhận)

Status: DRAFT — chưa thực thi
Branch gốc: `main`
Ngày: 2026-08-20

## Outcome

Người dùng giữ được phòng (`RESERVED` hold 15 phút) **bằng hội thoại**, không cần
mở panel khách sạn: chatbot tóm tắt phòng/ngày/số lượng/giá → hỏi xác nhận →
chỉ khi người dùng trả lời đồng ý ("ok", "đồng ý", "yes", "xác nhận"…) mới gọi
`create_booking_reservation` thật. Thanh toán vẫn đi qua `BookingModal` + VNPay
như hiện nay (quyết định phạm vi của user, 2026-08-20).

## Feasibility: KHẢ THI — hạ tầng đã có thật, chỉ thiếu đường dẫn từ chat

Đã kiểm chứng bằng đọc mã:

| Thành phần | Trạng thái |
|---|---|
| RPC giữ/xác nhận/huỷ phòng | Có thật — `backend/scripts/migrations/20260818_add_booking_reservation_rpcs.sql`, TTL mặc định 15 phút, guard 1 guest chỉ giữ 1 khách sạn (`20260819_add_guest_single_hotel_hold_guard.sql`) |
| Service | `backend/src/services/booking_service.py` (`reserve_booking`/`confirm_booking`/`cancel_booking`), lỗi domain đã phân loại sẵn |
| REST | `POST /bookings`, `/bookings/{id}/confirm|cancel`, `POST /payments/vnpay`, IPN — `backend/src/api/routes.py:226-401` |
| UI hold + thanh toán | `frontend/src/hooks/use-room-hold.ts`, `components/booking-modal.tsx`, `components/hold-banner.tsx` |
| Dữ liệu phòng cho agent | `services/place_details.get_hotel_detail(hotel_id, check_in, check_out)` — đúng nguồn mà room card đang dùng, có `id`, `price`, `available_room_count` |
| Đường từ chat tới booking | **CHƯA CÓ** — `agents/graph/routing.py:69` đặt `_IMPOSSIBLE["booking_node"] = True`; `nodes/booking_node.py` chỉ trả lời từ chối; `nodes/extract_patch.py:101` chưa có intent `booking` |
| Danh tính khách trong chat | **CHƯA CÓ** — `temporary_user_ref` chỉ nằm ở localStorage trình duyệt (`frontend/src/lib/guest-ref.ts`); `PlannerChatRequest` (`models/schemas.py:382`) chỉ có `session_id`/`message`/`language` |

Nói cách khác: không cần schema DB mới, không cần RPC mới, không đụng luồng
thanh toán. Việc phải làm là (1) mở route intent → `booking_node`, (2) một cổng
xác nhận 2 lượt có trạng thái, (3) đưa `temporary_user_ref` vào request chat và
đưa hold vừa tạo ra response để frontend "nhận nuôi".

## Bất biến phải giữ

1. **`CONFIRMED` = đã trả tiền.** Chỉ IPN VNPay được gọi `confirm_booking`
   (`routes.py:343`, `session_store.booking_states_for_sessions`,
   `hotel_node` `already_paid` lock). Chat **không bao giờ** gọi confirm.
2. **Không bịa dữ liệu.** Không tự sinh `temporary_user_ref` phía backend (FE sẽ
   không huỷ/thanh toán được hold đó); không bịa giá — chỉ gửi `total_amount`
   khi phòng có giá thật, đúng như `use-room-hold.ts:294`.
3. **Không hành động khi mơ hồ.** Chuỗi xác nhận nhận diện bằng luật xác định
   (deterministic), không LLM. Nghi ngờ → không đặt, hỏi lại.
4. **Một hold cho một khách.** Guard `guest_already_holding_elsewhere` là trọng
   tài; chat báo lỗi, không tự huỷ hold cũ.
5. **Turn đặt phòng không được đụng kế hoạch.** `budget_check` có thể chạy re-plan
   (tìm lại khách sạn + rebuild ngày) và ghi đè `task_results[-1]` — cạnh
   `booking_node → budget_check` hiện tại phải đổi sang `respond`.

## Non-goals

- Thu thập tên/email/SĐT và tạo link VNPay trong chat (option B, user đã loại).
- Chat gọi `confirm_booking` bỏ qua thanh toán (option C, phá bất biến #1).
- Đăng nhập/tài khoản cho booking; vẫn là guest ref ẩn danh.
- Sửa/huỷ hold bằng chat (huỷ vẫn ở hold-banner). Có thể là plan sau.
- Đặt tour/vé; chỉ phòng khách sạn.

## Acceptance criteria

- [ ] "đặt phòng Deluxe khách sạn 2 cho tôi" → bot tóm tắt (khách sạn, tên phòng,
      ngày nhận/trả, số phòng, tổng tiền nếu biết) và hỏi xác nhận; **không có**
      row `bookings` nào được tạo ở lượt này.
- [ ] Lượt kế tiếp trả lời "ok"/"đồng ý"/"yes" → tạo hold thật, reply nêu thời
      hạn giữ phòng và hướng dẫn bấm "Đặt phòng" để thanh toán.
- [ ] Trả lời "thôi"/"không" → xoá đề nghị, không tạo hold, bot xác nhận đã huỷ.
- [ ] Tin nhắn không phải xác nhận ("thời tiết Đà Nẵng thế nào?") khi đang có đề
      nghị treo → đi tuyến bình thường (qa_node), không tạo hold.
- [ ] Hold do chat tạo hiện đúng trên `hold-banner` với đếm ngược, và
      `BookingModal` thanh toán được y như hold tạo từ panel.
- [ ] Hết phòng / hết hạn / đang giữ khách sạn khác → thông báo tiếng Việt (hoặc
      EN theo `language`), không stack trace, không hold mồ côi.
- [ ] Không có `temporary_user_ref` trong request → bot nói chưa đặt được qua chat
      và chỉ sang panel; không tạo booking nào.
- [ ] `pytest backend/tests` xanh; `npm test` (frontend) xanh.

## Phases

| # | Phase | Phụ thuộc | File |
|---|---|---|---|
| 1 | Backend: intent `booking`, mở route, resolver đề nghị đặt phòng | — | [phase-01-booking-intent-and-proposal.md](phase-01-booking-intent-and-proposal.md) |
| 2 | Backend: cổng xác nhận xác định + giữ phòng thật + lỗi | 1 | [phase-02-confirmation-gate-and-reservation.md](phase-02-confirmation-gate-and-reservation.md) |
| 3 | Hợp đồng API: `temporary_user_ref` vào, `booking_hold` ra (chat + stream) | 1 | [phase-03-api-contract-guest-ref.md](phase-03-api-contract-guest-ref.md) |
| 4 | Frontend: nhận nuôi hold do chat tạo | 3 | [phase-04-frontend-hold-adoption.md](phase-04-frontend-hold-adoption.md) |
| 5 | Test + tài liệu | 1-4 | [phase-05-tests-and-docs.md](phase-05-tests-and-docs.md) |

Phase 1 và 3 độc lập file (graph nodes vs schemas/routes) → chạy song song được;
2 và 4 nối tiếp.

## Quyết định thiết kế

| Quyết định | Lý do |
|---|---|
| Đề nghị treo (`pending_booking`) nằm ở `TravelGraphState`, không nằm trong `travel_state` | `travel_state` round-trip qua `TravelState.from_dict/to_dict` mỗi lượt và chỉ giữ `ALLOWED_PATHS` → sẽ mất sau 1 lượt (đúng lý do `trip_data` nằm ngoài, `state.py:149-158`) |
| Nhận diện "đồng ý/từ chối" bằng bảng từ khoá + giới hạn độ dài, không LLM | Hành động có hệ quả tiền bạc; false-positive tệ hơn false-negative nhiều. Cùng lập trường "không hỏi model điều code đã trả lời được" (`supervisor.py` docstring) |
| `temporary_user_ref` truyền từ FE trong request chat | Backend tự sinh ref sẽ tạo hold mà FE không huỷ/thanh toán được (`guest-ref.ts` là nguồn sự thật của trình duyệt) |
| `booking_node` → `respond` thay vì `budget_check` | `budget_check` có thể re-plan và ghi đè `task_results[-1]` (cùng lý do `route_after_itinerary_node` tồn tại, `routing.py:104-121`) |
| Không thêm phase key streaming cho `booking_node` | Node không gọi LLM, xong trước khi người dùng đọc kịp — đúng chính sách `phase_keys.py` |
| Re-resolve giá/tồn phòng ngay trước khi giữ | Tồn phòng đổi giữa 2 lượt; RPC là trọng tài cuối nhưng tóm tắt đã đọc cho user không được sai |

## Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Nhận nhầm "ok" trong câu dài thành xác nhận | Chỉ nhận cụm ngắn (≤4 token sau chuẩn hoá) khớp whitelist; còn lại rơi về tuyến thường |
| Đề nghị treo bị "sống dai" và bị xác nhận nhầm nhiều lượt sau | `expires_at` 10 phút trong `pending_booking` + xoá khi user đổi khách sạn/ngày |
| Hold tạo bởi chat nhưng FE không biết → hold mồ côi tới khi hết hạn | Phase 4: `adoptHold` từ `booking_hold` trong response; kể cả FE lỗi thì hold vẫn tự hết hạn 15 phút và `delete_session` vẫn dọn (`booking_service.cancel_reserved_bookings_for_session`) |
| Hai tab / vừa panel vừa chat cùng giữ | RPC guard `guest_already_holding_elsewhere` chặn; chat báo lại, không tự huỷ |
| Test hiện có khoá hành vi cũ | `backend/tests/test_graph_v2_skeleton.py:196-212` (booking_node decline) và test routing phải cập nhật có chủ đích trong Phase 5 |

## Quyết định đã chốt (user, 2026-08-20)

1. **Đang giữ phòng khách sạn A mà nhắn đặt B → chỉ báo lỗi.** Không tự huỷ hold
   cũ, không thêm lượt xác nhận "đổi". Trọng tài là guard
   `guest_already_holding_elsewhere` của RPC; chat chỉ diễn giải lỗi đó thành
   câu chữ và chỉ user sang thanh hold để tự huỷ.
2. **Số phòng suy từ `people`** khi user không nói rõ:
   `ceil(people / room.max_guests)`, chặn dưới 1. `max_guests` không có →
   1 phòng. Tóm tắt luôn nói rõ đã suy ra bao nhiêu phòng để user sửa được.
