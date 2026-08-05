---
phase: 4
title: "[BE] Persist session & lịch sử hội thoại"
status: pending
priority: P2
effort: "2-3 ngày"
dependencies: [1]
track: backend
---

# Phase 4: [BE] Persist session & lịch sử hội thoại

## Tổng quan

Làm cho session sống sót qua restart process và qua việc bị TTL loại bỏ, đồng thời phơi ra
dưới dạng danh sách, để rail lịch sử hội thoại (Glassmorphism) trong design có dữ liệu thật
đằng sau.

Đây là phase backend lớn nhất và có blast radius cao nhất — nó chạm vào vòng đời session mà
mọi lượt chat đều phụ thuộc. Nó được thiết kế **thuần cộng thêm**: khi tắt persistence, hệ
thống chạy y hệt hôm nay.

## Yêu cầu

**Chức năng**
- State nghiệp vụ của session được ghi xuống Postgres sau mỗi lượt có thay đổi
- Luồng tin nhắn được persist để hội thoại khôi phục lại có lịch sử
- `GET /api/v1/chat/sessions` liệt kê session đã persist kèm title suy ra, trạng thái, điểm
  đến, số ngày, mốc thời gian và thumbnail
- `GET /api/v1/chat/{session_id}/restore` trả toàn bộ state hội thoại
- `registry.get()` rehydrate từ Postgres khi miss trong RAM, thay vì trả `None` và ép ra 404
- `DELETE /api/v1/chat/{session_id}` xoá luôn dòng đã persist

**Phi chức năng**
- Persistence **bật/tắt qua settings**; không bật → hành vi in-memory y hệt hôm nay
- Lỗi persistence **không bao giờ** làm hỏng một lượt chat — chỉ log và đi tiếp
- Ghi diễn ra bên trong lock theo session đã có, nên không phát sinh bề mặt concurrency mới
- Restore một session có luồng tin nhắn dài vẫn dưới ~1s

## Kiến trúc

### Seam đã có sẵn

`TripSession` vốn đã mang `persist_hook: Callable[[TripSession], None] | None`
(`agents/session.py:124, :143`), được gọi sau các thay đổi state (`:279-280`, `:296-297`,
`:493-494`). CLI cài `cli_persist_hook` để ghi file JSON; **server để trống hook**
(`:300-303`). `SessionRegistry.__init__` cũng đã nhận và truyền `persist_hook`
(`:1079-1085`) xuống `create_chat_session`.

Nghĩa là đường ghi **không cần plumbing mới** — chỉ cần một hook implementation mới và một
cờ settings để cài nó. Đây chính là lý do phase này khả thi dù phạm vi lớn.

### Cái gì serialize được

`TripState` (`agents/state.py:27-65`) là TypedDict. Mọi field đều JSON-safe **trừ**:

- `messages: Annotated[list, add_messages]` — object message của LangChain
- `remaining_steps: NotRequired[Annotated[int, RemainingStepsManager]]` — manager runtime
  của LangGraph, **tuyệt đối không được persist**

Serialize luồng tin nhắn bằng `messages_to_dict` / `messages_from_dict` của LangChain, và
**bỏ hẳn `remaining_steps` khi ghi** (LangGraph tự tiêm lại lúc compile — persist nó chính
là nguyên nhân sinh ra lớp lỗi `Missing required key(s) {'remaining_steps'}` mà docstring
của state ở `:42` đã cảnh báo sẵn).

### Lưu trữ

Hai bảng đã tồn tại và server hiện chưa dùng:

- `sessions(session_id varchar PK, context_data jsonb, created_at, updated_at)` —
  chứa `TripState` đã serialize, đã bỏ `messages`/`remaining_steps`
- `chat_messages(...)` — **phải kiểm tra cột thật trước khi dùng**; schema của bảng này chưa
  được đọc trong lúc lập plan. Nếu shape không hợp (role/text/stage/created_at) thì nên lưu
  luồng tin nhắn ngay trong `sessions.context_data` dưới khoá `messages`, thay vì bẻ cong
  một bảng không liên quan. Quyết ở bước 1 và ghi vào contract.

