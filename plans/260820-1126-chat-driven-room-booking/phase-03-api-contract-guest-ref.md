# Phase 3 — Hợp đồng API: `temporary_user_ref` vào, `booking_hold` ra

## Bối cảnh

`temporary_user_ref` hôm nay chỉ tồn tại ở trình duyệt
(`frontend/src/lib/guest-ref.ts`, localStorage) và chỉ đi kèm các request
`/bookings*`. `PlannerChatRequest` (`backend/src/models/schemas.py:382-408`) không
có nó, nên backend không biết hold thuộc về ai khi đặt từ chat.

Backend **không** được tự sinh ref: hold sinh ra sẽ không thuộc về trình duyệt
nào, FE không huỷ cũng không thanh toán được. Vì vậy FE gửi ref lên.

Chiều ngược lại: FE phải biết hold vừa được tạo để hiện banner đếm ngược và mở
`BookingModal` — thêm `booking_hold` vào `PlannerChatResponse`.

## Yêu cầu

1. `PlannerChatRequest.temporary_user_ref: str | None` (1..128, khớp ràng buộc
   của `BookingReservationRequest.temporary_user_ref`).
2. Ref chảy tới graph state `guest_ref`, ghi đè **mỗi lượt** (kể cả `None`).
3. `PlannerChatResponse.booking_hold: BookingHoldPayload | None`, chỉ khác `None`
   ở đúng lượt tạo hold.
4. Đường non-stream và đường stream hành xử như nhau. `GET /chat/{id}/restore`
   **không** trả `booking_hold` (hold là trạng thái tức thời, không phải lịch sử).

## File

| File | Việc |
|---|---|
| `backend/src/models/schemas.py` | `temporary_user_ref` vào request; `BookingHoldPayload` + field vào response |
| `backend/src/api/routes.py` | truyền ref qua `extra_state` ở cả `planner_chat` và `planner_chat_stream` |
| `backend/src/agents/graph/nodes/respond.py` | đọc `booking_hold` từ state vào payload |
| `backend/src/agents/graph/response_payload.py` | helper `booking_hold_from_state` (dùng chung với restore = luôn `None`) |
| `frontend/src/types/index.ts` (+ `wire.generated.ts` nếu sinh tự động) | kiểu `BookingHold` |
| `frontend/src/api/chat-client.ts`, `frontend/src/api/stream-client.ts` | gửi `temporary_user_ref` |

## Các bước

### 3.1 Schema

```python
class PlannerChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)
    language: Literal["vi", "en"] = DEFAULT_LANGUAGE
    # Danh tính guest ẩn danh của trình duyệt (frontend/src/lib/guest-ref.ts),
    # cùng giá trị đi kèm POST /bookings. Có mặt thì chat mới giữ phòng được;
    # thiếu thì booking_node từ chối và chỉ sang bảng khách sạn — backend
    # KHÔNG tự sinh ref, vì hold sinh ra sẽ không trình duyệt nào huỷ hay
    # thanh toán được.
    temporary_user_ref: str | None = Field(default=None, min_length=1, max_length=128)
```

Ghi chú: docstring hiện tại của class giải thích vì sao `stay_dates`/`min_price`/
`max_price` bị xoá (cửa sau không kiểm soát vào `travel_state`). `temporary_user_ref`
**không** rơi vào lập luận đó — nó không phải slot của `travel_state`, không đi
qua `extract_patch`, và là danh tính chứ không phải dữ kiện chuyến đi. Viết rõ
điều này vào docstring để lần đọc sau không tưởng là tái phạm.

```python
class BookingHoldPayload(ResponsePayload):
    """Hold vừa được tạo NGAY TRONG lượt chat này (booking_node). Chỉ khác
    None ở đúng lượt đó — frontend nhận nuôi vào use-room-hold rồi tự quản.
    Không phải ảnh chụp trạng thái hold hiện thời: nguồn sự thật vẫn là
    bookings/expires_at phía server."""
    hotel_id: str
    session_id: str | None = None
    bookings: list[BookingPayload]
```

### 3.2 Routes

`planner_chat`: `_run_turn_via_graph(session_id, message, language, {"guest_ref": request.temporary_user_ref})`.

`planner_chat_stream`: `_run_stream_turn` đã có tham số `extra_state`
(`routes.py:928-936`) nhưng endpoint chưa truyền (`routes.py:1006-1008`) — truyền
`extra_state={"guest_ref": request.temporary_user_ref}` và cập nhật docstring của
`_run_stream_turn` (đang ghi "never set by the real endpoint").

Luôn truyền key, kể cả `None`, để lượt sau không thừa hưởng ref của lượt trước
qua checkpointer.

### 3.3 respond

`respond.py` thêm `booking_hold=state.get("booking_hold")` vào payload. Vì
`load_context` reset về `None` mỗi lượt, không có đường nào rò hold cũ.
`GET /chat/{id}/restore` dựng payload từ helper chung → helper trả `None` khi
state không có key (đúng cho lịch sử phát lại).

### 3.4 Frontend gửi ref

`chat-client.ts` / `stream-client.ts:162`: thêm `temporary_user_ref: getGuestRef()`
vào body. Dùng đúng hàm `getGuestRef()` sẵn có, không sinh ref riêng.

## Validation

```bash
cd backend && pytest tests/test_request_field_passthrough.py tests/test_stream_modes.py tests/test_reply_contract.py -q
cd frontend && npm test -- stream-client chat-client
```

Kiểm cả hai đường: cùng một `temporary_user_ref` phải tới được graph state ở
`/planner_chat` và `/planner_chat/stream`.

## Rủi ro & rollback

- `docs/chat_api_contract.md` là hợp đồng công khai → phải cập nhật (Phase 5).
- Field optional cả hai chiều nên client cũ vẫn chạy: không gửi ref = không đặt
  được qua chat, đúng như hôm nay.
- Rollback: bỏ field khỏi schema; `booking_node` rơi về nhánh `no_guest_ref`.
