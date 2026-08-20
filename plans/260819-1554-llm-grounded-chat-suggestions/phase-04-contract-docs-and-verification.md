---
phase: 4
title: "Contract docs and verification"
status: done
priority: P2
effort: "0.5d"
dependencies: [1, 2, 3]
---

# Phase 4: Contract docs and verification

## Overview

Cập nhật hợp đồng API cho event `suggestions` mới và chạy trọn bộ kiểm chứng
end-to-end.

## Requirements

- `docs/chat_api_contract.md` mô tả đúng event mới, thứ tự frame, và việc
  `POST /planner_chat` trả `suggestions: []`.
- Bỏ các tham chiếu tới `suggestions_for()` — hàm này không còn tồn tại trong
  code (doc đang nhắc ở dòng 132, 472, 556).
- Toàn bộ test backend + frontend xanh.

## Related Code Files

- Modify: `docs/chat_api_contract.md`
  - §Streaming (quanh dòng 173-189): thêm ví dụ frame `event: suggestions` sau
    `event: final`, ghi rõ đây là frame phi-terminal duy nhất được phép đứng
    sau terminal frame, và client cũ bỏ qua nó là hợp lệ.
  - Dòng 130-132: `suggestions` không còn do `suggestions_for()` dựng; mô tả
    lại nguồn gốc (LLM có grounding, gate theo worker của turn).
  - Dòng 470-476 (`hotel_options[].index` ↔ `suggestions[].value`): kiểm tra
    lại — mô tả "một chip mỗi option" không còn đúng với cơ chế mới; sửa hoặc
    xoá theo hành vi thật.
  - Dòng ~667: ví dụ payload `"suggestions": []` cho POST — ghi chú đây là
    hành vi cố định, không phải thiếu sót.
  - Ghi rõ phạm vi của quyết định #7: **mọi** endpoint không stream trả
    `suggestions: []`, gồm `POST /planner_chat`, `POST /hotels/select`
    (`change_hotel` dùng chung `_response_from_result`) và `restore`. Chip chỉ
    tồn tại trên đường SSE.
- Modify/Create: test theo Phase 1-3.

## Implementation Steps

1. Đọc lại `docs/chat_api_contract.md` các mục nêu trên trước khi sửa.
2. Cập nhật §Streaming + các tham chiếu `suggestions_for()`.
3. Chạy `pytest backend/tests -q`.
4. Chạy test frontend (`npm test` trong `frontend/`).
5. Smoke bằng tay: một turn tìm khách sạn và một turn sửa lịch trình — xác
   nhận chip tới sau reply và mọi chip đều bấm được ra kết quả thật.
6. Chạy `detect_changes({scope: "compare", base_ref: "main"})` trước khi commit
   theo CLAUDE.md.

## Success Criteria

- [x] `grep -n "suggestions_for" docs/chat_api_contract.md` không còn kết quả.
- [x] Doc có ví dụ frame `suggestions` và nêu rõ thứ tự so với `final`.
- [x] `pytest backend/tests` xanh — trừ 13 test thất bại có sẵn từ trước, không liên quan (verify bằng `git stash`), xem plan.md.
- [x] Test frontend xanh — trừ 1 test thất bại có sẵn từ trước (`merge-active-session.test.ts`).
- [ ] Smoke: bấm từng chip của một turn hotel → không chip nào bị scope_guard
      chặn hoặc trả 0 kết quả. **Chưa chạy** — cần LLM thật + backend/frontend
      chạy sống, ngoài phạm vi phiên làm việc này.

## Risk Assessment

- **Doc trôi tiếp nếu chỉ sửa §Streaming.** Giảm thiểu: sửa cả 4 vị trí đã
  liệt kê, kiểm bằng `grep`.
- **Smoke thủ công phụ thuộc LLM thật** → kết quả có thể khác giữa các lần
  chạy. Chốt tiêu chí ở mức "chip thực thi được", không phải "chip giống hệt
  lần trước".