### Field suy ra cho danh sách

`GET /chat/sessions` trả các field tính từ `context_data`, không thêm cột mới:

| Field | Suy ra từ |
|---|---|
| `title` | `intake.destination` + số ngày → `"Đà Nẵng – Hội An 4N3Đ"`; fallback là tin nhắn đầu của user (cắt ngắn); rồi mới đến nhãn "Chuyến đi mới" đã dịch |
| `status` | `"completed"` khi `trip_data` khác null, ngược lại `"draft"` |
| `destination`, `duration_days` | `intake` / `trip_data.itineraries[0]` |
| `thumbnail_url` | `image_url` của khách sạn đã chọn, nếu chưa chọn thì `null` |
| `created_at`, `updated_at` | cột trong bảng |

Việc suy ra title **không được** là chuỗi tiếng Việt hardcode trong Python. Hãy trả về các
thành phần (`destination`, `duration_days`) và một `title` hoặc là nội dung thật của user
hoặc là `null`; frontend tự dịch phần fallback. Nhất quán với cách tách i18n mà dự án đã làm.

### Rehydration

`SessionRegistry.get()` hiện trả `None` khi miss (`:1097-1105`), router biến thành `404` —
hành vi mà bootstrap của frontend đã xử lý sẵn bằng cách âm thầm tạo session mới
(`use-chat-session.ts:141-160`). Sửa `get()` để thử load từ Postgres trước khi bỏ cuộc:

```
get(session_id):
  hit trong RAM   → trả về (không đổi)
  miss trong RAM  → load từ Postgres
                      thấy      → dựng lại TripSession, đưa vào registry, trả về
                      không thấy → trả None (không đổi → 404)
```

Đường dựng lại phải build lại agent qua `create_chat_session` rồi mới gán `state` đã
deserialize — **agent, tools và lock là process-local, phải dựng lại, tuyệt đối không
restore** (`agents/session.py:105-107` nói đúng điều này).

Giữ nguyên cơ chế loại bỏ theo TTL/cap: bị loại giờ chỉ có nghĩa là "rời khỏi RAM", không
còn là "mất hội thoại" — đó chính là mục đích của phase này.

## File liên quan

- Tạo: `backend/src/services/session_store.py` — serialize/deserialize, CRUD, list
- Sửa: `backend/src/agents/session.py`
  - thêm `supabase_persist_hook`
  - `SessionRegistry.get()` — rehydrate khi miss
  - `SessionRegistry.drop()` — xoá dòng đã persist
- Sửa: `backend/src/api/routes.py` — `GET /chat/sessions`, `GET /chat/{id}/restore`
- Sửa: `backend/src/models/schemas.py` — `SessionSummaryPayload`, `SessionRestorePayload`
- Sửa: module settings — cờ `session_persistence_enabled`
- Tạo: `backend/tests/test_session_store.py`

## Các bước thực hiện

1. **Kiểm tra cột của `chat_messages`** rồi quyết: dùng bảng riêng hay `context_data.messages`.
   Ghi quyết định và contract kết quả vào `docs/chat_api_contract.md`.
2. Viết `session_store.py`:
   - `serialize(session) -> dict` — `state` trừ `remaining_steps`, `messages` qua `messages_to_dict`
   - `deserialize(row) -> TripState`
   - `upsert(session)`, `load(session_id)`, `delete(session_id)`, `list_sessions(limit)`
   - `summarize(row) -> dict` cho endpoint list
3. Thêm `supabase_persist_hook(session)` trong `session.py` — mỏng, uỷ quyền cho store, bắt
   và log **mọi** exception để lỗi persistence không thể làm hỏng lượt chat.
