---
phase: 2
title: "Restore endpoint from real state"
status: complete
priority: P1
effort: "1.5d"
dependencies: [1]
---

# Phase 2: Restore endpoint from real state

## Overview

`GET /chat/{session_id}/restore` hiện trả về một vỏ rỗng với bốn giá trị hardcode. Phase
này thay chúng bằng dữ liệu thật, dùng lại đúng các helper mà `respond.py` đã dùng —
không viết serialization thứ hai.

## Bằng chứng lỗi

`backend/src/api/routes.py:236-244`:

```python
return SessionRestorePayload(
    messages=[],            # hardcode
    suggestions=[],         # hardcode
    stage="intake",         # hardcode
    hotel_options=to_hotel_options_payload(state.get("hotel_options")),
    trip_plan=to_trip_plan_payload(state.get("trip_data")),
    intake=IntakeStatus.from_state(None, None),   # luôn rỗng
)
```

- `state.get("hotel_options")` — `TravelGraphState` (`state.py`) **không định nghĩa key
  này**. `hotel_node` trả options lồng trong `task_results[-1]["hotel_search_result"]`
  (xem `respond.py:179-186`). Field này luôn `[]`.
- `IntakeStatus.from_state(None, None)` là hàm của plane cũ; plane mới dùng
  `_intake_status_from_travel_state` (`respond.py:295-334`).
- `session_store.restored_messages()` (`session_store.py:344`) được viết đúng cho payload
  này và **không ai gọi**.
- Hệ quả FE: `use-chat-session.ts:223-242` khởi tạo từ `INITIAL_STATE` rồi áp đúng các
  field trên → bấm hội thoại cũ ra khung chat trắng, checklist intake reset.

`stage="intake"` là chỗ **duy nhất vô hại** — FE cố ý bỏ qua `data.stage` và tự suy ra
bằng `deriveStageView`. Vẫn nên trả stage thật để payload trung thực.

## Requirements

**Functional**
- `messages` trả transcript thật từ `chat_messages` (do Phase 1 ghi).
- `hotel_options` trả danh sách thật từ `task_results` của checkpoint.
- `intake` dùng cùng hàm `respond.py` dùng, không phải `IntakeStatus.from_state`.
- `stage` dùng cùng `_derive_stage` mà `respond.py` dùng.
- `suggestions` — trả `[]` là **đúng và có chủ đích**: suggestions gắn với một turn cụ
  thể, không phải trạng thái bền vững. Ghi rõ điều này vào docstring thay vì để nó trông
  như thiếu sót.

**Non-functional**
- Không duplicate logic: mọi hàm dựng payload phải là hàm dùng chung với `respond.py`.
- Session tồn tại nhưng chưa có turn nào → trả payload rỗng hợp lệ, không 404.

## Architecture

`respond.py` hiện giữ các hàm dựng payload ở dạng private (`_intake_status_from_travel_state`,
`_derive_stage`, `_hotel_options_from_task_results`). Restore cần đúng ba hàm đó.

**Quyết định:** tách chúng ra module mới `backend/src/agents/graph/response_payload.py`,
`respond.py` import lại. Lý do không để restore import hàm `_`-prefixed từ `respond`: đó
là node function của graph, import ngược từ tầng API vào node là đảo chiều phụ thuộc — và
tên `_`-prefixed là tín hiệu "không phải API công khai" cần được tôn trọng.

```
                    ┌─ respond.py (node)
response_payload.py ┤
                    └─ routes.py::restore_session
```

Nguồn dữ liệu cho restore:

| Field | Nguồn |
|---|---|
| `messages` | `session_store.restored_messages(rows)` với rows từ `session_store.load(session_id)["messages"]` |
| `stage` | `derive_stage(state, hotel_options)` từ module mới |
| `hotel_options` | `hotel_options_from_task_results(state)` từ module mới |
| `trip_plan` | `to_trip_plan_payload(state["trip_data"])` — **đã đúng, giữ nguyên** |
| `intake` | `intake_status_from_travel_state(TravelState.from_dict(state["travel_state"]))` |
| `suggestions` | `[]` — có chủ đích, ghi rõ lý do |

