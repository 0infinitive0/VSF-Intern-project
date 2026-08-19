---
title: "Route nearby-places questions to itinerary_node"
description: "Câu hỏi đọc-only kiểu \"liệt kê địa điểm nổi bật trong bán kính Xkm\" đang bị supervisor auto-route thẳng vào qa_node (không bao giờ ghi suggested_places → map trắng), thay vì itinerary_node's list_nearby action vốn được xây riêng cho case này."
status: pending
priority: P1
effort: "0.5-1d"
tags: [backend, langgraph, supervisor, routing, bugfix, map]
created: 2026-08-19
blockedBy: []
blocks: []
---

# Route nearby-places questions to itinerary_node

## Overview

User hỏi "liệt kê các địa điểm nổi bật trong vòng bán kính 3km" sau khi đã có
lịch trình + khách sạn. Chat trả lời đúng — liệt kê tên chỗ — nhưng **map
không hiện pin nào**. Xác minh bằng LangSmith trace thật
(`thread_id=14166be7-d2b8-4ab1-804e-4886120da894`, turn `2026-08-19T09:08:00Z`,
project `ai-thuctap-prod`):

```
"next_worker":"qa_node"
"task_description":"auto-routed to qa_node via read_only_intent"
"routing_source":"read_only_intent"
```

`qa_node`'s ReAct agent tự nhận ra giới hạn của tool trong reasoning:
*"there's a restriction on using a radius parameter"* — rồi gọi
`search_places(query="địa điểm nổi bật", near="Khách sạn Boutique The
Signature Sài Gòn", ...)`, không kèm bán kính. Tool trả text list đúng tên
chỗ nhưng **không bao giờ ghi `task_results`** (`agents/tools/search_places.py`
chỉ trả `ToolMessage`), nên `suggested_places_from_task_results`
(`response_payload.py:122-135`) đọc `task_results[-1]` và luôn ra `[]` — map
0 pin. Khớp chính xác ảnh user gửi (pin lộ trình theo ngày vẫn còn, không có
pin "gợi ý" xám tròn của `map-view.tsx:464-482`).

**Root cause thật sự không phải ở `qa_node` hay ở FE** — cả hai đều làm đúng
việc của chúng. Root cause nằm ở một deterministic shortcut trong
`supervisor.py:201-219`:

```python
if not workers and state.get("intent") == _READ_ONLY_INTENT:  # "general_question"
    return _delegate("qa_node", "read_only_intent", state)
```

