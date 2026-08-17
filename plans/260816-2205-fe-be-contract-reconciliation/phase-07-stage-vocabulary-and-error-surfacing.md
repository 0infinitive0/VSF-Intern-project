---
phase: 7
title: "Stage vocabulary and error surfacing"
status: complete
priority: P2
effort: "1d"
dependencies: [2]
---

# Phase 7: Stage vocabulary and error surfacing

## Overview

`ChatStage` khai 6 giá trị, `_derive_stage` chỉ sinh được 3. Hệ quả nghiêm trọng nhất:
lỗi phía backend hiển thị như tin nhắn assistant bình thường vì `stage === 'error'` không
bao giờ đúng.

## Bằng chứng lỗi

`_derive_stage` (`respond.py:230-244`) chỉ trả `intake` | `planned` | `hotel_options`.
Docstring của chính nó thừa nhận: *"`finalized`/`modified`/`error` are never emitted — no
graph producer exists for any of the three yet"* (`respond.py:43-45`).

Nhưng `ChatStage` (`schemas.py:327`) khai 6 giá trị, và FE tin vào điều đó:

```ts
// use-chat-session.ts:159
const isError = data.stage === 'error'    // không bao giờ true
```

→ lỗi backend không có styling lỗi, không phân biệt được với câu trả lời thật.

Backend **có** sinh lỗi user-facing: `sanitize_system_error` (`schemas.py:515-533`) trả
chuỗi bắt đầu bằng `"SYSTEM ERROR:"`. Chuỗi đó đi thẳng vào `reply` với `stage` bình
thường. User thấy một bubble trắng ghi "SYSTEM ERROR: ..." như thể đó là câu trả lời.

Ngoài ra `booking_node` (`graph.py:103`) chạy được nhưng không có stage tương ứng —
`finalize` không có cách nào biểu đạt.

## Requirements

**Functional**
- Turn kết thúc bằng lỗi user-facing → `stage = "error"`, FE hiện styling lỗi.
- `booking_node` hoàn tất → `stage = "finalized"`.
- `ChatStage` không còn giá trị nào không có producer — hoặc có producer, hoặc bị xóa.
- `modified`: **xóa**. Không có node nào phân biệt "vừa sửa" với "đã có plan", và
  `trip_data` sticky nên không thể suy ra (`respond.py:255-258` đã ghi nhận vấn đề sticky này).

**Non-functional**
- Không parse text để đoán lỗi ở FE. `stage` là field structured, dùng nó.
- Sanitize hiện tại giữ nguyên — phase này không đổi nội dung thông báo lỗi, chỉ đổi cách
  đánh dấu.

## Architecture

### Nguồn tín hiệu lỗi

`_derive_stage` hiện chỉ đọc state. Lỗi nằm trong `reply` text. Hai lựa chọn:

- **A. Sniff prefix trong `_derive_stage`**: `reply.startswith("SYSTEM ERROR:")` → `"error"`.
  Rẻ, một dòng, nhưng lại là heuristic text — đúng thứ plan này đang cố loại bỏ.
- **B. State key tường minh**: node nào sinh lỗi set `state["turn_failed"] = True`.
  Đúng kiến trúc, nhưng phải sửa mọi producer lỗi.

**Chọn A cho phase này, với lối thoát sang B.** Lý do: `sanitize_system_error` đã là điểm
tập trung duy nhất mọi lỗi user-facing đi qua — prefix `"SYSTEM ERROR:"` không phải quy
ước lỏng lẻo mà là hợp đồng đã được test (`_SAFE_ERROR_PREFIXES`, 16 entry, hai ngôn ngữ).
Sniff tại **một** chỗ đã có hợp đồng thì chấp nhận được; rải heuristic ra nhiều chỗ thì không.

Ghi comment nói rõ đây là bước trung gian và điều kiện để chuyển sang B (khi có node đầu
tiên cần báo lỗi mà không qua `sanitize_system_error`).

```python
def _derive_stage(state, hotel_options, reply: str) -> str:
    if reply.startswith("SYSTEM ERROR:"):
        return "error"
    if state.get("missing_slots"):
        return "intake"
    if _booking_completed(state):        # từ task_results của booking_node
        return "finalized"
    if state.get("trip_data"):
        return "planned"
    if hotel_options:
        return "hotel_options"
    return "intake"
```

Thứ tự: lỗi outrank mọi thứ (một turn hỏng không phải một turn `planned`).

### FE

