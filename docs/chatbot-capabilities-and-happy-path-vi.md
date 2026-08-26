# Khả năng của Chatbot & Kịch bản Happy Case

Tài liệu mô tả **chính xác những gì chatbot V-OTA làm được / không làm được** theo code đang chạy trên `main`, và một **kịch bản happy case** chạy xuyên suốt từ lúc mở phiên tới lúc chốt lịch trình.

Nguồn: `backend/src/agents/graph/` (14 node LangGraph), `backend/src/api/routes.py`, `backend/src/services/`, `docs/chat_api_contract.md`, `docs/architecture/booking_and_payment_workflow_vi.md`.

---

## Phần 1 — Khả năng của chatbot

### 1.1 Kiến trúc một lượt chat (14 node)

```
START → load_context → scope_guard → extract_patch → validate_patch → apply_patch → ask_slot
                                          │                                            │
                                    (jailbreak → respond)              ┌───────────────┼──────────────┐
                                                                    "ask"         "intake_qa"    "supervisor"
                                                                      │               │               │
                                                                      └──→ respond ←──┘               ▼
                                                                                              hotel_node / itinerary_node
                                                                                              booking_node / qa_node
                                                                                                      │
                                                                                          budget_check → respond → END
```

- **Patch pipeline luôn chạy trước** — mọi thông tin người dùng nói trong lượt này được commit vào `TravelState` *trước khi* hệ thống hỏi tiếp. Nhờ vậy một câu hỏi đang treo không bao giờ chặn được một dữ kiện không liên quan (chống deadlock intake).
- **Supervisor (LLM) chỉ chọn worker**, không tự quyết định nội dung; thứ tự cố định khi nhiều workflow bị ảnh hưởng: `hotel_node → itinerary_node → booking_node → qa_node` (khách sạn neo lịch trình, nên phải chốt khách sạn trước).
- **Contract per-node**: mỗi worker khai báo đường dẫn state được đọc/ghi; ghi ngoài hợp đồng → `ContractViolation` (`strict` ở CI, `log` ở production). Worker khai `emits_reply=True` bắt buộc phải trả lời, không được im lặng.

### 1.2 Thu thập nhu cầu (intake) — `ask_slot` + `slot_registry`

| Thứ tự | Slot | Bắt buộc | Ghi chú |
|---|---|---|---|
| 1 | `destination` | ✅ | không có điểm đến thì không worker nào chạy được |
| 2 | `people` | ✅ | |
| 3 | `dates.start` | ✅ | hỏi chung một câu với `dates.end` |
| 4 | `dates.end` | ✅ | |
| 5 | `budget.target` | ✅ (bỏ qua được) | chấp nhận thay thế bằng `budget.min` / `budget.max` |

- Hỏi **tuần tự theo bảng**, không phải theo `if` ladder — ngân sách xếp cuối nên **không bao giờ chặn** bước chọn ngày.
- Câu hỏi được **LLM viết lại cho tự nhiên** (`get_fast_llm`); nếu LLM lỗi → rơi về câu template cố định, mất mỗi phần diễn đạt.
- Người dùng có thể trả lời **nhiều slot trong một câu**, trả lời **lệch thứ tự**, hoặc **sửa lại** giá trị đã khai — patch pipeline xử lý hết.
- Người dùng **hỏi ngược giữa lúc intake** → node `intake_qa` trả lời câu hỏi đó, rồi câu hỏi intake vẫn được gắn tiếp trong cùng một reply.

### 1.3 Hiểu ý định & cập nhật trạng thái — `extract_patch`

6 intent: `hotel_search`, `update_itinerary`, `update_trip`, `select_hotel`, `finalize`, `general_question`.

4 phép toán: `set`, `unset`, `append`, `remove` — trên **20 đường dẫn hợp lệ** (`ALLOWED_PATHS`):

| Nhóm | Đường dẫn |
|---|---|
| Chuyến đi | `destination`, `dates.start`, `dates.end`, `people` |
| Ngân sách | `budget.min`, `budget.max`, `budget.target` (mỗi ĐÊM), `budget.trip_total` (CẢ chuyến) |
| Sở thích | `preferences.themes`, `.companions`, `.pace`, `.day_rhythm`, `.notes` |
| Khách sạn | `hotel_preferences.amenities`, `.radius_km`, `.center`, `.min_star_rating` (1–5 sao), `.min_review_score` (0–10 điểm), `.result_count` (2–20 thẻ) |
| Lịch trình | `constraints.max_items_per_day`, `.max_item_distance_km`, `.max_items_by_day.*`, `daily_preferences.*.theme`, `locked_days` |

