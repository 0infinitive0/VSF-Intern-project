---
phase: 4
title: "Request field pass-through"
status: complete
priority: P1
effort: "1.5d"
dependencies: []
---

# Phase 4: Request field pass-through

## Overview

`_run_turn_via_graph` chỉ nhận `(session_id, message, language, extra_state)`. Mọi field
khác trên request model rơi im lặng — schema validate chúng rồi vứt đi. Phase này đóng
đường ống hoặc xóa field khỏi schema; **không chấp nhận trạng thái thứ ba** là "khai báo
nhưng không dùng".

## Bằng chứng lỗi

### 4a. `selection_message` bị vứt

- FE gửi: `chat-client.ts:84-88`
- Schema khai: `schemas.py:357`
- Route ghi đè bằng chuỗi tự chế: `routes.py:298`
  ```python
  message = f"Tôi chọn khách sạn ID {request.hotel_id}"
  ```

### 4b. `stay_dates` / `min_price` / `max_price` được validate rồi bỏ

- `PlannerChatRequest` (`schemas.py:330-351`) có validator bắt buộc *"ít nhất một trong
  message/stay_dates/min_price/max_price"*.
- `_run_turn_via_graph` chỉ truyền `request.message` (`routes.py:439`).
- FE cũng không gửi — form intake ghép thành câu tiếng Việt qua `composeIntakeMessage`
  (`intake-parameters-form.tsx:64,70`).
- **Hợp đồng chết hai đầu.** Rủi ro còn lại: client gửi mỗi `stay_dates` qua được
  validation nhưng tạo turn với message rỗng → `extract_patch` nhận `""`.

### 4c. `/hotels/change` không deterministic như FE tin

- Comment FE (`chat-client.ts:100-105`) khẳng định *"no LLM call, deterministic endpoint"*.
- Thực tế `routes.py:320` chạy `_run_turn_via_graph(session_id, "đổi khách sạn", ...)` —
  đi qua `extract_patch` → **có gọi LLM**.
- Chuỗi hardcode tiếng Việt, bỏ qua `session.language`.

## Requirements

**Functional**
- `selection_message` của client được dùng làm message của turn; `selected_hotel_id` vẫn
  là tín hiệu quyết định (không đổi hành vi `hotel_node`).
- `stay_dates`/`min_price`/`max_price`: **quyết định là xóa khỏi schema**, không nối
  đường ống. Lý do ở phần Architecture.
- `/hotels/change` vào graph tại `hotel_node` qua `Command(goto=...)`, gated bằng spike
  (**QĐ-3** trong `plan.md`); dùng `session.language` thay hardcode tiếng Việt; comment FE
  sửa cho khớp sự thật.

**Non-functional**
- Không thêm field mới lên wire. Phase này chỉ đóng khoảng cách hiện có.
- Mỗi thay đổi schema phải kèm kiểm tra không có client nào đang gửi field bị xóa.

## Architecture

### Vì sao xóa `stay_dates`/`min_price`/`max_price` thay vì nối đường ống

Nối chúng vào graph nghĩa là dựng một đường vào `travel_state` **bỏ qua**
`extract_patch` → `validate_patch` → `apply_patch`. Chính pipeline đó là lý do tồn tại
của plan 260812: mọi thay đổi state phải đi qua validate. Một cửa sau structured cho
riêng ba field này sẽ:

- bỏ qua `validate_patch` (nơi xử lý ngày mơ hồ bằng `interrupt()`),
- tạo nguồn sự thật thứ hai cho cùng các slot,
- và không ai đang dùng nó.

FE đã có đường đi hoạt động được: widget ghép câu → `extract_patch` parse. Chậm hơn (một
LLM call) nhưng **đúng kiến trúc**. Nếu sau này cần đường structured nhanh, đó là một
plan riêng có thiết kế riêng, không phải một field ngủ quên được đánh thức.

Vậy nên:

```
PlannerChatRequest:
  session_id, message, language     ← giữ
  stay_dates, min_price, max_price  ← XÓA + xóa model_validator
```

