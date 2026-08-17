---
phase: 1
title: "Session persistence writer"
status: complete
priority: P1
effort: "2.5d"
dependencies: []
---

# Phase 1: Session persistence writer

## Overview

Viết một writer mới đọc thẳng `TravelGraphState` và ghi `sessions` + `chat_messages` với
**schema `context_data` v3**, thay cho `session_store.upsert(session: TripSession)` đã mất
call site sau cutover. Đây là phase chặn phần lớn giá trị người dùng: không có nó, lịch sử
hội thoại vĩnh viễn rỗng và Phase 2 không có gì để restore.

Quyết định schema: **QĐ-1** trong `plan.md` — v3 sạch, không tái dùng shape v2.

## Bằng chứng lỗi

- `_run_turn_via_graph` (`backend/src/api/routes.py:368-425`) không gọi `persist_hook`.
- `session.py:518` tự xác nhận: *"`_run_turn_via_graph` never touches TripSession.state"*.
- `supabase_persist_hook` → `session_store.upsert` chỉ còn 2 call site đều thuộc luồng
  legacy: `session.py:293` (`_clear_pending_hotel_selection`) và `session.py:311`
  (`clear_session_history`).
- `list_sessions` (`session_store.py:331`) join `chat_messages!inner(session_id)` →
  session không có message row không bao giờ xuất hiện.
- `backend/.env` đang bật `SESSION_PERSISTENCE_ENABLED=true` — lỗi không do tắt cờ.

## Requirements

**Functional**
- Sau mỗi chat turn hoàn tất (kể cả turn dừng ở `interrupt()`), ghi được: transcript,
  `travel_state`, và tóm tắt cho history rail.
- `summarize()` đọc được **cả v1, v2 và v3** — row cũ trong DB vẫn phải hiện ở sidebar.
- `deserialize()` gặp row v3 phải chặn tường minh, không rơi vào nhánh `_deserialize_v1`.
- Ghi best-effort: lỗi DB không được làm hỏng chat turn.
- Không ghi khi `SESSION_PERSISTENCE_ENABLED=false`.
- `owner_user_id` gán đúng từ `TripSession.owner_user_id` (registry vẫn giữ ownership).

**Non-functional**
- Không hồi sinh `TripSession.state` cho luồng HTTP.
- Writer **chỉ** ghi v3. Không viết migration ngược cho row cũ.
- Persist chạy **trong** `session.lock`, cùng critical section với turn — nếu không, hai
  turn song song có thể ghi đè transcript của nhau.

## Architecture

### Luồng

```
HIỆN TẠI
_run_turn_via_graph → app.invoke() → result["response"] → PlannerChatResponse
                                   (không có gì ghi xuống DB)

ĐÍCH
_run_turn_via_graph → app.invoke() → result
                    → persist_graph_session(session, final_state)   ← MỚI
                    → result["response"] → PlannerChatResponse
```

`persist_graph_session(session, state)` nhận cả hai:
- `session` chỉ dùng cho `session_id` và `owner_user_id`.
- `state` là `TravelGraphState` sau turn — nguồn của mọi dữ liệu nội dung.

### Schema `context_data` v3

```jsonc
{
  "schema_version": 3,
  // TravelState.to_dict() — dict phẳng theo ALLOWED_PATHS. Nguồn sự thật nghiệp vụ.
  "travel_state": { "destination": "...", "dates.start": "...", "people": 2, ... },
  // Con trỏ tới dữ liệu nằm ở bảng khác, không phải bản sao.
  "trip": { "itinerary_id": "...", "hotel_id": "...", "status": "Draft" },
  // Giữ NGUYÊN shape của v2 — đây là thứ summarize() đọc, và nó không có
  // từ vựng nào của plane cũ. Giữ lại là tiết kiệm thật, không phải nợ.
  "ui_summary": {
    "destination": "...", "duration_days": 4, "status": "draft",
    "hotel_name": "...", "thumbnail_url": "..."
  }
}
```

Khác v2 ở đâu và vì sao:

| v2 | v3 | Lý do |
|---|---|---|
| `workflow` = `_CHECKPOINT_FIELDS` của `TripSession` | `travel_state` = `TravelState.to_dict()` | v2 lưu từ vựng của plane đã chết |
| `current_trip` | `trip` | Đổi tên cho khớp nội dung; bỏ tiền tố "current" vô nghĩa khi mỗi session một trip |
| `pending_hotel_selection` (+ `_pending_hotel_checkpoint`, `_HOTEL_SNAPSHOT_FIELDS`) | **bỏ hẳn** | Khái niệm của plane cũ. Graph mang hotel options trong `task_results`, và chúng luôn dựng lại được từ `hotel_node` |
| `ui_summary` | **giữ nguyên** | `summarize()` đọc key này; shape đã sạch. Giữ lại nghĩa là `summarize()` chỉ cần nới điều kiện version, không viết lại |

