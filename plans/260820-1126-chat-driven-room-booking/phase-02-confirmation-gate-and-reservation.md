# Phase 2 — Cổng xác nhận xác định + giữ phòng thật

## Bối cảnh

Phase 1 để lại `pending_booking` trong graph state và một câu hỏi xác nhận.
Phase này biến câu trả lời của người dùng thành hành động — hoặc không.

Đây là phần có hệ quả tiền bạc, nên nguyên tắc là: **luật xác định, không LLM**,
và nghi ngờ thì không đặt. Cùng lập trường với `supervisor.py` ("không hỏi model
điều code đã trả lời được") và với `_IMPOSSIBLE` (structured output bảo đảm nhãn
hợp lệ, không bảo đảm hành động hợp lệ).

## Máy trạng thái của cổng xác nhận

Trạng thái duy nhất là `state["pending_booking"]` (None hoặc dict có `expires_at`).
Không có bảng DB, không có cờ ở frontend — checkpointer của LangGraph đã lưu
graph state theo `thread_id = session_id` nên đề nghị tự sống qua các lượt.

```
                 ┌─────────────────────────────────────────────┐
                 │ pending_booking = None  (trạng thái nghỉ)    │
                 └───────────────┬─────────────────────────────┘
      intent == "booking"        │  mọi tin nhắn khác → tuyến thường
      + resolve OK               ▼
                 ┌─────────────────────────────────────────────┐
                 │ pending_booking = {proposal, expires_at}     │
                 │ reply = tóm tắt + "bạn xác nhận chứ?"        │
                 │ CHƯA có row bookings nào                     │
                 └───┬──────────────┬───────────────┬──────────┘
   classify=confirm  │   =decline   │   =other      │  quá 10 phút
                     ▼              ▼               ▼          ▼
              re-resolve +      xoá đề nghị    KHÔNG đụng   coi như None,
              reserve_booking   reply "ok,     đề nghị,     lượt sau
              → booking_hold    chưa đặt gì"   đi tuyến     re-resolve lại
              → pending=None                   thường
```

Ba chốt chặn độc lập, theo thứ tự, để một hành động tốn tiền không bao giờ xảy
ra do một lỗi đơn lẻ:

1. **Chốt định tuyến** (`supervisor._is_booking_turn`): không có `pending_booking`
   còn hạn thì `booking_node` chỉ được gọi khi `intent == "booking"` — một câu
   "ok" bâng quơ giữa hội thoại không bao giờ tới được node đặt phòng.
2. **Chốt phân loại** (`classify_booking_reply`): luật xác định, `other` là mặc
   định khi không chắc.
3. **Chốt dữ liệu** (`booking_node` nhánh confirm): re-resolve tồn phòng/giá; lệch
   so với tóm tắt đã đọc cho user → đề nghị lại thay vì đặt.

## Yêu cầu

1. Phân loại câu trả lời thành `confirm` | `decline` | `other` bằng bảng từ khoá
   + giới hạn độ dài. `other` không bao giờ đặt phòng.
2. `confirm` → re-resolve tồn phòng/giá, rồi gọi `booking_service.reserve_booking`
   một lần cho mỗi loại phòng (cùng cách `use-room-hold.ts:279-299` làm).
3. Mọi `BookingError` có câu trả lời tiếng người, không stack trace, không hold
   mồ côi (lỗi giữa chừng → huỷ những gì đã tạo).
4. Chat **không bao giờ** gọi `confirm_booking`.

## File

| File | Việc |
|---|---|
| `backend/src/services/booking_intent.py` | **mới** — `classify_booking_reply` |
| `backend/src/agents/graph/nodes/booking_node.py` | nhánh confirm/decline |
| `backend/src/agents/graph/nodes/supervisor.py` | hoàn thiện `_is_booking_turn` |

## Các bước

### 2.1 `classify_booking_reply(message: str) -> Literal["confirm","decline","other"]`

Thuần, không I/O, không state — test được độc lập.

```python
_CONFIRM = frozenset({
    "ok", "oke", "okie", "okay", "yes", "y", "yeah", "yep", "sure",
    "dong y", "dong y nhe", "xac nhan", "chot", "chot don", "dat di",
    "dat luon", "dat phong di", "duoc", "duoc roi", "u", "um", "ung",
    "confirm", "confirmed", "book it", "go ahead", "agree",
})
_DECLINE = frozenset({
    "khong", "ko", "k", "no", "thoi", "thoi khoi", "huy", "huy di",
    "khong dat", "de sau", "khoan", "cancel", "nope", "not now",
})
_MAX_TOKENS = 4
```

Chuẩn hoá bằng đúng cách repo đã làm: bỏ dấu như
`hotel_selection._normalize_for_match` (NFKD + `Đ/đ → D/d`), lower, bỏ dấu câu.

Luật:
- Sau chuẩn hoá, nếu chuỗi **khớp nguyên vẹn** một mục trong `_CONFIRM`/`_DECLINE`
  → nhãn tương ứng.
- Nếu > `_MAX_TOKENS` token → luôn `other` ("ok cho tôi xem thêm khách sạn khác"
  không phải xác nhận).
