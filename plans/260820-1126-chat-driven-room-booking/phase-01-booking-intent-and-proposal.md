# Phase 1 — Intent `booking`, mở route, và đề nghị đặt phòng

## Bối cảnh

Hôm nay một câu "đặt phòng cho tôi" đi tới đâu: `extract_patch` trả
`general_question` + patch rỗng → `pending_tasks` rỗng → `supervisor` rơi vào
nhánh read-only (`nodes/supervisor.py:267`) → `qa_node` trả lời chung chung.
`booking_node` không bao giờ được chọn vì `_IMPOSSIBLE["booking_node"] = True`
(`agents/graph/routing.py:69`).

Phase này làm cho lượt "đặt phòng" tới được `booking_node` và **chỉ dừng ở đề
nghị** — chưa ghi DB (việc ghi là Phase 2).

## Yêu cầu

1. Intent mới `booking` trong từ vựng extractor: user muốn đặt/giữ một phòng cụ
   thể. Không đổi ngữ nghĩa `select_hotel` (chọn khách sạn để dựng lịch trình).
2. `booking_node` khả dụng khi có thứ để đặt: có `trip_data.hotel.id` hoặc có
   danh sách khách sạn đã hiện (`shown_hotel_options`). Ngược lại: vẫn impossible.
3. Resolver thuần (không I/O ngoài `get_hotel_detail`) dựng `BookingProposal`
   từ: câu người dùng + state. Thiếu dữ kiện → trả lý do, node hỏi lại.
4. `booking_node` ghi `pending_booking` vào graph state và trả lời tóm tắt +
   câu hỏi xác nhận. Không gọi `booking_service`.

## File được sửa/tạo

| File | Việc |
|---|---|
| `backend/src/agents/graph/nodes/extract_patch.py` | thêm `"booking"` vào `_INTENTS` (dòng 101) |
| `backend/src/agents/graph/prompts.py` | thêm `booking` vào danh sách intent (dòng ~64) + mô tả ngữ nghĩa (khối `intent meanings`, dòng ~72-78) |
| `backend/src/agents/graph/routing.py` | thay `_IMPOSSIBLE["booking_node"]` bằng guard thật |
| `backend/src/agents/graph/state.py` | thêm `guest_ref`, `pending_booking`, `booking_hold` |
| `backend/src/agents/graph/nodes/load_context.py` | reset `booking_hold`; **không** reset `pending_booking` |
| `backend/src/agents/graph/nodes/supervisor.py` | nhánh delegate `booking_node` |
| `backend/src/agents/graph/graph.py` | cạnh `booking_node` → `respond` |
| `backend/src/services/booking_resolver.py` | **mới** — resolver + dataclass |
| `backend/src/agents/graph/nodes/booking_node.py` | viết lại thân node |

## Các bước

### 1.1 Từ vựng intent

`extract_patch.py:101` → thêm `"booking"`. `prompts.py` mô tả:

```
- booking: the user wants to actually reserve/hold a specific room
  ("đặt phòng Deluxe", "giữ phòng cho tôi", "book that room"), as opposed to
  select_hotel, which only picks which hotel the itinerary is built around.
```

Intent vẫn **không** chọn worker (giữ nguyên bất biến ở `state.py:37-41`); nó chỉ
là tín hiệu cho nhánh delegate xác định ở supervisor, giống `asks_nearby_places`.
Patch của lượt booking luôn rỗng — không có `ALLOWED_PATHS` nào cho booking.

### 1.2 Guard khả thi

```python
def _nothing_to_book(state) -> bool:
    from src.agents.tools.shown_hotels import shown_hotel_options
    return not (state.get("trip_data") or {}).get("hotel", {}).get("id") \
        and not shown_hotel_options(state)

_IMPOSSIBLE = {
    "itinerary_node": ...,
    "booking_node": _nothing_to_book,
}
```