- **Grounding tất định** cho vài tiện ích hay bị LLM bỏ sót (ví dụ "bao ăn sáng", "view biển") — chỉ chạy khi intent *không* phải `general_question`.
- LLM lỗi/trả JSON hỏng → fallback `{"patch": [], "intent": "general_question"}`, lượt chat vẫn hoàn tất, không vỡ.
- Câu là lệnh sửa nhưng **không nói sửa thành gì** (`patch_reason = missing_value`) → hệ thống hỏi lại đúng giá trị còn thiếu thay vì im lặng không làm gì.

### 1.4 Tìm & chọn khách sạn — `hotel_node`

**Làm được:**
- Lọc **cứng** theo tiện ích, số sao tối thiểu, điểm đánh giá tối thiểu, bán kính + tâm tìm kiếm, khoảng giá/đêm — khác với điểm cộng "mềm" của `rank_hotel_candidates`.
- Mở rộng tiện ích theo cây danh mục (`amenity_catalog`: cha → con).
- Giải mã tâm tìm kiếm từ tên địa danh ("cách Cầu Rồng 2km"); nếu **không giải được** → `interrupt()` hỏi lại đúng một lần, người dùng trả lời xong lượt chạy tiếp.
- Trả thẻ khách sạn kèm `display_amenities` (tối đa 4 tiện ích nổi bật, ưu tiên tiện ích người dùng đang yêu cầu), ảnh, điểm khớp, lý do khớp.
- **Chọn khách sạn bằng chat** ("lấy cái số 2") hoặc bằng nút → `build_selected_hotel_trip` dựng **cả khách sạn lẫn toàn bộ lịch trình** trong một lượt.
- Không có kết quả → phân biệt rõ nguyên nhân: `no_results_dates` / `no_results_amenities` / `no_results_rating` và gợi ý nới điều kiện.

**Đường tắt không qua LLM** (nhanh, tất định): `POST /hotels/expand` (thêm lô thẻ), `POST /hotels/preferences` (bật/tắt pill tiện ích), `POST /hotels/select`.

### 1.5 Sửa lịch trình — `itinerary_node`

`itinerary_node` là **trình BIÊN TẬP, không phải trình tạo mới** — nó luôn cần `trip_data` đã tồn tại (tức là đã chọn khách sạn).

| Action | Việc làm |
|---|---|
| `rebuild_days` | dựng lại 1 ngày / vài ngày / cả chuyến (mặc định), tôn trọng `locked_days` |
| `edit_item` | sửa từng mục trong ngày ("bỏ bảo tàng ngày 2, thêm quán cà phê") |
| `lock_days` | khoá ngày lại để các lần dựng sau không đụng vào (hợp nhất tích luỹ, chưa có "mở khoá") |
| `list_nearby` | **chỉ đọc** — liệt kê điểm tham quan quanh khách sạn theo bán kính; chạy được **cả khi chưa chọn khách sạn** (đo từ thẻ khách sạn đang hiển thị) |

Lịch trình nhiều ngày được dựng **mỗi lượt một ngày**, node tự xếp lại hàng đợi; các lượt trung gian im lặng có chủ đích — người dùng chỉ nghe kết quả một lần khi xong.

### 1.6 Kiểm tra ngân sách — `budget_check`

- Kích hoạt khi có `budget.trip_total`.
- Tính chi phí đã biết của kế hoạch → **đủ / vượt / không đủ dữ liệu giá**.
- Nếu vượt: suy ra trần giá/đêm còn lại sau khi trừ chi phí hoạt động, chạy **đúng một vòng lập lại kế hoạch** (tìm khách sạn + dựng lại ngày chưa khoá), rồi tính lại. Vẫn vượt → nêu rõ hạng mục tốn nhất và số tiền thiếu. **Không bao giờ bịa giá thiếu, không loop vô hạn.**

### 1.7 Hỏi đáp chỉ đọc — `qa_node` (ReAct subgraph)

Công cụ: `query_hotel`, `query_hotel_rooms`, `search_places`, `get_hotel_options`, `get_trip_plan`.