`extract_patch` phân loại "liệt kê địa điểm nổi bật..." là `general_question`
— **đúng** theo spec của chính nó (`prompts.py:78`: câu hỏi về "cái gì hay ho
xung quanh" là request-thông-tin, không phải statement thay đổi trip). Nhưng
`intent` enum chỉ có 6 giá trị
(`hotel_search|update_itinerary|update_trip|select_hotel|finalize|general_question`,
`extract_patch.py:102`) — **không có** intent riêng cho "liệt kê gần đây".
Shortcut ở trên coi MỌI `general_question` là việc của `qa_node`, và nó chạy
**trước** LLM supervisor (dòng 240-258) — nơi duy nhất biết phân biệt
`list_nearby` (thuộc `itinerary_node`, đã viết rõ ở `prompts.py:22,32`) với
một câu hỏi qa_node thật. Kết quả: `itinerary_node`'s `list_nearby` **không
bao giờ reachable được** cho một câu hỏi "gần đây có gì" đứng một mình (không
đi kèm `pending_tasks` từ impact map).

Comment gốc ở `supervisor.py:201-217` giải thích rõ TẠI SAO shortcut này tồn
tại: một bug thật trước đây — "ngày 3 tôi làm gì?" (câu hỏi đọc-only chính
hiệu) rơi vào nhánh LLM không ràng buộc, và model chọn nhầm
`itinerary_node`/`rebuild_days`, **âm thầm build lại cả lịch trình** (địa
điểm ngày 1 đổi từ Bãi biển Mỹ Khê sang Đức Maria Mẹ Sao Biển, reply không hề
nói gì). Fix ở đây **không được mở lại bug đó**.

## Root cause (đã verify bằng code + trace, không phải suy đoán)

| Bằng chứng | Nguồn |
|---|---|
| `next_worker="qa_node"`, `routing_source="read_only_intent"` cho đúng turn hỏi 3km | LangSmith trace, `01a01947-0688-78a0-8abb-4caeb181fda2` |
| Model tự note thiếu radius param trong reasoning | Cùng trace, `reasoning`/`summary_text` |
| `search_places` không ghi `task_results` | `agents/tools/search_places.py` (toàn bộ file — chỉ `Command(update={"messages": ...})`) |
| `itinerary_node.list_nearby` CÓ ghi `suggested_places`, chưa từng chạy được | `itinerary_node.py:475-501`, `_suggested_places_payload` dòng 276-293 |
| Shortcut chặn LLM supervisor cho mọi `general_question` khi `workers` rỗng | `supervisor.py:201-219` |
| `intent` enum không có case riêng cho nearby-listing | `extract_patch.py:102` |
| Đường này hoàn toàn chưa có test | `grep read_only_intent backend/tests/test_supervisor_routing.py` → 0 kết quả |

## Quyết định đã chốt

| # | Quyết định | Lý do |
|---|-----------|-------|
| 1 | **Không** mở rộng `intent` enum. Thay vào đó thêm một field PHỤ `asks_nearby_places: bool` vào output của `extract_patch` | `extract_patch.py:4-5` ghi thành invariant: *"`intent` never selects a WORKER — `detect_impact` + `WORKFLOW_TO_WORKER` does that"*. Thêm giá trị vào `_INTENTS` để nó tự chọn `itinerary_node` là ngoại lệ thứ hai phá cùng invariant đó, đồng thời buộc rà lại `_INCOMPLETE_EDIT_INTENTS`, `_READ_ONLY_INTENT` rescue gate (dòng 291) và `is_intake_question`. Field phụ không đụng thứ nào trong số đó |
| 2 | Field mới parse **non-strict**, y hệt khuôn `reason` đã có | Module docstring (dòng 19-23) chốt sẵn khuôn này cho `reason`: *"a missing key, a null, a non-string, or an unrecognized value all fall open to `""` rather than spending the retry"*. Đi theo đúng khuôn ⇒ field mới **không thể** gây retry, không thể gây fallback, không thể làm hỏng turn nào đang chạy. Đây là thứ khử phần lớn blast radius của việc đụng vào node chạy mọi turn |
| 3 | Tái dùng LLM call `extract_patch` đã chạy sẵn mỗi turn — **không** thêm call nào | `extract_patch` đã tốn đúng 1 call cho mọi turn bất kể nội dung. Nhét thêm 1 field vào chính call đó là miễn phí. Mọi phương án khác (keyword filter, hay gọi LLM supervisor lần 2) đều hoặc phải maintain wordlist, hoặc +1 round-trip cho toàn bộ traffic read-only |
| 4 | Supervisor dựng `task_description` JSON **deterministic**, hardcode `action="list_nearby"` — bỏ hẳn LLM call thứ 2 | `_resolve_radius_km` (`itinerary_node.py:240-245`) đã có sẵn fallback regex `_extract_radius_km(user_request)`, dùng đúng khi LLM để trống `radius_km` — nên không cần hỏi model radius. Hardcode `action` đóng regression "ngày 3 tôi làm gì?" **chặt hơn cả validation**: model không còn được phép chọn action nào, không có đường nào chạm tới `rebuild_days`/`edit_item`/`lock_days` từ nhánh này |
| 5 | Không sửa `search_places`/`qa_node` để nó ghi `suggested_places` | **Bị chặn về mặt kiến trúc, không phải sở thích**: `qa_node.py:14-18` + `QAState` docstring nói `travel_state`/`pending_tasks`/`task_results` là *"structurally unreachable from inside it — the contract is enforced by the schema boundary itself"*. Muốn ghi phải widen `QAState` bằng key ghi được, tức phá chính contract `CONTRACTS["qa_node"].writes` đang giữ rỗng |
| 6 | Không đụng `SupervisorDecision` / `SUPERVISOR_SYSTEM_PROMPT` | Sau quyết định #4 thì nhánh này không gọi LLM supervisor nữa, nên không có gì để mở rộng. Phân loại `list_nearby` ở `prompts.py:22,32` vẫn giữ nguyên cho nhánh LLM path bình thường (turn có `pending_tasks`) |

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Câu hỏi "liệt kê/tìm/gợi ý địa điểm nổi bật/tham quan gần đây (trong bán kính Xkm)" khi đã có khách sạn → route tới `itinerary_node`/`list_nearby`, map nhận pin | P1 |
| 2 | Câu hỏi đọc-only khác ("ngày 3 tôi làm gì?", "phòng nào rẻ hơn?", …) tiếp tục route `qa_node` y hệt hiện tại, KHÔNG regress | P1 |
| 3 | **Không** tăng số LLM call cho bất kỳ turn nào — kể cả turn nearby lẫn turn read-only thường | P1 |
| 4 | Field mới không bao giờ làm `extract_patch` retry hoặc rơi fallback, kể cả khi model bỏ qua nó hoặc trả sai kiểu | P1 |

## Non-goals

- Không sửa `search_places`/`qa_node` để tự ghi `suggested_places` — xem quyết định #5 (bị chặn kiến trúc).
- Không mở rộng `intent` enum của `extract_patch.py` — xem quyết định #1.
- Không dùng keyword/wordlist filter ở bất kỳ đâu — đã cân nhắc và loại: phải
  maintain danh sách từ, không bắt được cách diễn đạt ngoài danh sách, và
  quyết định #3 khiến nó thành thừa.
- Không gọi LLM supervisor lần thứ hai để xác nhận — xem quyết định #4.
- Không đổi `docs/chat_api_contract.md` — `routing.worker` phase fact
  (`chat_api_contract.md:280`) đã liệt kê sẵn `qa_node`/`itinerary_node` như
  giá trị hợp lệ; fix này chỉ đổi turn nào nhận giá trị nào, không thêm giá
  trị mới, không đổi shape response.
- Không sửa case khi CHƯA có khách sạn (`trip_data` rỗng) — `itinerary_node`'s
  `list_nearby` đã tự trả lỗi rõ ràng cho case đó (`itinerary_node.py:476-482`,
  `"Mình cần bạn chọn khách sạn trước..."`), hành vi giữ nguyên.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [Phase 1: extract_patch nearby hint](./phase-01-extract-patch-nearby-hint.md) | Pending |
| 2 | [Phase 2: Supervisor routing fix](./phase-02-supervisor-routing-fix.md) | Pending |
| 3 | [Phase 3: Regression + coverage tests](./phase-03-regression-and-coverage-tests.md) | Pending |
| 4 | [Phase 4: Verify against real trace + ship](./phase-04-verify-and-ship.md) | Pending |

Dependencies: 2 phụ thuộc 1; 3 phụ thuộc 1-2; 4 phụ thuộc 1-3.

## Files touched

| Phase | Files |
|-------|-------|
| 1 | `backend/src/agents/graph/prompts.py` (thêm field vào schema + 1 dòng mô tả trong `_EXTRACT_PATCH_SYSTEM_PROMPT`), `backend/src/agents/graph/nodes/extract_patch.py` (parse non-strict + trả field), `backend/src/agents/graph/state.py` (khai báo `asks_nearby_places`), `backend/src/agents/graph/nodes/load_context.py` (reset turn-scoped) |
| 2 | `backend/src/agents/graph/nodes/supervisor.py` (đổi nhánh dòng 218-219, thêm `_nearby_task_description`) |
| 3 | `backend/tests/test_supervisor_routing.py`, `backend/tests/test_extract_patch.py` (xác nhận tên file khi thực thi) |
| 4 | Không sửa file — chạy pytest, GitNexus `impact()`/`detect_changes()`, đối chiếu LangSmith |

## Success Criteria

- [ ] Câu message y hệt trace lỗi ("liệt kê các địa điểm nổi bật trong vòng
      bán kính 3km", có khách sạn đã chọn) → `next_worker=itinerary_node`,
      `task_description` JSON có `"action":"list_nearby"`.
- [ ] `asks_nearby_places` vắng mặt / `null` / sai kiểu (list, số, string) →
      `extract_patch` trả `False`, KHÔNG retry, KHÔNG `extraction_failed`,
      turn hoàn tất bình thường — khoá đúng khuôn `reason` đã có.
- [ ] `asks_nearby_places=False` (câu hỏi đọc-only thường) → `qa_node`,
      `routing_source="read_only_intent"`, hành vi không đổi so với hôm nay.
- [ ] Không có `get_fast_llm` call nào phát sinh trong `supervisor` cho nhánh
      read-only — assert bằng `_unreachable_llm_factory` pattern có sẵn.
- [ ] Model KHÔNG có đường nào chọn được `rebuild_days`/`edit_item`/
      `lock_days` từ nhánh này — `action` là hằng số trong code, verify bằng
      đọc diff, không chỉ bằng test.
- [ ] `pytest backend/tests/test_supervisor_routing.py
      backend/tests/test_supervisor_llm_budget.py backend/tests/test_extract_patch.py`
      xanh.
- [ ] GitNexus `impact()` chạy cho CẢ `extract_patch` và `supervisor` trước
      khi sửa, risk level báo cáo cho user trước khi edit.
- [ ] `detect_changes()` trước khi commit, so với `main`.

## Rủi ro chính

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Đụng vào `extract_patch` — node chạy MỌI turn, blast radius rộng nhất graph | Field mới parse non-strict theo đúng khuôn `reason` (quyết định #2): mọi giá trị lạ đều fall open về `False`, không đường nào dẫn tới retry hay `extraction_failed`. Test riêng cho từng kiểu giá trị hỏng — success criteria #2 |
| Model bỏ qua field mới (prompt dài, field cuối bị lơ) → nearby request vẫn về `qa_node` | Không phải regression: bằng đúng hành vi hôm nay. Đo bằng LangSmith sau khi ship; nếu tỉ lệ miss cao thì tinh chỉnh wording prompt, không cần đổi kiến trúc |
| False positive: `asks_nearby_places=True` cho câu hỏi không phải nearby | Hậu quả tối đa là user nhận danh sách địa điểm thay vì câu trả lời qa — **degraded answer, không mutation**, vì `action` hardcode `list_nearby` (quyết định #4) và branch đó thuần đọc |
| Mở lại bug "ngày 3 tôi làm gì?" | Đóng chặt hơn bản validation: nhánh này KHÔNG hỏi model chọn action, `list_nearby` là hằng số trong code. Không tồn tại đường code nào từ nhánh này tới một action ghi dữ liệu |
| Thêm field vào prompt làm lệch chất lượng extract các field cũ (`intent`/`changes`) | Chạy `test_extract_patch.py` đầy đủ, không chỉ test mới; field thêm ở cuối schema, mô tả 1 dòng, không đổi wording của bất kỳ mục nào đang có |
| Quên reset `asks_nearby_places` trong `load_context` → giá trị turn cũ rò sang turn sau | Bắt buộc thêm vào dict return của `load_context` cùng lúc với khai báo state (Phase 1 gộp 1 bước), theo đúng comment `state.py` về `extraction_failed`/`patch_reason` |

## Chồng lấn với plan khác

- `plans/260812-0927-langgraph-orchestration-state-patch-and-interrupts`
  (pending, P1, ~28d) là plan thiết kế gốc đặt ra chính kiến trúc
  `qa_node`/`general_question` đang sửa ở đây (dòng 80-81 plan đó: *"The
  ReAct agent survives as `qa_node`, a worker subgraph. It handles the
  `general_question` intent only"*). Code hiện tại đã implement đúng kiến
  trúc đó — fix này KHÔNG đổi kiến trúc, chỉ vá một gap trong quy tắc
  route-by-intent mà plan gốc chưa lường tới (list_nearby không có intent
  riêng). Không đặt `blockedBy`/`blocks` vì không đổi shape state hay
  interface nào plan kia phụ thuộc.
- `plans/260819-1554-llm-grounded-chat-suggestions` (pending) cùng nói tới
  gap "`qa_node` không ghi `task_results`" nhưng cho **chip gợi ý** khác
  (`suggestions`), không phải **map pins** (`suggested_places`) — hai field
  khác nhau, hai plan độc lập, không overlap file.

## Open questions

- Tên chính xác của field: `asks_nearby_places` (đang dùng xuyên suốt plan).
  Nếu review thấy tên khác rõ hơn thì đổi đồng loạt ở cả 4 phase.
- Chưa đo tỉ lệ model thực sự set đúng field mới trên traffic thật. Sau khi
  ship, xem LangSmith vài chục turn read-only để biết có cần chỉnh wording
  prompt không — không block ship vì miss = hành vi hôm nay.

<!-- slug: route-nearby-places-questions-to-itinerary-node -->
