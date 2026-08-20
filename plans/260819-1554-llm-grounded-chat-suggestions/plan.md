---
title: "LLM grounded chat suggestions"
description: "Luôn sinh gợi ý bằng LLM có grounding từ dữ liệu turn thật, gate theo worker, giao qua SSE event riêng sau `final`"
status: completed
priority: P1
effort: "2-3d"
tags: [backend, frontend, sse, llm]
created: 2026-08-19
blockedBy: []
blocks: []
---

# LLM grounded chat suggestions

## Overview

`backend/src/services/suggestions.py` hiện trả list hardcode cho nhánh
`recommend_hotels`/`finalized` và chỉ gọi LLM ở nhánh "general" — nhánh mà
đường web **không bao giờ** chạm tới (`_LAST_ACTION_BY_STAGE` trong
`respond.py:207-209` chỉ map `hotel_options` → `recommend_hotels`, tức nhánh
hardcode). Hệ quả đo được:

- Chip `"Lọc theo đánh giá cao hơn"` không thực thi được: slot
  `hotel_preferences.min_review_score` là number range 0-10
  (`travel_state.py:614`), câu không có số nên không extract ra giá trị.
- Chip `"Lọc khách sạn có bể bơi và bao gồm ăn sáng"` hardcode tiện ích mà
  không biết card đang hiển thị có gì → có thể lọc ra 0 kết quả.
- Chip biến mất vĩnh viễn sau khi có lịch trình: `derive_stage` ưu tiên
  `planned` > `hotel_options` (`response_payload.py:175-178`) và `trip_data`
  không bao giờ reset.
- Parse JSON thủ công: shape sai → fallback im lặng, không log
  (`suggestions.py:75-86`).

Plan này chuyển sang: **luôn dùng LLM**, grounding bằng dữ liệu thật của turn,
gate theo **worker đã chạy trong turn** thay vì `stage`, và giao chip qua **SSE
event `suggestions` phát sau `final`** để không làm chậm reply.

## Quyết định đã chốt

| # | Quyết định | Lý do |
|---|-----------|-------|
| 1 | Luôn gọi LLM, bỏ toàn bộ list hardcode | User chọn. Xem #5 cho trường hợp LLM hỏng |
| 2 | Gate theo `task_results[-1]["worker"]` | `load_context.py:69` reset `task_results` mỗi turn ⇒ đây là tín hiệu "turn này vừa làm gì" thật sự; `stage=planned` thì sticky nên không dùng được. Lấp đúng khoảng trống mà `respond.py:203-206` đã ghi chú |
| 3 | Chip giao qua SSE event riêng sau `final` | User chọn — reply không chậm thêm chút nào |
| 4 | Bật cho `hotel_node`, `itinerary_node`, `budget_check`, `booking_node` | `qa_node` không ghi `task_results` (`qa_node.py:90`) nên tự động bị loại; `scope_guard` bị loại có chủ đích |
| 5 | LLM hỏng → **không chip nào**, bỏ hẳn fallback tĩnh | Validation #1. List hardcode chính là thứ đẻ ra lỗi đang sửa; "không có event" đã là trạng thái hợp lệ trong thiết kế SSE |
| 6 | Turn có worker nhưng status lỗi → bỏ qua hết | Validation #2. Không card, không trip ⇒ không có gì để grounding, gợi ý sẽ bịa |
| 7 | Endpoint không stream luôn trả `suggestions: []` | Validation #3. Không duy trì hai đường sinh chip song song |
| 8 | Ngôn ngữ chip theo `state["language"]` | Validation #4. Backend đã phân nhánh `en`/`vi` tại `respond.py:344`; dùng LLM rồi thì gần như miễn phí |

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Mọi chip đều gửi được thẳng vào chat và thực thi được (có số cụ thể, chỉ nhắc tiện ích có thật trên card) | P1 |
| 2 | Chip xuất hiện trên mọi turn có thay đổi thật, không chỉ turn hotel | P1 |
| 3 | Reply không chậm thêm mili-giây nào vì suggestion | P1 |
| 4 | LLM trả sai shape phải có log, không im lặng | P2 |
| 5 | Chip khớp ngôn ngữ hội thoại (`en`/`vi`) | P2 |

## Non-goals

- Không đổi cơ chế filter/preference panel (`all_preferences`/`active_preferences`) — comment ở `respond.py:371-373` nói rõ đó là hành vi có chủ đích.
- Không thêm cache. Nếu đo thấy tốn, mở plan riêng.
- Không đổi gate `lastStage !== 'intake'` ở `chat-panel.tsx:247` (giờ thừa nhưng vô hại).

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: Grounded suggestion service](./phase-01-grounded-suggestion-service.md) | Done |
| 2 | [Phase 2: SSE suggestions event after final](./phase-02-sse-suggestions-event-after-final.md) | Done |
| 3 | [Phase 3: Frontend late suggestions consumption](./phase-03-frontend-late-suggestions-consumption.md) | Done |
| 4 | [Phase 4: Contract docs and verification](./phase-04-contract-docs-and-verification.md) | Done |