`use-chat-session.ts:159` đã đúng, chỉ là chưa bao giờ đúng được. Sau phase này nó chạy.
Kiểm `message-bubble.tsx` render `isError` như thế nào — nếu chưa có styling riêng thì
thêm.

`RestoredMessage.stage` từ `restored_messages` map cứng thành `"intake"`
(`session_store.py:352`) → message lỗi khi restore mất dấu lỗi. Sửa: ghi `stage` thật vào
`chat_messages` ở Phase 1, đọc lại ở đây. **Phụ thuộc mềm với Phase 1** — nếu Phase 1 chưa
xong, ghi nhận là hạn chế đã biết thay vì hack.

## Related Code Files

- Modify: `backend/src/agents/graph/response_payload.py` — `derive_stage` nhận `reply`, thêm `error`/`finalized` (module do Phase 2 tạo — đây là lý do phase này `dependencies: [2]`)
- Modify: `backend/src/agents/graph/nodes/respond.py` — cập nhật call site
- Modify: `backend/src/models/schemas.py` — `ChatStage` bỏ `modified`
- Modify: `backend/src/agents/graph/nodes/booking_node.py` — đảm bảo `task_results` có tín hiệu hoàn tất
- Modify: `frontend/src/types.ts` — `Stage` phản ánh union thật (Phase 8 sẽ sinh tự động)
- Check: `frontend/src/components/message-bubble.tsx` — styling `isError`
- Modify: `backend/tests/test_respond.py` — case `error` và `finalized`

## Implementation Steps

1. **Test đỏ trước.** `test_system_error_reply_derives_error_stage`: turn có reply
   `"SYSTEM ERROR: ..."` → `response["stage"] == "error"`. Fail hiện tại.
2. Đổi chữ ký `derive_stage` trong `response_payload.py` để nhận `reply`; cập nhật hai
   call site (`respond.py` và `routes.py::restore_session`). Restore truyền `reply=""` —
   không có reply nào để đánh giá, và một session đã lưu không phải một turn đang lỗi.
3. Thêm `_booking_completed(state)` đọc `task_results` tìm entry của `booking_node`.
   Đọc `booking_node.py` (42 dòng) trước để biết nó đang trả gì.
4. Xóa `"modified"` khỏi `ChatStage`; `grep` xác nhận không consumer nào đang so sánh với nó.
5. FE: kiểm `message-bubble.tsx` có nhánh `isError`. Nếu chỉ đổi màu chữ, cân nhắc thêm
   icon/border theo design token hiện có — **không** tự chế màu mới.
6. Chạy full suite hai phía.

## Success Criteria

- [x] Test `error` stage fail trước (8 đỏ trong `TestDeriveStage`), pass sau
- [ ] Gây lỗi thật (ngắt Supabase giữa turn) → bubble hiện với styling lỗi *(cần kiểm thủ công; styling đã có sẵn, xem bên dưới)*
- [~] ~~`booking_node` chạy xong → `stage == "finalized"`~~ → **`finalized` bị xóa thay vì được wire.** Xem Sai lệch
- [x] `ChatStage` không còn giá trị nào không có producer — có test khóa: `set(get_args(ChatStage)) == {intake, planned, hotel_options, error}`
- [x] `grep -rn "'modified'" backend/src frontend/src` → không kết quả
- [x] Full suite hai phía xanh (backend 685 pass / 5 fail = baseline; frontend 218 pass, typecheck sạch)

## Sai lệch so với bản plan (2026-08-16)

### `finalized` bị **xóa**, không được wire vào `booking_node`

Plan yêu cầu *"`booking_node` hoàn tất → `stage = "finalized"`"* và bước 3 dặn đọc
`booking_node.py` trước. Đọc xong thì tiền đề sụp:

| Bằng chứng | Hệ quả |
|---|---|
| `routing.py:69` — `_IMPOSSIBLE["booking_node"] = lambda s: True` | Supervisor **không bao giờ** route tới được. Node unreachable. |
| `booking_node.py:40` — trả `{"status": "declined", "reply": <"chưa hỗ trợ đặt chỗ">}` | Nó **từ chối**, không hoàn tất. Không có khái niệm "booking xong". |
| `grep "finalized"` phía FE | Không consumer nào đọc `stage === 'finalized'` |

Gắn `finalized` vào một lần từ chối là nói dối người dùng: họ vừa được bảo "chưa hỗ trợ
đặt chỗ" mà UI lại chuyển sang trạng thái "đã chốt".

