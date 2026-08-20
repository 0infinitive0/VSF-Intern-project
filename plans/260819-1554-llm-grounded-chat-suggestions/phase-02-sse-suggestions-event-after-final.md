---
phase: 2
title: "SSE suggestions event after final"
status: done
priority: P1
effort: "0.5d"
dependencies: [1]
---

# Phase 2: SSE suggestions event after final

## Overview

Gỡ hoàn toàn việc sinh gợi ý ra khỏi node `respond`, chuyển sang worker của
endpoint stream: phát `final` trước, gọi LLM sau, rồi phát event
`suggestions`.

## Requirements

**Functional**
- `respond` không còn gọi `generate_next_chat_suggestions`; payload trả
  `suggestions: []`.
- `planner_chat_stream` phát thêm đúng một frame `event: suggestions` sau
  `final`, trước khi `close()`. **Danh sách rỗng thì không phát frame nào** —
  Phase 1 trả `[]` khi LLM hỏng, và "không có event" đã là trạng thái hợp lệ
  nên FE không cần biết phân biệt "chưa có" với "không có".
- Gate theo worker: chỉ chạy khi `task_results[-1]["worker"]` thuộc
  `{hotel_node, itinerary_node, budget_check, booking_node}` và `status`
  không phải nhánh lỗi/từ chối (quyết định validation #2: bỏ qua **hết** turn
  lỗi — không card, không trip thì không có gì để grounding, gợi ý sẽ bịa).
- Context mang `language` lấy từ state (`respond.py:344` đã phân nhánh
  `en`/`vi`) để chip khớp ngôn ngữ hội thoại.
- Lỗi ở bước suggestion không được ảnh hưởng tới stream: đã có `final` rồi,
  `close()` vẫn phải chạy.

**Non-functional**
- Việc đọc state để dựng context làm **bên trong** `session.lock`; lời gọi LLM
  và `emit` làm **bên ngoài** lock (tránh giữ lock qua một network call).

## Architecture

```
_run_turn (executor thread)
 ├─ with session.lock:
 │    response = _run_turn_via_graph(..., stream=True)
 │    ctx = _suggestion_context(app, config, response)   # đọc state, rẻ, không LLM
 ├─ emitter.emit("final", **response.model_dump())        # reply lên màn hình NGAY
 ├─ if ctx: chips = generate_next_chat_suggestions(ctx)   # LLM, ngoài lock
 │          if chips:                                    # rỗng → không phát
 │              emitter.emit("suggestions", session_id=..., suggestions=chips)
 └─ finally: emitter.close()
```

Thứ tự frame do queue của `TurnEmitter` bảo đảm (`streaming.py:113-114`), nên
`final` chắc chắn tới trước `suggestions`.

Contract "đúng một terminal frame (`final` | `error`)" ở
`docs/chat_api_contract.md` vẫn giữ: `suggestions` là frame **phi terminal**
phát sau terminal frame. Ghi rõ điều này trong doc ở Phase 4 vì nó là ngoại lệ
duy nhất.

## Related Code Files

- Modify: `backend/src/agents/graph/nodes/respond.py`
  - Xoá `_LAST_ACTION_BY_STAGE` (207-209) và `_suggestions_for_stage` (212-219).
  - `"suggestions": []` trong dict `response` (383).
  - Xoá `_available_preferences_from_hotel_options` (241-254) — **dead code
    hiện tại, không có call site nào**; nó là tàn dư của quyết định đã ghi ở
    comment 371-373.
  - Cập nhật docstring module (66-67 nhắc "Phase 17 gọi
    `generate_next_chat_suggestions`") cho khớp.
  - **Chạy `impact({target: "respond", direction: "upstream"})` trước khi sửa.**
- Modify: `backend/src/api/routes.py`
  - `planner_chat_stream._run_turn`: thêm bước dựng context + emit.
  - Helper `_suggestion_context(app, config, response) -> SuggestionContext | None`
    đặt cạnh `_response_from_result`; đọc worker qua
    `last_worker_from_task_results` (Phase 1) từ `app.get_state(config).values`.
  - `POST /planner_chat` (không stream) **không đổi** → luôn `suggestions: []`.

## Implementation Steps

1. Xoá 3 khối trong `respond.py`, đặt `"suggestions": []`, sửa docstring.
2. Thêm `_SUGGESTION_WORKERS` và `_SKIP_STATUSES` (các status lỗi/từ chối như
   `no_destination`, `unknown_destination`, `error`, `partial_error`,
   `declined`, `blocked`) vào `routes.py`.
3. Viết `_suggestion_context(...)`: lấy `hotel_options`, `hotel_amenities`,
   `trip_plan`, `reply`, `stage` từ `response`; lấy destination từ
   `response.intake`; lấy worker/status và `language` từ state. Trả `None`
   nếu không đủ điều kiện.
4. Sửa `_run_turn`: gọi context bên trong lock, emit `final`, rồi gọi LLM +
   emit `suggestions` trong `try/except` riêng (log rồi bỏ qua nếu lỗi).
5. Thêm test: một turn hotel phát `final` rồi `suggestions`, đúng thứ tự; một
   turn `qa_node` không phát `suggestions`.

## Success Criteria

- [x] `grep -rn "generate_next_chat_suggestions" backend/src/agents/` không còn kết quả.
- [x] Test SSE: danh sách event của turn hotel là `[..., "final", "suggestions"]`.
- [x] Test SSE: `generate_next_chat_suggestions` trả `[]` → không có frame `suggestions` nào.
- [x] Test SSE: turn qa (không ghi `task_results`) không có frame `suggestions`.
- [x] `generate_next_chat_suggestions` ném exception → stream vẫn kết thúc bình thường sau `final`.
- [x] `POST /planner_chat` vẫn trả 200 với `suggestions: []`.

## Risk Assessment

- **`app.get_state` sau khi nhả lock có thể đọc state của turn khác.** Giảm
  thiểu: đọc state và dựng context **trong** lock; chỉ lời gọi LLM ra ngoài.
- **Mất chip trên đường fallback POST.** Chấp nhận có chủ đích (quyết định
  validation #3): FE chỉ dùng POST khi `StreamUnsupported`, và duy trì hai
  đường sinh chip song song đắt hơn giá trị nó mang lại. Ghi vào doc ở Phase 4.
- **Client cũ dừng đọc ở `final`.** Không vỡ; chỉ không có chip cho tới khi
  Phase 3 lên.