- Ngắn hơn giới hạn nhưng chỉ *chứa* từ khoá chứ không khớp nguyên vẹn →
  `confirm` chỉ khi mọi token đều nằm trong `_CONFIRM ∪ {từ đệm}` với từ đệm =
  `{"nhe","nha","di","luon","roi","a","please"}`. Ngoài ra `other`.

Hướng lệch có chủ ý: bỏ sót một câu đồng ý (user gõ lại) rẻ hơn nhiều so với
đặt phòng khi user chưa đồng ý.

### 2.2 Supervisor

```python
def _is_booking_turn(state) -> bool:
    if state.get("intent") == _BOOKING_INTENT:
        return True
    pending = state.get("pending_booking")
    if not pending or _expired(pending):
        return False
    return classify_booking_reply(_last_human_message(state)) != "other"
```

`_expired` đọc `pending["expires_at"]`. Đề nghị hết hạn coi như không có: lượt đó
đi tuyến bình thường (và `booking_node` sẽ dọn `pending_booking` ở lần chạy kế).

### 2.3 `booking_node` — nhánh `decline`

Xoá đề nghị (`"pending_booking": None`), reply "Ok, mình chưa đặt gì cả. Bạn có
thể xem tiếp các lựa chọn khác." status `cancelled`. Không gọi service.

### 2.4 `booking_node` — nhánh `confirm`

1. Đề nghị hết hạn → re-resolve từ đầu, đề nghị lại (status
   `awaiting_confirmation`), **không** đặt. Nói rõ vì sao ("đề nghị trước đã quá
   hạn, mình kiểm tra lại phòng").
2. Re-resolve `get_hotel_detail` để đọc giá + tồn phòng hiện tại. Khác so với
   tóm tắt đã đọc cho user (giá đổi, hoặc tồn < số phòng) → **không đặt**, báo
   thay đổi và đề nghị lại. RPC vẫn là trọng tài cuối, nhưng tóm tắt user đã đọc
   không được sai.
3. Đặt tuần tự từng loại phòng:

```python
created = []
try:
    for room in proposal.rooms:
        created.append(booking_service.reserve_booking(
            room_id=UUID(room.room_id),
            temporary_user_ref=guest_ref,
            check_in_date=proposal.check_in_date,
            check_in_time=time(14, 0),
            check_out_date=proposal.check_out_date,
            check_out_time=time(12, 0),
            room_count=room.room_count,
            total_amount=room_total_or_none,
            currency=room.currency,
            session_id=state.get("session_id"),
        ))
except BookingError as exc:
    for booking in created:
        try: booking_service.cancel_booking(booking_id=UUID(booking["id"]), temporary_user_ref=guest_ref)
        except Exception: logger.exception(...)
    return _error_reply(exc, language, state)
```

Giờ nhận/trả phòng 14:00/12:00 là cùng hằng số FE đang dùng
(`use-room-hold.ts:132-133`) và cũng là default của
`BookingReservationRequest` (`models/schemas.py:425-427`).

4. Thành công → ghi:

```python
{
    "pending_booking": None,
    "booking_hold": {
        "hotel_id": proposal.hotel_id,
        "session_id": state.get("session_id"),
        "bookings": [BookingPayload-shaped dict, ...],
    },
    "task_results": [..., {"worker": "booking_node", "status": "held", "reply": reply}],
}
```

reply nêu: giữ những phòng nào, tới mấy giờ (từ `expires_at` sớm nhất — cùng quy
tắc "nhóm hold chỉ sống bằng reservation ngắn nhất", `use-room-hold.ts:243-248`),
và bước tiếp theo là bấm "Đặt phòng" để thanh toán VNPay. Không hứa hẹn gì về
việc đã thanh toán.

### 2.5 Ánh xạ lỗi → câu chữ

| `BookingError` | vi |
|---|---|
| `insufficient_room_availability` | "Phòng vừa hết trong lúc mình xác nhận. Bạn muốn mình tìm phòng khác không?" |
| `guest_already_holding_elsewhere` | "Bạn đang giữ phòng ở một khách sạn khác. Huỷ giữ chỗ đó ở thanh phía trên rồi mình đặt lại giúp bạn." |
| `booking_reservation_expired` | "Lượt giữ phòng trước đã hết hạn, mình kiểm tra lại phòng trống nhé." |
| `invalid_booking_request` | "Ngày nhận/trả phòng chưa hợp lệ. Bạn cho mình lại ngày nhận và ngày trả phòng nhé?" |
| còn lại | "Mình chưa giữ được phòng do lỗi hệ thống. Bạn thử lại giúp mình nhé." (log `exception`) |

Mọi câu có bản EN theo `state["language"]`.

## Validation

```bash
cd backend && pytest tests/test_booking_intent.py tests/test_booking_node.py -q
```

Bắt buộc có test: `"ok cho tôi xem thêm khách sạn khác"` → `other` → **zero call**
tới `reserve_booking`.

## Rủi ro & rollback

- Từ khoá tiếng Việt thiếu → user nói "ừ được rồi đặt đi" mà không nhận. Chấp
  nhận được; bổ sung từ khoá là thay đổi một dòng, có test đi kèm.
- Rollback: giữ Phase 1 (chỉ đề nghị, không đặt) bằng cách cho nhánh `confirm`
  trả lời "tính năng tạm khoá" — không cần revert.