## Related Code Files

- Create: `backend/src/agents/graph/response_payload.py` — chuyển `_derive_stage`, `_hotel_options_from_task_results`, `_intake_status_from_travel_state`, `_budget_from_travel_state`, `_format_duration` sang đây
- Modify: `backend/src/agents/graph/nodes/respond.py` — import từ module mới, xóa bản copy
- Modify: `backend/src/api/routes.py` — viết lại `restore_session`
- Modify: `backend/src/models/schemas.py` — đánh dấu `IntakeStatus.from_state` là legacy/CLI-only hoặc xóa nếu không còn call site
- Create: `backend/tests/test_restore_endpoint.py`

## Implementation Steps

1. **Test đỏ trước.** `test_restore_returns_real_transcript_and_intake`: chạy 2 turn,
   gọi `/restore`, assert `messages` có đúng số dòng, `intake.destination` khớp,
   `hotel_options` không rỗng khi turn trước đó là hotel turn.
2. Tạo `response_payload.py`, di chuyển 5 hàm sang (đổi tên bỏ `_`). Chạy full test
   backend — `respond.py` phải pass y nguyên sau khi chuyển sang import.
3. Viết lại `restore_session` dùng các hàm đó + `restored_messages`.
4. Bổ sung docstring giải thích vì sao `suggestions` cố ý rỗng.
5. `grep` mọi call site còn lại của `IntakeStatus.from_state`. Nếu chỉ còn CLI → ghi chú
   trong docstring. Nếu không còn call site nào → xóa cùng test của nó.
6. Cập nhật `plans/frontend-session-persistence-plan.md`: đánh dấu acceptance criteria
   nào giờ đã đạt được (plan rời đó không có frontmatter status — thêm vào).
7. **Test cho nhánh postgres checkpointer** (**QĐ-2** trong `plan.md`). Nhánh
   `checkpointer_backend == "postgres"` ở `main.py:88-105` hiện **không có test nào phủ** —
   chỉ được verify bằng đọc code. GitNexus index còn trỏ tới
   `test_paused_thread_survives_a_simulated_process_restart` trong `test_interrupt_resume.py`,
   nhưng test đó **không còn tồn tại** trong file (index stale). Viết lại một test tương
   đương: build graph với `PostgresSaver`, chạy tới `interrupt()`, dựng graph mới từ cùng
   DSN (giả lập restart), assert resume được. Đánh dấu `@pytest.mark.skipif` khi thiếu
   `CHECKPOINTER_DATABASE_URL` để CI không đỏ ở máy không có Postgres.

## Success Criteria

- [x] `test_restore_endpoint.py` fail trước (8/10 đỏ), pass sau (10/10)
- [ ] Bấm một hội thoại cũ trong sidebar → chat hiện đúng nội dung, checklist intake đúng, itinerary panel đúng *(cần kiểm thủ công)*
- [x] Session chưa có turn nào → `/restore` trả 200 với payload rỗng, không 404
- [x] `grep -rn "hotel_options" backend/src/api/routes.py` không còn đọc key không tồn tại
- [x] Không có hàm nào bị copy-paste giữa `respond.py` và `routes.py` — cả hai import từ `response_payload.py`; có test khẳng định restore và một turn thật đồng ý với nhau
- [x] Với `CHECKPOINTER_BACKEND=memory` + restart: `/restore` trả payload **nhất quán** — `_restored_transcript` tách riêng, mất Supabase chỉ mất transcript
- [~] Nhánh `checkpointer_backend == "postgres"` có test; skip sạch khi thiếu DSN — **xem Ghi chú bên dưới**
- [x] Test suite backend đầy đủ pass sau khi di chuyển module (681 pass / 5 fail = baseline)