- Trả lời về khách sạn đã hiển thị, loại phòng, giá, tiện ích, địa điểm quanh vùng, và lịch trình hiện có.
- **Không thể sửa gì** — ràng buộc bằng cấu trúc: subgraph chỉ chia sẻ kênh `messages`, không hề với tới `travel_state`/`trip_data`.
- Là node duy nhất nhận cả lịch sử hội thoại; được `fit_context_window` cắt ngắn để không tràn context.

### 1.8 Bảo vệ & an toàn

| Cơ chế | Trạng thái |
|---|---|
| Chặn jailbreak / lộ system prompt (`JAILBREAK_GUARD_MODE=block`) | ✅ đã chạy — chặn thẳng tới `respond`, không chạm LLM/tool nào |
| Từ chối câu hỏi ngoài phạm vi (toán, code, vé máy bay) | ❌ **chưa build** — `scope_guard` cho đi qua |
| Contract ghi state theo node | ✅ |
| Khoá lịch trình đã finalize (chat, `/hotels/change`, `/hotels/expand`, `/hotels/preferences` → 409) | ✅ |
| Kiểm tra quyền sở hữu session trên mọi route `/chat/{id}/…` | ✅ |
| Guard "bất khả thi": `itinerary_node` khi chưa có chuyến, `booking_node` luôn | ✅ |

### 1.9 Trải nghiệm hội thoại

- **Song ngữ vi/en** (`language` trong request; `t()` + i18next ở frontend).
- **Streaming SSE** `POST /planner_chat/stream` với các khung: `phase` (tiến độ thật, có cả `started`/`completed`), `delta` (token thật, chỉ từ `qa_node`/`intake_qa`), `reasoning` (tóm tắt suy luận, **luôn tiếng Anh**, thường vắng), `final` (payload đầy đủ), `suggestions`, `error`. Heartbeat 15s. Luôn đúng **một** khung kết thúc.
- Phase keys: `received`, `compacting_history`, `intake_check`, `routing`, `hotel_search`, `itinerary_build`, `routing_legs`, `persisting`, `generating`.
- **Suggestion chips**: do LLM sinh, **bám dữ liệu thật của lượt đó** (worker nào chạy, thẻ nào đang hiện, tiện ích thật trên thẻ, filter đang bật, độ dài chuyến). **Chỉ có trên đường SSE**; `POST /planner_chat`, `/hotels/select`, `/chat/{id}/restore` luôn trả `suggestions: []` — đúng thiết kế.
- `stage` trả về: `intake` | `hotel_options` | `planned` | `error`.
- **Lưu & khôi phục phiên**: `GET /chat/sessions` (danh sách), `GET /chat/{id}/restore` (khôi phục hội thoại + kế hoạch), `DELETE /chat/{id}`.

### 1.10 Đặt phòng & thanh toán — **qua UI, KHÔNG qua chat**

- Trong chat, ý định đặt phòng đi tới `booking_node` và node này **từ chối tường minh**: "Mình chưa hỗ trợ đặt chỗ trực tiếp…". Kế hoạch chat-driven booking (`plans/260820-1126-chat-driven-room-booking/`) đang ở trạng thái **DRAFT — chưa thực thi**.
- Luồng thật chạy trên giao diện: `room-card` → `booking-modal` (wizard 3 bước) → `hold-banner`:
  - `POST /bookings` — giữ phòng **TTL 15 phút** qua RPC `create_booking_reservation` (advisory lock theo `room_id` + `guest_ref`); chặn giữ 2 khách sạn cùng lúc.
  - `POST /payments/vnpay` — tạo URL ký HMAC-SHA512, điều hướng cả trang sang VNPay.
  - `GET /payments/vnpay/ipn` — **nguồn xác nhận duy nhất đáng tin** (redirect về chỉ để hiển thị); IPN → `confirm_booking_reservation` → gửi email xác nhận qua Resend.
  - `GET /chat/{id}/booking-receipt` — mở lại biên nhận của phiên cũ.
- Khách **không cần đăng nhập**: định danh bằng `temporary_user_ref` (UUID trong `localStorage`).

### 1.11 Chốt lịch trình — `POST /chat/{id}/finalize`

- **Bị chặn bởi thanh toán**: 409 nếu phiên chưa có booking `CONFIRMED`.
- Khoá lịch trình + lưu thành **template có embedding tái sử dụng được** (Tier-1 reuse: fingerprint BGE-M3, ngưỡng tương đồng > 88%).
- Sau khi finalize, mọi đường sửa đều trả 409.