Sau khi xóa, `message` trở thành bắt buộc (`str`, `min_length=1`) — điều mà validator cũ
đang cố diễn đạt một cách vòng vo.

### `selection_message`

```python
# TRƯỚC (routes.py:298)
message = f"Tôi chọn khách sạn ID {request.hotel_id}"

# SAU
message = request.selection_message or f"Tôi chọn khách sạn ID {request.hotel_id}"
```

Fallback giữ nguyên cho client cũ không gửi field. `selected_hotel_id` trong
`extra_state` không đổi — nó vẫn là tín hiệu deterministic mà `hotel_node` đọc
(review finding F2), `message` chỉ vào transcript.

### `SelectPlaceRequest` — code chết

`schemas.py:360` khai `SelectPlaceRequest`, **không có route nào dùng**. `qa_node`'s
docstring nói rõ thiết kế đích là interrupt-resume trong `rebuild_day`, không phải một
`select_place` endpoint. Xóa model.

### `/hotels/change` — vào graph tại `hotel_node`

Chi tiết lập luận ở **QĐ-3** trong `plan.md`. Tóm tắt: `hotel_node` đọc toàn bộ input từ
`state["travel_state"]` đã commit, nên chuỗi `"đổi khách sạn"` mang zero thông tin mới —
đẩy nó qua `extract_patch` chỉ tạo cơ hội cho extractor sinh patch giả mạo, không đổi lấy
được gì.

```python
# TRƯỚC (routes.py:320)
return _run_turn_via_graph(session_id, "đổi khách sạn", session.language)

# SAU
snapshot = app.get_state(config)
result = app.invoke(
    Command(goto="hotel_node", update=load_context(snapshot.values)),
    config=config,
)
```

`update=load_context(...)` **bắt buộc**, không phải tùy chọn. `load_context`
(`load_context.py:38-61`) reset 17 field turn-scoped, trong đó:

| Field | Thiếu reset thì sao |
|---|---|
| `task_results: []` | `respond._reply_from_task_results` nhặt reply của worker turn trước |
| `next_question: None` | `respond._question_for_this_reply` hỏi lại câu hỏi cũ |
| `response: {}` | payload cũ lẫn vào |
| `supervisor_iterations: 0` | budget delegation không reset |

Tái dùng chính `load_context` thay vì chép danh sách — nó là nguồn sự thật duy nhất cho
"field nào thuộc về một turn".

**Lưu ý `interrupt()`:** `hotel_node` có thể pause khi radius search cần center
(`hotel_node.py:11-16`). Đường `Command(goto=...)` đi qua graph nên interrupt vẫn hoạt
động bình thường — đây chính là lý do không gọi `hotel_node(state)` như hàm Python. Nhánh
`if interrupts:` hiện có trong `_run_turn_via_graph` phải dùng chung, không viết lại.

### Route alias trùng

`/chat/select_hotel`, `/chat`, `/session/{id}/state` là alias của `/hotels/select`,
`/planner_chat`, `/chat/{id}/plan`. FE chỉ dùng bản chính. Giữ hay xóa là quyết định
tương thích ngược — **giữ**, nhưng thêm comment nói rõ chúng là alias cho CLI/test, để
lần đọc sau không tưởng là hai endpoint khác nhau.

## Related Code Files

- Modify: `backend/src/models/schemas.py` — `PlannerChatRequest` bỏ 3 field + validator; xóa `SelectPlaceRequest`, `StayDatesInput` (nếu hết call site)
- Modify: `backend/src/api/routes.py` — `select_hotel` dùng `selection_message`; `change_hotel` vào graph tại `hotel_node`; comment cho alias
- Modify: `backend/src/i18n/` — catalog entry cho reply của `change_hotel` (chỉ cần nếu spike fail và vẫn phải gửi chuỗi qua extractor)
- Modify: `frontend/src/api/chat-client.ts` — sửa comment sai ở `changeHotel`
- Modify: `backend/tests/test_respond.py` / `test_hotel_node.py` — cập nhật nếu chạm request model
- Create: `backend/tests/test_request_field_passthrough.py`
- Create: `backend/tests/test_hotels_change_entrypoint.py` — spike ở bước 0 lớn lên thành test thật khi nó pass

