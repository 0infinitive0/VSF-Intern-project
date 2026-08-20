---
phase: 1
title: "Grounded suggestion service"
status: done
priority: P1
effort: "1d"
dependencies: []
---

# Phase 1: Grounded suggestion service

## Overview

Viết lại `suggestions.py`: luôn gọi LLM, nhận context có grounding thật của
turn, dùng structured output thay parse JSON tay, hậu xử lý output. LLM hỏng
thì **không có chip nào**, không có fallback tĩnh.

## Requirements

**Functional**
- Không còn bất kỳ chuỗi gợi ý hardcode nào trong file. LLM lỗi / timeout /
  trả rỗng → trả `[]`.
- Input là dữ liệu thật của turn: worker + status, reply, destination, card
  khách sạn đang hiển thị, nhãn tiếng Việt của tiện ích **có trên card**,
  filter đang bật, số ngày của trip, language.
- Mọi gợi ý lọc phải kèm số cụ thể lấy từ dải giá trị thật của card.
- Cấm nhắc tiện ích không có trong danh sách nhãn được truyền vào.
- Mỗi gợi ý là một câu lệnh hoàn chỉnh gửi thẳng vào chat được, < 12 từ.
- Ngôn ngữ chip theo `context.language` (`respond.py:344` cho thấy backend đã
  phân nhánh `en`/`vi`), không mặc định tiếng Việt.

**Non-functional**
- Không exception nào thoát ra caller.
- Shape sai / rỗng → `logger.warning` rồi trả `[]` (hiện tại im lặng).
- Có timeout cho lời gọi LLM. Sau Phase 2 lời gọi này nằm ngoài đường đi của
  reply nên timeout không còn để cứu độ trễ, mà để một call treo không giữ mãi
  executor slot và kết nối SSE của turn đó.

## Architecture

```
respond/routes ──► SuggestionContext (dataclass, thuần dữ liệu)
                        │
                        ▼
            generate_next_chat_suggestions()
                        │
                 get_fast_llm(temperature=0.7, timeout=...)
                        │
              .with_structured_output(NextChatSuggestions)
                        │
                 _clean(): strip → bỏ tiền tố "1." → dedupe → [:limit]
                        │
                 rỗng/lỗi ──► [] + logger.warning
```