Dependencies: 2 phụ thuộc 1; 3 phụ thuộc 2; 4 phụ thuộc 1-3.

## Files touched

| Phase | Files |
|-------|-------|
| 1 | `backend/src/services/suggestions.py` (rewrite), `backend/src/services/llm.py` (thêm `timeout` cho nhánh OpenAI), `backend/src/agents/graph/response_payload.py` (helper `last_worker_from_task_results`), `backend/src/cli/terminal_chat.py` (đổi call site) |
| 2 | `backend/src/agents/graph/nodes/respond.py` (xóa `_LAST_ACTION_BY_STAGE`, `_suggestions_for_stage`, `_available_preferences_from_hotel_options`), `backend/src/api/routes.py` (`planner_chat_stream._run_turn`) |
| 3 | `frontend/src/api/stream-client.ts`, `frontend/src/hooks/use-chat-session.ts` (union `Action` nằm ở đây, không phải `types/index.ts`) |
| 4 | `docs/chat_api_contract.md`, `backend/tests/test_suggestions.py`, test mới cho routes/stream, `frontend/src/api/stream-client.test.ts`, `frontend/src/hooks/use-chat-session.test.ts` |

## Success Criteria

- [x] Không còn bất kỳ list gợi ý hardcode nào trong `suggestions.py`.
- [x] Chip lọc luôn kèm số cụ thể; không chip nào nhắc tiện ích vắng mặt trên card đang hiển thị. (Ràng buộc ở tầng prompt, khẳng định bằng test đọc prompt — không khẳng định output LLM thật, đúng như Phase 1 đã ghi.)
- [x] Turn `itinerary_node` và `budget_check` có chip (trước đây luôn rỗng). Verified trực tiếp bằng `TestSuggestionContext::test_itinerary_node_and_budget_check_are_gated_in`.
- [x] Frame `final` đến trước lời gọi LLM suggestion; đo bằng test SSE thứ tự frame.
- [x] LLM trả shape sai → có `logger.warning`, trả `[]`, không exception thoát ra caller.
- [x] Hội thoại tiếng Anh → chip tiếng Anh.
- [x] `pytest backend/tests` và `npm test` (frontend) xanh — trừ 14 test thất bại từ trước (không liên quan, verify bằng `git stash`): 6 `test_llm_provider.py`, 2 `test_room_availability_schema.py`, 4 `test_supabase_search.py`, 1 `test_trip_modification.py`, 1 `merge-active-session.test.ts` (frontend).

## Rủi ro chính

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Thêm 1 LLM call mỗi turn có worker | Dùng `get_fast_llm`, context cắt gọn, limit 3; `qa_node`/`scope_guard`/intake không tính |
| Mọi endpoint không stream sẽ luôn trả `suggestions: []` | Không chỉ `POST /planner_chat`: `applyPlannerResponse` (`use-chat-session.ts:113`) cũng chạy cho `HOTEL_SELECTION_SUCCESS` và `RESTORE`, và `_response_from_result` dùng chung cho `change_hotel`. Nên **turn chọn khách sạn qua `POST /hotels/select` cũng mất chip**. Trước đây turn đó cũng không có chip (stage `hotel_options` chỉ xuất hiện khi còn card), nên đây không phải hồi quy — nhưng phải ghi vào contract doc ở Phase 4 |
| Client SSE cũ dừng đọc tại `final` → mất chip | Không vỡ gì: `stream-client.ts` có `default: break` forward-compatible; chip chỉ đơn giản không xuất hiện |
| GitNexus MCP không kết nối trong session này nên chưa chạy `impact()` theo CLAUDE.md | Đã trace bằng grep/đọc code; **chạy `impact()` trước khi sửa `get_llm` và `respond`** ở bước implement |

## Chồng lấn với plan khác

- `plans/260816-2205-fe-be-contract-reconciliation` (pending) phase-05 và
  `plans/260818-0924-deepdive-thinking-loader` (pending) phase-03 cùng liệt kê
  `frontend/src/api/stream-client.ts`. Đối chiếu code hiện tại: các sửa đổi đó
  (`case 'reasoning'`, `onPhase(key, at, d)`) **đã có trong file**, nên đây là
  chồng lấn lịch sử chứ không phải blocker. Không đặt `blockedBy`.
- `260816-2205` phase-02 chốt `restore` trả `suggestions=[]` có chủ đích — plan
  này giữ nguyên quyết định đó.

## Open questions

- Chưa đo chi phí/độ trễ thật của `get_fast_llm` với prompt suggestion. Nếu p95 > ~3s, cân nhắc mở plan cache theo `(worker, hash danh sách hotel/trip)`.
- Có nên cấp chip cho turn chọn khách sạn (`POST /hotels/select`) không? Hiện quyết định #7 nói không. Nếu muốn, cần một plan riêng đưa endpoint đó sang SSE.

## Validation Log

### Session 1 — 2026-08-19