### 1.12 Giới hạn cần biết

| Giới hạn | Chi tiết |
|---|---|
| Không đặt phòng bằng chat | `booking_node` từ chối; phải dùng UI |
| Không có guard ngoài phạm vi | hỏi toán/code vẫn được LLM trả lời |
| Không tạo lịch trình trước khi chọn khách sạn | lịch trình được xếp quanh vị trí khách sạn |
| Không có "mở khoá ngày" | chỉ có `lock_days` |
| Chips chỉ có trên SSE | POST thường luôn `[]` |
| `POST /hotels/change` là nợ kỹ thuật | vẫn bắn chuỗi `"đổi khách sạn"` vào extractor thay vì đặt tín hiệu state tất định |
| Embedding luôn dùng Ollama `bge-m3` | cố định 1024 chiều, kể cả khi `LLM_PROVIDER=openai` |
| Không có cron dọn hold hết hạn | hold hết hạn tự hết tác dụng khi `expires_at` trôi qua |

---

## Phần 2 — Kịch bản Happy Case

**Bối cảnh:** khách Việt, 2 người, đi Đà Nẵng 3 ngày, ngân sách ~1.5 triệu/đêm, thích biển và ẩm thực, muốn khách sạn gần Cầu Rồng có hồ bơi và bao ăn sáng, đặt phòng thật và chốt lịch.

**Điều kiện tiên quyết:** backend `:8000` + frontend `:5173` đang chạy, Supabase có dữ liệu Đà Nẵng, Ollama đã pull `bge-m3`, VNPay sandbox đã cấu hình.

### Bước 0 — Mở phiên

| | |
|---|---|
| Hành động | Mở `http://localhost:5173` |
| API | `POST /api/v1/chat/session` → `{session_id, created_at}` |
| Kỳ vọng | Màn hình intake, `stage="intake"`, chưa có phiên nào trong sidebar (phiên chỉ được lưu khi có lượt chat đầu) |

### Bước 1 — Khai nhu cầu trong một câu

> **User:** `Mình muốn đi Đà Nẵng 3 ngày, 2 người, từ 12/09 đến 14/09, ngân sách khoảng 1.5 triệu/đêm, thích biển và ăn uống`

| | |
|---|---|
| Phase SSE | `received` → `compacting_history` → `intake_check` (`intent="hotel_search"`, `fields=["destination","people","dates.start","dates.end","budget.target","preferences.themes"]`) → `routing` (`worker="hotel_node"`) → `hotel_search` (`started`) |
| Trong máy | `extract_patch` sinh ~6 change → `validate_patch` chốt ngày theo DD-MM → `apply_patch` ghi vào `TravelState` → `ask_slot` thấy **không còn slot thiếu** → `supervisor` chọn `hotel_node` (`itinerary_node` bị guard `requires_existing_trip` loại) |
| Kỳ vọng | `stage="hotel_options"`, 5 thẻ khách sạn Đà Nẵng đúng ngày 12–14/09, giá ≈ ngưỡng 1.5tr/đêm, mỗi thẻ có ≤4 `display_amenities` + điểm khớp + lý do khớp |
| Chips | ví dụ "Lọc khách sạn có hồ bơi", "Xem khách sạn gần biển" |

**Điểm cần quan sát:** ask_slot **không hỏi lại gì cả** — cả 5 slot đã đủ ngay lượt đầu; đây là bằng chứng patch pipeline chạy trước gate intake.

### Bước 2 — Thêm điều kiện cứng (tiện ích + bán kính)

> **User:** `Cho mình khách sạn có hồ bơi, bao ăn sáng, cách Cầu Rồng trong 3km thôi`

| | |
|---|---|
| Phase | `intake_check` (`intent="hotel_search"`, `fields=["hotel_preferences.amenities","hotel_preferences.radius_km","hotel_preferences.center"]`) → `routing` (`hotel_node`) → `hotel_search` (`outcome="ok"`, `radius_km=3`, `amenities=[...]`) |
| Trong máy | "bao ăn sáng" được **grounding tất định** kể cả khi LLM bỏ sót; `resolve_center` tra `attractions` thấy "Cầu Rồng" → **không cần `interrupt()`**; amenity mở rộng xuống các node con trong catalog |
| Kỳ vọng | Danh sách thu hẹp, mọi thẻ đều **thật sự có** hồ bơi + ăn sáng và nằm trong bán kính 3km; pill filter hiện đúng 2 tiện ích đang bật |