## Implementation Steps

0. **Spike (~1h, cổng chặn cho QĐ-3).** Viết một test dùng thật:
   `Command(goto="hotel_node", update=load_context(...))` trên thread đã có checkpoint →
   assert `hotel_node` chạy, `extract_patch` **không** chạy, `respond` trả payload đầy đủ,
   và một lần `interrupt()` trong `hotel_node` vẫn pause/resume được. Docs LangGraph cảnh
   báo `Command` làm input có thể "appear stuck" (xem QĐ-3) — spike này là chỗ phát hiện.
   **Nếu spike fail:** rơi về phương án cũ (giữ full graph, chỉ làm bước 6 và 7), ghi kết
   quả spike vào `plan.md` QĐ-3, bỏ bước 6b. Không cố ép.
1. **Test đỏ trước.** `test_select_hotel_uses_client_selection_message`: POST
   `/hotels/select` với `selection_message="Chọn khách sạn Mường Thanh"`, assert transcript
   của turn chứa đúng chuỗi đó (không phải "Tôi chọn khách sạn ID ...").
2. Sửa `select_hotel` (một dòng).
3. `grep -rn "stay_dates\|min_price\|max_price" backend/ frontend/ --include="*.py"
   --include="*.ts" --include="*.tsx"` — xác nhận không client nào gửi 3 field đó lên
   `/planner_chat`. Kiểm cả `frontend/mock/server.js`.
4. Xóa 3 field + `model_validator` khỏi `PlannerChatRequest`; đổi `message` thành bắt buộc.
5. Xóa `SelectPlaceRequest`; `grep` xác nhận không call site.
6. **Nhánh phụ thuộc kết quả spike:**
   - **6a (spike pass):** `change_hotel` dùng `Command(goto="hotel_node",
     update=load_context(snapshot.values))`. Không còn chuỗi `"đổi khách sạn"` nào —
     vấn đề hardcode tiếng Việt biến mất cùng lúc, không cần i18n entry mới. Dùng chung
     nhánh `if interrupts:` của `_run_turn_via_graph`, không viết lại.
   - **6b (spike fail):** giữ `_run_turn_via_graph`, thay `"đổi khách sạn"` bằng
     `t("đổi khách sạn", session.language)` qua cơ chế i18n hiện có (`src/i18n`).
7. Sửa comment ở `chat-client.ts:100-105` cho khớp hành vi thật sau bước 6 — 6a làm nó
   thành deterministic thật (comment hiện tại trở nên đúng); 6b thì comment phải nói rõ
   là **có** gọi LLM.
8. Ghi kết quả spike (pass/fail + lý do) vào QĐ-3 trong `plan.md`.
9. Chạy `backend/tests/test_legacy_guards.py` và full suite.

## Success Criteria

- [x] Test `selection_message` fail trước, pass sau
- [x] `PlannerChatRequest` không còn field nào không đến được graph — test khóa `model_fields == {session_id, message, language}`
- [x] `grep -rn "SelectPlaceRequest" backend/` → không kết quả
- [x] `/hotels/change` không đẩy chuỗi tiếng Việt cứng vào extractor ở bất kỳ `language` nào — không còn chuỗi nào cả
- [x] **(6a)** `/hotels/change` không gọi `extract_patch` — assert bằng spy, không bằng đo thời gian
- [x] **(6a)** `interrupt()` trong `hotel_node` vẫn pause/resume qua đường `Command(goto=...)`
- [x] **(6a)** Turn `/hotels/change` không kế thừa `next_question`/`task_results` của turn trước
- [x] Comment ở `chat-client.ts` mô tả đúng hành vi thật của endpoint sau bước 6
- [x] Kết quả spike đã ghi vào QĐ-3 trong `plan.md`
- [x] OpenAPI schema không còn field ma — verify bằng `app.openapi()`: `PlannerChatRequest.properties == {session_id, message, language}`, `required == {message, session_id}`, `SelectPlaceRequest`/`StayDatesInput` biến mất
- [x] Full backend suite pass (701 pass / 5 fail = baseline); frontend 218 pass, typecheck sạch