**Verification Results**
- Claims checked: 24
- Verified: 23 | Failed: 1 | Unverified: 0
- Tier: Standard (4 phases, Fact Checker + Contract Verifier)
- Failure: Phase 3 ghi union action nằm ở `frontend/src/types/index.ts` — sai.
  Union `Action` khai báo tại `use-chat-session.ts:73`, biến thể `STREAM_DELTA`
  tại dòng 94; `types/index.ts` không chứa action nào. Đã sửa Phase 3, và ghi
  rõ file đó không cần đụng tới.

**Quyết định đã chốt** (chi tiết ở bảng "Quyết định đã chốt" #5-#8)
1. LLM hỏng → không chip nào, bỏ hẳn fallback tĩnh.
2. Turn có worker nhưng status lỗi → bỏ qua hết, không gọi LLM.
3. Endpoint không stream luôn trả `suggestions: []`.
4. Ngôn ngữ chip theo `state["language"]`.

**Propagation**
- Phase 1: Overview, Requirements, Architecture, Steps 2/5, Success Criteria, Risk.
- Phase 2: Requirements (không phát frame khi rỗng, gate status, language), Architecture, Step 3, Success Criteria, Risk.
- Phase 3: Requirements (không có frame = trạng thái hợp lệ), Related Code Files (sửa claim FAILED), Step 3.
- Phase 4: thêm mục doc cho endpoint không stream.

### Whole-Plan Consistency Sweep

- Không còn tham chiếu `_FALLBACK` nào sau khi bỏ fallback tĩnh.
- Số dòng `_LAST_ACTION_BY_STAGE` sửa từ `206-209` → `207-209` cho khớp nguồn.
- Phát hiện mới trong lúc sweep: quyết định #7 ảnh hưởng rộng hơn mô tả ban
  đầu — `applyPlannerResponse` dùng chung cho `SEND_SUCCESS`,
  `HOTEL_SELECTION_SUCCESS`, `RESTORE`, và `_response_from_result` dùng chung
  cho `change_hotel`. Đã ghi vào bảng rủi ro; **không phải hồi quy** vì turn
  chọn khách sạn hiện cũng không có chip.
- Mâu thuẫn chưa giải quyết: không có.

### Implementation — 2026-08-19

Tất cả 4 phase đã code + test xanh (xem Success Criteria). Code review
(`code-reviewer` subagent) tìm 2 HIGH + 4 MEDIUM + 4 LOW; đã sửa:

- **HIGH** `stream-client.ts`: một lỗi đọc SSE SAU khi `final` đã tới (network
  drop, hoặc `abort()` từ turn kế tiếp) từng làm promise reject dù reply đã
  hiển thị đúng — giờ trả `finalData` nếu đã có, chỉ throw khi `finalData`
  còn `null`.
- **HIGH** `use-chat-session.ts`: `pending` giờ gỡ tại `final` chứ không đợi
  cả stream đóng, nên turn N có thể vẫn đang đọc dở (chờ frame `suggestions`)
  khi user gửi turn N+1 — hai turn liên tiếp trong cùng session dùng chung
  một `turnId` (chỉ tăng ở RESET/RESTORE) nên guard đó không chặn được. Sửa:
  `send()` gọi `abortRef.current?.abort()` trước khi mở turn mới, cùng
  pattern `startNew()`/`restore()` đã dùng.
- **MEDIUM** `_SKIP_STATUSES` (`routes.py`) thiếu `hotel_selection_failed` và
  `already_paid` — turn chọn khách sạn thất bại hoặc đoạn chat đã khoá (thanh
  toán xong) vẫn sinh chip trước đó. Đã thêm cả hai.
- **MEDIUM** `generate_next_chat_suggestions` chỉ có timeout ở nhánh OpenAI
  (`get_llm`'s `timeout=`); nhánh Ollama fallback có thể treo vô hạn, giữ
  executor slot. Thêm wall-clock guard bằng `concurrent.futures` bọc ngoài,
  áp dụng cho mọi provider.
- **MEDIUM** `_suggestion_context` trước đó không có test trực tiếp (chỉ test
  qua mock). Thêm `TestSuggestionContext` (12 test) phủ gating theo
  worker/status, mapping card/amenity/filter, language switch, trip duration.
- LOW: gộp nhánh trùng trong `_cli_suggestion_context`; assert `timeout`
  kwarg trong test cũ.

Chưa sửa (ghi nhận, không phải regression):
- `_suggestion_context` đọc `app.get_state()` thêm một lần trong
  `session.lock`, trùng với lần `_persist_turn` đã đọc — chấp nhận theo
  non-goal "không thêm cache/tối ưu sớm; đo được thì mở plan riêng".
- `active_preferences[].label` (từ `_payload_preferences`) luôn tiếng Việt dù
  hội thoại tiếng Anh — hạn chế có sẵn của `PreferencePayload` (không có
  `label_en`), không phải hồi quy của plan này.
- `terminal_chat.py` có lỗi import `process_chat_turn` **có sẵn từ trước**
  (verify bằng `git show HEAD:...`), không phải do plan này gây ra — CLI hiện
  không import được nên tiêu chí "chạy được với API mới" chỉ đúng ở mức code,
  chưa smoke-test được qua CLI thật.

<!-- slug: llm-grounded-chat-suggestions -->