Lưu ý import: `routing.py` hiện chỉ import từ `state`/`domain`.
`shown_hotels.py` chỉ import `src.services.amenity_catalog` và nhận `state` kiểu
`Any` → không tạo vòng lặp với `agents.graph`. Nếu vẫn muốn giữ `routing.py`
mỏng, đặt helper trong `booking_resolver.py` và import từ đó.

### 1.3 State + reset

`state.py`, kèm docstring giải thích lý do (theo văn phong module này):

```python
    # Danh tính guest cho lượt này (PlannerChatRequest.temporary_user_ref).
    # Ghi đè mỗi lượt bởi routes.py, kể cả khi None — không bao giờ mang giá
    # trị của lượt trước.
    guest_ref: str | None
    # Đề nghị đặt phòng đang chờ user xác nhận. KHÔNG bị load_context reset
    # (giống missing_slots/selected_hotel_id): phải sống từ cuối lượt đề nghị
    # sang đầu lượt xác nhận. Nằm ngoài travel_state vì travel_state chỉ giữ
    # ALLOWED_PATHS qua from_dict/to_dict.
    pending_booking: dict[str, Any] | None
    # Hold vừa tạo trong CHÍNH lượt này, cho respond dựng payload. Turn-scoped;
    # load_context reset về None để hold cũ không rò sang lượt sau.
    booking_hold: dict[str, Any] | None
```

`load_context.py`: thêm `"booking_hold": None`. `initial_graph_state`: thêm cả ba.

### 1.4 Resolver — `services/booking_resolver.py`

```python
@dataclass(frozen=True)
class ProposedRoom:
    room_id: str
    name: str
    room_count: int
    unit_price: Decimal | None
    currency: str | None
    available_room_count: int | None

@dataclass(frozen=True)
class BookingProposal:
    hotel_id: str
    hotel_name: str
    check_in_date: date
    check_out_date: date
    rooms: tuple[ProposedRoom, ...]
    total_amount: Decimal | None   # None khi thiếu giá thật
    currency: str | None
    nights: int

def resolve_booking_request(message: str, state) -> BookingProposal | ResolutionGap
```

Quy tắc:

- **Khách sạn**: ưu tiên `trip_data.hotel.id`; nếu câu nói nêu rank/tên thì khớp
  qua danh sách `shown_hotel_options` bằng đúng cách `query_hotel_rooms.py:99-124`
  làm (rank số trước, rồi substring tên). Trùng nhiều → gap `ambiguous_hotel`.
- **Ngày**: dùng `_stay_dates(state)` — logic đã có ở
  `agents/tools/query_hotel_rooms.py:18-45` (`previous_hotel_search_context` →
  fallback `trip_data.itineraries[0]`). **Tách hàm này ra `booking_resolver.py`
  và cho `query_hotel_rooms` import lại** (DRY, một nguồn sự thật). Không có ngày
  → gap `missing_dates`.
- **Phòng**: `get_hotel_detail(hotel_id, check_in, check_out)` → lọc theo từ khoá
  tên phòng trong câu. Không nêu tên và khách sạn có nhiều loại → gap
  `room_not_specified` (kèm danh sách tên phòng còn trống để node hỏi lại).
  Phòng khớp nhưng `available_room_count <= 0` → gap `sold_out`.