## Ghi chú thực thi (2026-08-16)

### Test postgres checkpointer: viết xong, **chưa chạy thật**

`tests/test_postgres_checkpointer.py` có 2 test và skip sạch khi thiếu
`CHECKPOINTER_DATABASE_URL` (xác nhận: `2 skipped`). Nhưng máy này **không có DSN**
(`backend/.env` không khai `CHECKPOINTER_DATABASE_URL`), nên nhánh `PostgresSaver` vẫn
chưa được thực thi lần nào.

Một test chỉ skip thì không chứng minh gì, nên phần thân test đã được verify riêng bằng
cách chạy chính hai hàm đó với một `MemorySaver` dùng chung (script tạm trong scratchpad):
cả hai pass. Nghĩa là logic lái graph (điểm pause, resume, đọc lại state) đúng; **chỉ còn
`PostgresSaver.from_conn_string(...)` là chưa được chạy**.

Lần verify đầu tiên **fail** và bắt được lỗi thật trong test: `budget.target` là slot bị
gate trước `hotel_node`, thiếu nó thì turn dừng ở `ask_slot` và không bao giờ tới chỗ
`interrupt()`. Đây chính là lý do phải verify thay vì tin vào một test chỉ biết skip.

**Việc còn lại:** chạy `CHECKPOINTER_DATABASE_URL=<dsn> pytest tests/test_postgres_checkpointer.py`
ở nơi có Postgres. Cho tới lúc đó, đường thoát của QĐ-2 vẫn chưa được chứng minh end-to-end.

### `IntakeStatus.from_state` đã bị xóa

Sau khi viết lại `restore_session`, `grep` xác nhận **không còn call site nào** (chỉ có
đúng một, chính là dòng bị thay). Đã xóa cùng hai helper riêng của nó
(`_available_destination_names`, `_budget_tier_labels`) — cả hai chỉ tồn tại để phục vụ
`from_state` và trở thành code chết cùng lúc. Docstring module `schemas.py` cập nhật để
lần đọc sau biết nó đi đâu, không phải biến mất.

### Bug bắt được khi viết test

Fixture đầu tiên dựng `hotel_search_result = {"hotels": [...]}`. Test đỏ, và **code đúng**:
`hotel_node.py:339` ghi `{"options": [...], "active_preferences": [...]}`, và
`to_hotel_options_payload` chỉ đọc key `options`. Đã sửa fixture cho khớp shape thật.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **`CHECKPOINTER_BACKEND=memory` → restart mất `travel_state`/`trip_data`** | Trung bình | **Degrade đã được chấp nhận có ý thức — QĐ-2 trong `plan.md`.** Không rebuild `travel_state` từ `context_data` (tạo nguồn sự thật thứ hai). Yêu cầu: payload phải **nhất quán** (transcript + intake rỗng), không nửa vời. Đường thoát production là `CHECKPOINTER_BACKEND=postgres`, đã wired đầy đủ nhưng chưa có test — bước 7 bổ sung |
| Nhánh postgres checkpointer chưa từng được test | Trung bình | Bước 7. Nhánh này là điều kiện để QĐ-2 chấp nhận được ở production; ship mà chưa test nghĩa là đường thoát chưa được chứng minh tồn tại |
| Di chuyển hàm làm vỡ test hiện có của `respond` | Trung bình | Bước 2 chạy full suite ngay sau khi move, trước khi viết logic mới |
| `restored_messages` map `stage` cứng thành `"intake"` (`session_store.py:352`) | Thấp | FE bỏ qua `stage` của message khi restore trừ lúc tính `isError`. Ghi nhận, xử lý ở Phase 7 nếu cần |
| Vòng import `response_payload` ↔ `schemas` | Trung bình | `response_payload` import `schemas`, không ngược lại. Test `test_domain_layer_purity.py` đã có sẵn để bắt vi phạm hướng phụ thuộc |