Producer thật của `finalized` từng là `_STAGE_MAP["finalize_trip_plan"]` trong
`session.py` — thuộc cascade `process_chat_turn` đã bị xóa ở `e26d6f5`. Cùng lý do với
`modified` (`_STAGE_MAP["execute_trip_edit_request"]`). Nên cả hai bị xóa theo đúng
nguyên tắc phase đã đặt ra: *"hoặc có producer, hoặc bị xóa"*.

Muốn `finalized` quay lại thì cần một plan riêng: gỡ `_IMPOSSIBLE`, cho `booking_node`
một đường hoàn tất thật, rồi thêm cả giá trị lẫn producer trong **cùng một** change.

### Xóa luôn `TurnResult` / `_STAGE_MAP` / `derive_stage` cũ trong `session.py`

`grep` xác nhận không còn call site nào — chết cùng `process_chat_turn`. Chúng là nơi duy
nhất còn sinh ra `finalized`/`modified`, nên để lại nghĩa là để lại đúng thứ vừa bị xóa
khỏi từ vựng. Docstring lỗi thời ở `routes.py:6` (*"assembly from TurnResult"*) sửa theo.

### Sniff prefix hóa ra **không phải** heuristic mới

Plan chọn phương án A và tự nhận là "chấp nhận có ý thức một heuristic text". Thực tế
plane cũ đã làm đúng như vậy — `session.py::derive_stage` mở đầu bằng
`if result.text.startswith("SYSTEM ERROR:")`. Cutover graph plane làm rơi mất nó. Vậy đây
là **khôi phục một hợp đồng cũ**, không phải thêm heuristic mới. Điều kiện chuyển sang B
đã ghi trong docstring `derive_stage`.

### FE: không cần đổi styling

`message-bubble.tsx:42-44` **đã có** nhánh `isError` dùng design token có sẵn
(`bg-error-container`, `text-on-error-container`, `border-error/30`). Không tự chế màu mới,
đúng yêu cầu. Nó chưa bao giờ chạy chỉ vì `stage === 'error'` không bao giờ đúng.

Có sửa `frontend/src/types.ts`: `Stage` từng là `'hotel_options' | 'error' | string | null`
— `| string` làm cả union tan thành `string`, nên `stage === 'error'` type-check trót lọt
suốt trong khi không giá trị nào sinh ra được. Giờ đóng lại đúng union thật
(`'intake' | 'hotel_options' | 'planned' | 'error' | null`); `npm run typecheck` xanh,
không call site nào phụ thuộc chuỗi tự do.

### Hạn chế đã biết: message khôi phục mất dấu lỗi

`chat_messages` **không có cột `stage`** (`backend/scripts/database_schema.sql:195-201`),
nên `restored_messages` hardcode `"intake"` cho mọi row và một bubble lỗi cũ khôi phục lại
sẽ mất styling đỏ. Turn đang chạy thì đúng (stage lấy thẳng từ response).

Không hack quanh nó: sửa đúng cách cần một migration thêm cột, nằm ngoài phạm vi phase và
ngoài ranh giới file của plan. Đã ghi chú tại `use-chat-session.ts` chỗ
`isError: m.stage === 'error'` để lần đọc sau không tưởng là bug.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sniff prefix là heuristic — đúng thứ plan này chống lại | Trung bình | Chấp nhận có ý thức, ghi comment kèm điều kiện chuyển sang B. Chỉ một call site, đã có hợp đồng test bảo vệ prefix |
| `"SYSTEM ERROR:"` lọt vào reply hợp lệ của user | Thấp | `sanitize_system_error` chỉ chạy trên reply của backend; user không điều khiển được `reply` |
| Xung đột với Phase 2 (cùng chạm `response_payload.py`) | Thấp | Đã chuyển thành `dependencies: [2]` — Phase 2 tạo module, phase này sửa hàm trong đó. Không còn là xung đột, chỉ là thứ tự |
| `finalized` đổi hành vi `deriveStageView` ở FE | Trung bình | `derive-stage.ts` không đọc `stage` (nó tự suy từ `tripPlan`/`hotelOptions`). Verify `chat-panel.tsx:112` (`lastStage === 'hotel_options'`) không bị ảnh hưởng |
| Restore mất dấu lỗi vì `stage` map cứng | Thấp | Phụ thuộc mềm Phase 1; ghi nhận là hạn chế nếu chạy độc lập |