### Bước 3 — Hỏi đáp chỉ đọc (không đụng vào kế hoạch)

> **User:** `Khách sạn số 2 có phòng nào cho 2 người và giá bao nhiêu?`

| | |
|---|---|
| Phase | `intake_check` (`intent="general_question"`) → `routing` (`worker="qa_node"`) → `generating` (`started`) + **`delta` token chảy ra** |
| Kỳ vọng | Trả lời theo loại phòng thật từ `query_hotel_rooms`; **`trip_plan` và danh sách thẻ không đổi**; không có `budget_check`, không có ghi state |

> **User:** `Quanh khách sạn số 2 có gì chơi không?`

| | |
|---|---|
| Trong máy | `itinerary_node` action `list_nearby` — chạy được **dù chưa chọn khách sạn**, đo bán kính từ thẻ số 2 đang hiển thị (`can_list_nearby`) |
| Kỳ vọng | Danh sách điểm tham quan quanh đó + pin trên bản đồ; **route thẳng tới `respond`, bỏ qua `budget_check`** — lượt chỉ-đọc không được âm thầm sửa kế hoạch |

### Bước 4 — Chọn khách sạn → sinh nguyên lịch trình

> **User:** `Ok lấy khách sạn số 2` *(hoặc bấm nút "Chọn" trên thẻ)*

| | |
|---|---|
| API | chat: `intent="select_hotel"` → `hotel_node`; nút: `POST /hotels/select {session_id, hotel_id}` |
| Phase | `routing` (`hotel_node`) → `itinerary_build` (`started`) → `routing_legs` (`days=3`) → `persisting` |
| Trong máy | `build_selected_hotel_trip` dựng khách sạn **và** cả 3 ngày trong một lượt; `trip_scheduler` phân bổ thời gian, gom cụm theo khoảng cách, chèn bữa ăn/nghỉ |
| Kỳ vọng | `stage="planned"`, panel lịch trình hiện 3 ngày, mỗi ngày ≥7 mục (`breakfast/attraction/lunch/rest/coffee/dinner/evening`), có tuyến đường giữa các điểm |

### Bước 5 — Sửa lịch trình

> **User:** `Ngày 2 mình muốn thiên về ẩm thực, bỏ bớt bảo tàng`

| | |
|---|---|
| Trong máy | `daily_preferences.2.theme` → workflow `itinerary_day`; `itinerary_node` action `rebuild_days` với `day_numbers=[2]` |
| Kỳ vọng | **Chỉ ngày 2 đổi**, ngày 1 và 3 giữ nguyên từng mục |

> **User:** `Ngày 1 ok rồi, giữ nguyên nhé`

| | |
|---|---|
| Trong máy | `locked_days` ← `[1]`, đồng bộ vào `trip_data.planning_constraints` |
| Kỳ vọng | Xác nhận đã khoá; mọi lần dựng lại sau đó không đụng ngày 1 |

### Bước 6 — Ràng buộc tổng ngân sách

> **User:** `Tổng cả chuyến mình chỉ muốn trong 12 triệu`

| | |
|---|---|
| Trong máy | `budget.trip_total` → `budget_check`: tính chi phí đã biết; nếu vượt → suy trần giá/đêm, chạy **đúng một** vòng tìm lại khách sạn + dựng lại **ngày chưa khoá** (ngày 1 được miễn), rồi tính lại |
| Kỳ vọng | Câu trả lời nêu **con số thật**: tổng ước tính, phần đã có giá / chưa có giá, và nếu vẫn vượt thì hạng mục tốn nhất + số tiền thiếu. Ngày 1 **không** bị đụng |

### Bước 7 — Giữ phòng (UI, không phải chat)

| | |
|---|---|
| Hành động | Panel khách sạn → chọn loại phòng, số lượng → "Đặt phòng" |
| API | `POST /bookings {room_id, temporary_user_ref, check_in/out, room_count, session_id}` → `201`, `status="RESERVED"`, `expires_at = now + 15 phút` |
| Kỳ vọng | `hold-banner` hiện đồng hồ đếm ngược **đọc từ `expires_at` của server** mỗi giây (không tự đếm ở client); đổi loại phòng cùng khách sạn → không hỏi xác nhận; đổi sang khách sạn khác → `ConfirmDialog` nêu rõ hold nào mất và còn bao nhiêu phút |