- **Số phòng**: số nguyên trong câu ("2 phòng") thắng tất cả. Không nói →
  suy từ `people` (slot int 1..50, `travel_state.py:600`) và `room.max_guests`
  (`place_details.py:25` có sẵn cột này):
  `room_count = max(1, ceil(people / max_guests))`; thiếu `people` hoặc thiếu
  `max_guests` → 1. Cap theo `available_room_count` và theo
  `BookingReservationRequest` (1..20, `models/schemas.py:428`). Vượt tồn → gap
  `not_enough_rooms`. Tóm tắt phải nói rõ con số này là suy ra ("4 khách → mình
  giữ 2 phòng"), để user sửa được trước khi xác nhận.
- **Tiền**: `unit_price * room_count * nights` chỉ khi có giá thật > 0 (đúng như
  `use-room-hold.ts:294`); không có giá → `total_amount=None`, tóm tắt ghi "giá
  theo yêu cầu" thay vì bịa số.

Không gọi `booking_service` ở đây. Không import gì từ `agents.graph.nodes`.

### 1.5 `booking_node` — nhánh đề nghị

Viết lại node; ở phase này chỉ xử lý nhánh "chưa có `pending_booking`":

1. `guest_ref` rỗng → reply "chưa đặt được qua chat, dùng bảng khách sạn",
   status `no_guest_ref`. Không ghi state. (Chỉ có ý nghĩa sau Phase 3; trước đó
   luôn rơi vào nhánh này — chính là feature flag tự nhiên.)
2. `resolve_booking_request` trả gap → reply câu hỏi tương ứng, status
   `needs_info`, `pending_booking` giữ nguyên `None`.
3. Có proposal → ghi:

```python
"pending_booking": {
    **asdict(proposal),                      # đã JSON-safe hoá
    "proposed_at": now_iso,
    "expires_at": (now + timedelta(minutes=10)).isoformat(),
}
```

reply = tóm tắt + câu hỏi xác nhận, ví dụ (vi):

> Mình sẽ giữ **2 phòng Deluxe** tại **Khách sạn X**, nhận phòng 12/09 (14:00),
> trả phòng 14/09 (12:00) — 2 đêm, tổng **4.200.000 ₫**. Phòng được giữ 15 phút
> sau khi xác nhận. Bạn xác nhận đặt chứ? Trả lời **"đồng ý"** để mình giữ phòng.

status `awaiting_confirmation`. Bản EN song song qua `language` (cùng cách
`booking_node` hiện tại chọn `_DECLINE_EN`/`_DECLINE_VI`).

Node vẫn tự gỡ mình khỏi `pending_tasks` và append `task_results` như bản hiện
tại (đó là hợp đồng `emits_reply=True` ở `contracts.py`). Contract `writes` giữ
rỗng — mọi thứ node ghi đều nằm ngoài `travel_state` nên `enforce_contract`
(chỉ diff `travel_state`) không bị ảnh hưởng.

### 1.6 Supervisor + cạnh graph

`supervisor.py`, chèn **sau** khối khoá trip finalized và **trước** nhánh
read-only (`if not workers and state.get("intent") == _READ_ONLY_INTENT`):

```python
    if _is_booking_turn(state) and not is_impossible("booking_node", state):
        return _delegate("booking_node", "booking_intent", state)
```

`_is_booking_turn` = `intent == "booking"` **hoặc** (`pending_booking` còn hạn
**và** `classify_booking_reply(last_message)` khác `"other"`) — hàm classifier
là Phase 2, ở phase này chỉ cần vế `intent == "booking"`.

`graph.py:163` đổi:

```python
builder.add_conditional_edges("booking_node", all_tasks_done, {True: "respond", False: "supervisor"})
```

kèm comment: `budget_check` chạy re-plan khi `budget.trip_total` được đặt và ghi
đè `task_results[-1]` — một lượt đặt phòng không đổi kế hoạch, và reply của nó
không được phép bị thay. Cùng lý do `route_after_itinerary_node` tồn tại.

## Validation

```bash
cd backend && pytest tests/test_graph_v2_skeleton.py tests/test_routing.py tests/test_extract_patch.py -q
```

Test mới (chi tiết ở Phase 5) tối thiểu: một lượt "đặt phòng X" cho ra
`pending_booking` và **không** gọi `booking_service` (mock/spy khẳng định
zero-call).

## Rủi ro & rollback

- Extractor gán nhầm `booking` cho câu chỉ hỏi giá → chỉ dừng ở đề nghị, chưa
  ghi gì; user bỏ qua là xong. Prompt nêu rõ ranh giới với `select_hotel` và với
  câu hỏi về phòng (`query_hotel_rooms` vẫn là nơi trả lời câu hỏi).
- Rollback: đặt lại `_IMPOSSIBLE["booking_node"] = lambda s: True` — mọi thứ trở
  về hành vi từ chối hiện tại, không cần revert file khác.