### Ba hàm đọc phải học v3

| Hàm | Hiện tại | Sau phase |
|---|---|---|
| `summarize(row)` (`session_store.py:376`) | `if context.get("schema_version") == _CONTEXT_SCHEMA_VERSION` rồi đọc `ui_summary`; ngược lại suy từ `intake`/`trip_data` | Đổi thành `in (2, 3)` — cả hai đều có `ui_summary` cùng shape. Nhánh legacy giữ nguyên cho row v1 |
| `deserialize(...)` (`session_store.py:179`) | `!= v2` → `_deserialize_v1` | Thêm chặn: `== 3` → trả `{"messages": ...}` và **không** rebuild workflow. Row v3 không có gì để nhồi vào `TripSession.state` |
| `registry.get()` (`session.py:498`) | `session.state = deserialize(...)` + load `trip_data` từ `ItineraryStore` | Với row v3, `session.state` chỉ cần messages; nhánh `ItineraryStore.load_session_trip_data` là legacy — graph đọc `trip_data` từ checkpointer. Giữ nhánh cho row cũ, bỏ qua cho v3 |

Điểm mấu chốt: `registry.get()` với row v3 chỉ còn cần **hai** thứ cho graph plane — session
tồn tại, và `owner_user_id`. Phần rebuild `TripSession.state` trở thành no-op.

### Transcript — bẫy tool message

`state["messages"]` gồm cả `AIMessage` do ReAct subgraph của `qa_node` sinh (tool call,
tool result). Ghi hết vào `chat_messages` sẽ đẩy nội dung nội bộ lên UI.

Lọc: phía assistant **chỉ** ghi message có `additional_kwargs["emitted_by"] == "respond"`
— tag mà `respond.py:107` đã đặt sẵn. Đó chính xác là những gì user đã nhìn thấy, vì
`respond` là node duy nhất sinh reply. Phía user ghi mọi `HumanMessage`.

## Related Code Files

- Modify: `backend/src/services/session_store.py` — thêm `persist_graph_session`, `_graph_message_records`, `_v3_context`; sửa `summarize`/`deserialize` nhận v3; giữ `upsert`/`serialize` cho CLI
- Modify: `backend/src/agents/session.py` — `registry.get()` bỏ qua rebuild state cho row v3
- Modify: `backend/src/api/routes.py` — gọi persist trong `_run_turn_via_graph`; sửa docstring `create_session` (`routes.py:174-187` vẫn nói *"process_chat_turn and friends already call it"*, mà cascade đó đã bị xóa ở `e26d6f5`)
- Create: `backend/tests/test_graph_session_persistence.py`
- Modify: `backend/tests/test_session_store_deserialize.py` — thêm case v3

## Implementation Steps

1. **Test đỏ trước.** `test_graph_turn_persists_session`: chạy một turn qua
   `_run_turn_via_graph` với client Supabase giả, assert có row `sessions` với
   `schema_version == 3` và ít nhất 1 `chat_messages`. Phải fail trên `main` hiện tại.
2. Thêm `_CONTEXT_SCHEMA_VERSION_V3 = 3` và `_v3_context(session, state)` dựng payload v3.
   `ui_summary` tái dùng `_ui_summary` hiện có bằng cách truyền dict tương thích —
   **không** copy-paste logic.
3. Thêm `_graph_message_records(state)`: duyệt `state["messages"]`, giữ `human` và `ai`
   có `emitted_by == "respond"`; map sang `{sender_type, message_content, created_at}`.
4. Thêm `persist_graph_session`: gọi cùng RPC `persist_session_checkpoint` mà `upsert`
   đang dùng, giữ nguyên fallback `PGRST202` và `_stamp_owner`.
5. Sửa `summarize`: điều kiện version thành `in (2, 3)`. Test với row cả ba version.
6. Sửa `deserialize`: chặn v3 tường minh trước khi tới nhánh `_deserialize_v1`.
7. Sửa `registry.get()`: với row v3, bỏ qua khối rebuild `trip_data`/`ItineraryStore`.
8. Gọi `persist_graph_session` từ `_run_turn_via_graph`, trong `session.lock`, bọc
   try/except log-only theo đúng semantics best-effort của `supabase_persist_hook`.
9. Turn dừng ở `interrupt()` cũng phải persist: đặt lời gọi ở nhánh chung, **trước**
   `if interrupts:`, dùng `app.get_state(config).values` làm nguồn state.
10. Sửa docstring lỗi thời ở `routes.py:174-187`.