*Thử happy-path phụ:* nếu người dùng gõ trong chat `"đặt giúp mình phòng này"` → `booking_node` **từ chối lịch sự** và chỉ sang nút đặt phòng. Đây là hành vi đúng, không phải lỗi.

### Bước 8 — Thanh toán VNPay

| | |
|---|---|
| Hành động | Wizard bước 2 → nhập tên/email/điện thoại → "Thanh toán" |
| API | `POST /payments/vnpay` → `{pay_url}` (ký HMAC-SHA512, `vnp_TxnRef` = `payment.id` bỏ dấu `-`) |
| Hành động | Trình duyệt điều hướng **cả trang** sang VNPay sandbox → thanh toán thành công |
| Xác nhận | VNPay gọi `GET /payments/vnpay/ipn` (server-to-server) → `confirm_booking_reservation` → booking `CONFIRMED`, `expires_at = NULL`, payment `PAID` → email Resend gửi đi |
| Kỳ vọng | Quay lại app: hold chuyển `BOOKED`, đồng hồ biến mất, email xác nhận (hero ảnh khách sạn + danh sách phòng) tới hộp thư. **Redirect chỉ để hiển thị — trạng thái thật luôn hỏi lại backend** |

### Bước 9 — Chốt lịch trình

| | |
|---|---|
| API | `POST /chat/{session_id}/finalize` |
| Kỳ vọng | `200` với `{status, summary, embedding_saved: true}`; lịch trình chuyển trạng thái `Finalized`, lưu thành template có embedding để tái sử dụng |
| Kiểm chứng khoá | Gửi tiếp `"đổi khách sạn khác đi"` hoặc gọi `/hotels/change` → **409** "Lịch trình đã hoàn tất và không thể chỉnh sửa." |

*Nếu chưa thanh toán mà gọi finalize* → `409` "Cần đặt phòng và thanh toán trước khi hoàn tất lịch trình." (cổng thanh toán, đúng thiết kế).

### Bước 10 — Rời đi rồi quay lại

| | |
|---|---|
| API | `GET /chat/sessions` → phiên hiện trong sidebar; `GET /chat/{id}/restore` → toàn bộ hội thoại + `trip_plan`; `GET /chat/{id}/booking-receipt` → biên nhận |
| Kỳ vọng | Hội thoại, lịch trình đã chốt và biên nhận đặt phòng hiện lại đầy đủ; `suggestions` là `[]` (đúng thiết kế, restore không phải đường SSE) |

### Bảng tổng kết tiêu chí đạt

| # | Tiêu chí | Đạt khi |
|---|---|---|
| 1 | Intake một câu | 5 slot đầy đủ, không có câu hỏi thừa |
| 2 | Lọc cứng | mọi thẻ đều thật sự thoả tiện ích + bán kính |
| 3 | Q&A chỉ đọc | `trip_plan` không đổi, có `delta` token |
| 4 | Chọn khách sạn | `stage="planned"`, đủ 3 ngày, có tuyến đường |
| 5 | Sửa có phạm vi | chỉ ngày được nhắc tới thay đổi |
| 6 | Khoá ngày | ngày đã khoá sống sót qua mọi lần dựng lại |
| 7 | Ngân sách | báo số thật, đúng một vòng lập lại, không bịa giá |
| 8 | Giữ phòng | TTL 15' đọc từ server, không giữ 2 khách sạn |
| 9 | Thanh toán | chỉ IPN mới xác nhận, email gửi thành công |
| 10 | Finalize | có cổng thanh toán, sau đó khoá mọi đường sửa |
| 11 | Khôi phục | hội thoại + kế hoạch + biên nhận trở lại đủ |

---

## Câu hỏi còn mở

1. Có cần bổ sung kịch bản unhappy (hết phòng, hold hết hạn, VNPay fail, `no_results_amenities`, jailbreak) không? Tài liệu này cố ý chỉ bao happy case theo yêu cầu.
2. Guard "ngoài phạm vi" (`guardrails/scope.py`) chưa build — có đưa vào kế hoạch không, hay chấp nhận như hiện trạng?
