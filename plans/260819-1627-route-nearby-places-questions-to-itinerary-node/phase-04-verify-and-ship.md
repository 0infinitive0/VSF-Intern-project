---
phase: 4
title: "Verify against real trace + ship"
status: pending
priority: P1
effort: "1-2h"
dependencies: [1, 2, 3]
---

# Phase 4: Verify against real trace + ship

## Overview

Xác nhận fix hoạt động với đúng kịch bản đã gây bug (không chỉ unit test
mock), chạy `detect_changes()` theo yêu cầu CLAUDE.md, rồi bàn giao.

## Requirements

- `detect_changes({scope: "compare", base_ref: "main"})` chỉ báo thay đổi
  nằm trong phạm vi dự kiến — không symbol nào ngoài ý muốn bị ảnh hưởng.
- Test suite liên quan graph/routing xanh, không chỉ file vừa sửa.
- Bằng chứng chạy thật (không chỉ mock) rằng câu hỏi gốc cho ra
  `suggested_places` non-empty.

## Related Code Files

- Không sửa file ở phase này.

## Implementation Steps

1. `detect_changes({scope: "compare", base_ref: "main"})` qua GitNexus MCP.
   Phạm vi dự kiến: `prompts.py`, `extract_patch.py`, `state.py`,
   `load_context.py`, `supervisor.py`, `test_extract_patch.py`,
   `test_supervisor_routing.py`. Bất kỳ symbol/flow nào ngoài danh sách này →
   dừng, báo cáo user trước khi đi tiếp.
2. Chạy test rộng hơn file vừa sửa — `extract_patch` và `supervisor` là node
   dùng chung, nên quét các file test có chạm tới graph routing:
   ```
   pytest backend/tests/test_extract_patch.py \
          backend/tests/test_supervisor_routing.py \
          backend/tests/test_supervisor_llm_budget.py \
          backend/tests/test_routing.py \
          backend/tests/test_graph_v2_skeleton.py \
          backend/tests/test_respond.py \
          backend/tests/test_reply_contract.py -q
   ```
   Nếu thời gian cho phép, chạy nguyên `pytest backend/tests -q`.
3. **Lưu ý coverage gap đã biết:** `grep -rl "list_nearby" backend/tests/`
   trả về **rỗng** — nhánh `list_nearby` của `itinerary_node` chưa từng có
   test nào, kể cả trước fix này. Plan này không mở rộng scope để lấp gap đó
   (nó nằm trong `itinerary_node`, không phải đường routing đang sửa), nhưng
   phải nêu rõ khi bàn giao: verify bước 4 là bằng chứng duy nhất cho nhánh
   đó thật sự chạy đúng.
4. Verify bằng tay: dựng lại chuỗi turn như trace lỗi gốc (`terminal_chat.py`
   cục bộ hoặc gọi API dev): chọn khách sạn → gõ "liệt kê các địa điểm nổi bật
   trong vòng bán kính 3km". Kiểm tra:
   - response JSON có `suggested_places` non-empty;
   - LangSmith trace của turn đó có `next_worker="itinerary_node"` và
     `routing_source="read_only_intent_nearby"` (tên đã chốt ở Phase 2);
   - `asks_nearby_places=true` trong output của `extract_patch` — xác nhận
     model thật sự set field mới, không chỉ code đọc được nó.
5. Kiểm tra thêm một câu read-only KHÔNG phải nearby ở cùng session (ví dụ
   "phòng nào rẻ hơn?") → vẫn `qa_node`, `asks_nearby_places=false`. Đây là
   nửa còn lại của bằng chứng: fix không kéo mọi câu hỏi sang itinerary_node.
6. Báo cáo tóm tắt: root cause, fix, coverage, kết quả verify thật, và gap ở
   bước 3.

## Success Criteria

- [ ] `detect_changes()` không báo gì ngoài 7 file dự kiến ở bước 1.
- [ ] Test suite ở bước 2 xanh.
- [ ] Bước 4 xác nhận `suggested_places` non-empty + `asks_nearby_places=true`
      trên turn thật.
- [ ] Bước 5 xác nhận câu read-only thường vẫn về `qa_node`.
- [ ] Gap coverage `list_nearby` được nêu rõ trong báo cáo bàn giao.

## Risk Assessment

Thấp — không sửa code. Rủi ro là verify bằng tay cần môi trường dev chạy được
(Supabase, LLM key). Nếu không sẵn sàng: hạ xuống đọc LangSmith trace của lần
chạy thử gần nhất thay vì tự chạy mới, và **ghi rõ giới hạn đó** trong báo cáo
— không được báo "đã verify" khi mới chỉ chạy unit test.