Không có fallback tĩnh (quyết định validation #1): list hardcode chính là thứ
đẻ ra lỗi đang sửa — chip không grounding, không thực thi được. Với thiết kế
SSE ở Phase 2, "không có chip" đã là trạng thái hợp lệ sẵn có (frame
`suggestions` đơn giản không được phát), nên FE không cần xử lý gì thêm.

`with_structured_output` là pattern đã có sẵn trong repo
(`supervisor.py:243`) — dùng lại thay vì tự bóc ```` ``` ```` + `json.loads` +
kiểm `isinstance`. Việc này xoá luôn 2 lỗi hiện tại: fence-strip chỉ chạy khi
chuỗi bắt đầu bằng ```` ``` ````, và nhánh shape-sai không log gì.

Nguồn grounding có sẵn, không phải tính mới:
- Card khách sạn: `hotel_options_from_task_results(state)`.
- Nhãn tiện ích trên card: `hotel_amenities_from_hotel_options(hotel_options)`
  → `AmenityCatalogPayload.label_vi` (`schemas.py:529-536`).
- Worker + status của turn: `task_results[-1]` — `load_context.py:69` reset
  mảng này mỗi turn nên nó chỉ chứa worker của turn hiện tại.

## Related Code Files

- Modify: `backend/src/services/suggestions.py` — rewrite.
- Modify: `backend/src/services/llm.py` — thêm `timeout: float | None` cho
  `get_llm` và `get_fast_llm`; chỉ áp cho nhánh OpenAI
  (`kwargs["timeout"]`), ghi docstring rằng nhánh Ollama không nhận.
  **Chạy `impact({target: "get_llm", direction: "upstream"})` trước khi sửa** —
  đây là factory dùng chung toàn backend.
- Modify: `backend/src/agents/graph/response_payload.py` — thêm
  `last_worker_from_task_results(state) -> tuple[str, str] | None` đặt cạnh
  `hotel_options_from_task_results` (cùng họ helper đọc `task_results`).
- Modify: `backend/src/cli/terminal_chat.py` — `_suggestion_action` hiện tự
  suy ra action từ `session`; thay bằng context dựng từ cùng helper để CLI và
  web không lệch nhau.

## Implementation Steps

1. Thêm `SuggestionContext` (frozen dataclass) và `NextChatSuggestions`
   (pydantic, field `suggestions: list[str]`) vào `suggestions.py`.
2. Viết prompt (ngôn ngữ output theo `context.language`) nhận context đã
   serialize gọn:
   - liệt kê tối đa 5 card: tên, giá, điểm đánh giá;
   - liệt kê nhãn tiện ích có thật;
   - nêu rõ hành động mà backend làm được ứng với worker của turn.
   Ràng buộc bắt buộc ghi trong prompt: chỉ dùng dữ liệu đã cho; gợi ý lọc
   phải có số; không nhắc tiện ích ngoài danh sách.
3. Đổi thân hàm sang `get_fast_llm(temperature=0.7, timeout=...)` +
   `.with_structured_output(NextChatSuggestions)`.
4. Viết `_clean(items, limit)`: strip, bỏ tiền tố đánh số, dedupe
   case-insensitive, bỏ rỗng, `[:max(1, limit)]`.
5. Xoá hết list hardcode; mọi đường thất bại đều trả `[]` kèm
   `logger.warning` nêu lý do (exception / shape sai / rỗng sau clean).
6. Thêm `last_worker_from_task_results` vào `response_payload.py`.
7. Cập nhật `terminal_chat.py` sang API mới.
8. Viết lại `backend/tests/test_suggestions.py`.

## Success Criteria

- [x] `suggestions.py` không còn chuỗi gợi ý literal nào (grep các câu hiện tại: `"Lọc`, `"Khách sạn nào`, `"Tóm tắt chi phí` → 0 kết quả).
- [x] Fake LLM trả tiện ích ngoài danh sách → test khẳng định prompt có ràng buộc và output vẫn được dedupe/cắt đúng.
- [x] Fake LLM ném exception → trả `[]`, có `logger.warning`, không raise.
- [x] Fake LLM trả `[]` → trả `[]` + warning (hiện tại: fallback im lặng).
- [x] Gợi ý có tiền tố `"1. "` bị bóc; trùng lặp khác hoa/thường bị loại.
- [x] `context.language == "en"` → prompt yêu cầu output tiếng Anh (test khẳng định prompt, không khẳng định output của LLM thật).
- [ ] `terminal_chat.py` chạy được với API mới (smoke bằng tay hoặc test import). **Blocked**: file có lỗi import `process_chat_turn` có sẵn từ trước plan này (`git show HEAD` xác nhận), nên module không import được để test/smoke. `_cli_suggestion_context` đúng API mới ở mức code, nhưng chưa chạy được thật.

## Risk Assessment

- **Sửa `get_llm` chạm mọi call site.** Giảm thiểu: chỉ thêm kwarg optional,
  mặc định `None` ⇒ hành vi hiện tại không đổi; chạy `impact()` trước.
- **`with_structured_output` với model local Ollama có thể không hỗ trợ tốt.**
  Hệ quả sau quyết định bỏ fallback: dev chạy Ollama có thể **không thấy chip
  nào**. Giảm thiểu: ghi rõ trong docstring; `logger.warning` cho biết lý do
  nên không ai phải đoán.
- **Prompt dài làm tăng chi phí.** Giảm thiểu: cắt còn 5 card, reply cắt 800
  ký tự như hiện tại.