4. Thêm cờ settings; chỉ cài hook lên `registry` cấp module khi cờ bật.
5. Cài rehydration trong `registry.get()`. Bọc bằng cùng cờ đó — tắt nghĩa là hành vi
   `None`-khi-miss hiện tại, y nguyên từng byte.
6. Mở rộng `registry.drop()` để xoá dòng đã persist.
7. Thêm hai endpoint. `restore` tái dùng đúng các builder payload có sẵn
   (`to_trip_plan_payload`, `to_hotel_options_payload`, `IntakeStatus.from_state`) để shape
   của nó không thể lệch khỏi `planner_chat`.
8. Test:
   - round-trip serialize→deserialize giữ nguyên intake, hotel prefs, trip_data, các cờ
   - `remaining_steps` không bao giờ xuất hiện trong JSON đã persist
   - luồng tin nhắn round-trip qua `messages_to_dict`/`from_dict`
   - `get()` rehydrate được sau khi entry trong RAM đã bị loại
   - lỗi persistence bị nuốt: lượt chat vẫn thành công
   - tắt cờ ⇒ không có ghi DB nào và ngữ nghĩa `get()` không đổi
   - `drop()` xoá cả RAM lẫn dòng DB
9. Kiểm tra tay: chạy trọn một hội thoại, restart process, list session, restore, xác nhận
   luồng tin nhắn + plan + intake đều quay lại và lượt chat tiếp theo chạy tiếp đúng.

## Tiêu chí hoàn thành

- [ ] Hội thoại đầy đủ sống sót qua restart process và chạy tiếp đúng sau đó
- [ ] `GET /chat/sessions` trả session đã persist thật kèm các field suy ra
- [ ] `GET /chat/{id}/restore` khớp shape `PlannerChatResponse` cộng `messages[]`
- [ ] `remaining_steps` không bao giờ được persist; không có lỗi thiếu khoá LangGraph khi restore
- [ ] Agent, tools và lock được dựng lại khi rehydrate, không bao giờ deserialize
- [ ] Tắt persistence ⇒ hành vi y hệt hôm nay, không ghi DB
- [ ] DB chết thì xuống cấp về hành vi in-memory hôm nay mà không làm hỏng lượt chat
- [ ] `DELETE` xoá cả RAM lẫn dòng đã persist
- [ ] Backend không sinh ra chuỗi hiển thị đã dịch nào
- [ ] Test suite backend pass

## Đánh giá rủi ro

**Phase rủi ro cao nhất trong plan.** Nó nằm trên vòng đời session mà mọi lượt chat dùng.

- *Serialize làm mất state agent và hỏng graph.* Giảm thiểu bằng cách chỉ persist
  `TripState` — docstring của class (`:96-115`) đã tuyên bố rõ field nào là dữ kiện nghiệp
  vụ và field nào là runtime process-local. Tuân thủ đúng ranh giới đó theo nghĩa đen.
- *Round-trip `remaining_steps` làm hỏng LangGraph.* Bỏ hẳn khi ghi, có test riêng phủ.
  Docstring của state vốn đã cảnh báo đúng lỗi này.
- *DB chậm hoặc chết làm treo lượt chat.* Hook là fire-and-forget, có timeout giới hạn và
  bắt trọn exception; lỗi thì log rồi đi tiếp.
- *Rehydration race với request đồng thời.* Thực hiện load **bên trong** `_registry_lock`,
  y hệt pattern check-then-create của `resolve()` (`:1112-1126`) — pattern đó được viết ra
  chính là để đóng race này.
- *Session id do client cung cấp.* Đã có `_SESSION_ID_PATTERN` validate cho debug hook; áp
  dụng đúng validation đó trước mọi thao tác ghi DB.

**Lưu ý phạm vi.** Đây là phase mà người dùng nâng cấp từ "bỏ qua" lên "làm". Nếu tiến độ
trượt thì đây chính là phase nên cắt — phase 5-10 không phụ thuộc vào nó, và sidebar rail
(Phase 5) đã được dựng để render được ngay cả khi không có danh sách lịch sử.