## Success Criteria

- [x] `test_graph_session_persistence.py` fail trước (17 fail), pass sau (25 pass)
- [x] Row mới có `schema_version == 3`; không có key `workflow` hay `pending_hotel_selection`
- [ ] `GET /chat/sessions` trả về session vừa chat, với `destination` và `status` đúng *(cần DB thật; `summarize` đã có test cho cả ba version, và `chat_messages` giờ có row nên inner-join qua được)*
- [x] Row v1 và v2 cũ **vẫn** hiện đúng ở history rail (test `summarize` cả ba version)
- [x] `deserialize` với row v3 không rơi vào `_deserialize_v1`
- [x] Transcript **không** chứa tool call/tool result của qa_node
- [x] Turn dừng ở interrupt vẫn tạo row
- [x] Ngắt Supabase → chat turn vẫn trả lời bình thường, chỉ có log ERROR
- [x] `SESSION_PERSISTENCE_ENABLED=false` → không có lời gọi DB nào
- [x] `test_legacy_guards.py` và `test_session_store_deserialize.py` pass
- [x] Full backend suite: 671 pass / 5 fail — đúng bằng baseline trước phase (5 lỗi có sẵn, không liên quan)

## Ghi chú thực thi (2026-08-16)

### Thêm ngoài plan: dấu thời gian `at` trên mỗi message

Plan không nói tới, nhưng writer bắt buộc phải có. `_write_checkpoint` **ghi lại toàn bộ
transcript mỗi lần persist** (nhánh fallback: `delete()` rồi `insert()` cả loạt). Nếu
`created_at` được đóng dấu `now()` lúc ghi, thì sau mỗi turn **mọi** message cũ nhảy sang
thời điểm hiện tại — cả hội thoại dồn về một mốc, và `load()` (`order("created_at")`) mất
thứ tự, FE mất giờ hiển thị.

Nên `at` được đóng dấu **một lần, tại nơi message được tạo**, rồi đi theo message qua
checkpointer:

- `routes.py::_invoke_fresh_turn` — `HumanMessage(additional_kwargs={"at": ...})`
- `respond.py` — thêm `"at"` vào `additional_kwargs` của reply (file này thuộc ranh giới
  Phase 2, nhưng phase chạy tuần tự nên không có xung đột merge)

Test `test_preserves_the_time_each_message_was_actually_sent` khóa hành vi này.

### Refactor nhỏ: `_write_checkpoint`

`upsert` (v2, cho CLI) và `persist_graph_session` (v3, cho HTTP) dùng chung đúng một
đường ghi: RPC → fallback `PGRST202` → `_stamp_owner`. Tách thành `_write_checkpoint`
thay vì copy, để hai writer không thể lệch nhau về retry semantics hay về bảng nào bị
chạm. `_stamp_owner` đổi sang nhận `(session_id, owner_user_id)` thay vì `TripSession` —
v3 không có `TripSession` để đưa vào.

### Sửa test hiện có (không phải nới lỏng)

`test_respond.py::test_the_reply_is_appended_tagged_with_the_slot_it_asked` so sánh
`additional_kwargs` bằng `==` với dict đầy đủ, nên khóa cứng cả những key nó không quan
tâm. Đổi sang assert đúng hai key nó thật sự kiểm (`emitted_by`, `asked_slot`), và **thêm**
test riêng cho `at` — tổng số assertion tăng, không giảm.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **Row v3 rơi vào `_deserialize_v1` → state rác** | Cao | Đây là hệ quả trực tiếp của QĐ-1 và là rủi ro số một của phase. Bước 6 chặn tường minh; test case riêng trong `test_session_store_deserialize.py` |
| Ghi cả tool message vào transcript → lộ nội dung nội bộ | Cao | Lọc theo tag `emitted_by == "respond"`; test khẳng định turn qa_node chỉ sinh 2 dòng |
| `summarize` vỡ với row cũ sau khi sửa điều kiện version | Cao | Bước 5 test cả ba version. Row v1/v2 tồn tại thật trong DB dev |
| Persist trong lock làm chậm turn | Trung bình | RPC một round-trip; đo trước/sau. Nếu chậm, chuyển nền nhưng **giữ trong lock cho tới khi đọc xong state** |
| `registry.get()` sửa nhầm làm hỏng rehydrate row cũ | Trung bình | Bước 7 chỉ thêm nhánh cho v3, không đụng nhánh cũ. Test rehydrate với row v2 |
| Trùng lặp với `frontend-session-persistence-plan.md` | Thấp | Plan đó là phía FE và đang fail vì backend; phase này làm nó chạy được. Cập nhật sau khi Phase 2 xong |