## Ghi chú thực thi (2026-08-16)

### Spike PASS → nhánh 6a. Chi tiết ở [QĐ-3 trong `plan.md`](./plan.md)

`tests/test_hotels_change_entrypoint.py` 8/8. Cảnh báo "appear stuck" của docs LangGraph
chỉ áp dụng cho `Command(update=...)` **không kèm** `goto`; dạng có `goto` chạy đúng.

### Dùng chung, không copy

Nhánh `if interrupts:` + bước dựng `PlannerChatResponse` tách thành
`_response_from_result(session_id, result)`; cả `_run_turn_via_graph` và
`_rerun_hotel_search` gọi nó. `/hotels/change` cũng gọi `_persist_turn` như mọi turn khác —
nó tạo ra một reply thật, phải sống sót qua reload.

### `StayDatesInput` xóa theo

Sau khi `PlannerChatRequest` bỏ `stay_dates`, `grep` cho thấy model này không còn call site
nào. Xóa cùng, kéo theo `model_validator` khỏi import của `schemas.py`.

### Bước 3 (grep) — kết quả

Không client nào gửi `stay_dates`/`min_price`/`max_price` lên `/planner_chat`. Mọi kết quả
grep của `min_price`/`max_price` phía FE đều thuộc **`IntakeStatus`** (chiều response, backend
echo lại budget slot) hoặc nội bộ `hotel_selection` — không liên quan request model.
`frontend/mock/server.js` cũng không gửi. Xóa an toàn, không cần giai đoạn `deprecated=True`.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Client bên ngoài đang gửi `stay_dates` mà ta không biết | Trung bình | Bước 3 grep cả `frontend/mock/`. Đây là app nội bộ, chưa có public API consumer. Nếu nghi ngờ, giữ field với `deprecated=True` một release thay vì xóa thẳng |
| Xóa field làm vỡ test hiện có | Thấp | `grep` ở bước 3 phủ cả `backend/tests/` |
| `message` bắt buộc làm vỡ client gửi message rỗng | Thấp | Turn message rỗng vốn đã vô nghĩa (`extract_patch` nhận `""` rồi fallback). Bắt buộc là sửa lỗi, không phải breaking change thật |
| **`Command(goto=...)` làm input không đáng tin** — docs cảnh báo graph có thể "appear stuck" | Cao | Chính là lý do bước 0 là spike có cổng chặn. Fallback 6b đã định nghĩa sẵn, không phải ứng biến giữa chừng |
| Thiếu `update=load_context(...)` → turn kế thừa `next_question`/`task_results` cũ | Cao | Success Criteria có assert riêng. Đây là lỗi im lặng: turn vẫn trả 200, chỉ nội dung sai |
| `Command(goto=...)` bỏ qua `scope_guard` | Thấp | `scope_guard` chặn jailbreak trong text người dùng; đường này không có text người dùng nào để chặn |
| Vào graph tại `hotel_node` bỏ qua `apply_patch` → `travel_state` không commit | Trung bình | `hotel_node` tự ghi `hotel_preferences.*` qua `apply_patch` của domain layer (`hotel_node.py` import `apply_patch` từ `domain.travel_state`), không phụ thuộc node `apply_patch`. Spike phải assert preference mới thật sự persist |
| Hai đường vào graph (`_run_turn_via_graph` và `change_hotel`) phân kỳ theo thời gian | Trung bình | Bắt buộc dùng chung nhánh `if interrupts:` và bước dựng `PlannerChatResponse`; tách helper nếu cần, không copy |
