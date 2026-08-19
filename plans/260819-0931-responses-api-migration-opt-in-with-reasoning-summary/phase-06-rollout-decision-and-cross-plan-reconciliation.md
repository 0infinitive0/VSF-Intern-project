---
phase: 6
title: "Quyết định rollout + hoà giải cross-plan"
status: pending
priority: P2
effort: "0.5d"
dependencies: [3, 5]
---

# Phase 6: Quyết định rollout + hoà giải cross-plan

## Overview

Ra quyết định về default dựa trên số đo Phase 3, và sửa các tài liệu đang mâu thuẫn với
nhau sau khi quyết định 2026-08-18 bị đảo ngược. Không sửa code sản phẩm ở phase này.

## Requirements

**Functional**
- Quyết định tường minh về `LLM_USE_RESPONSES_API`: giữ default `false`, hay đổi sang
  `true`. Kèm lý do bằng số từ Phase 3.
- Sửa `260818-0924-deepdive-thinking-loader/plan.md:62` — dòng khai "Không đụng
  Responses API" là non-goal giờ đã sai.
- Sửa deepdive `phase-03` và `phase-04` để tính đến làn reasoning (field `reasoning`
  trên `ThinkingGroup`, và quan hệ của nó với luật "thiếu dữ kiện thì không hiện dòng").
- Thêm ghi chú vào `plans/reports/spike-260818-reasoning-summary.md` §6: quyết định #1
  ("không dùng reasoning summary") đã bị đảo ngày 2026-08-19, kèm lý do và link plan này.
- Ghi quyết định vào `docs/` theo quy ước sẵn có của repo (đọc `docs/` trước để tìm chỗ
  đúng — không tạo cây thư mục mới).

**Non-functional**
- Sửa spike report bằng cách **thêm ghi chú có ngày**, không viết đè kết luận cũ. File
  đó đã có tiền lệ đúng: khối "ĐÍNH CHÍNH 2026-08-18" giữ nguyên kết luận sai rồi nói rõ
  vì sao sai. Giữ dấu vết quyết định là điểm mạnh của tài liệu này.
- Không để hai plan cùng khai một quyết định trái ngược nhau sau khi phase này xong.

## Architecture

Không có. Đây là phase tài liệu + quyết định.

## Related Code Files

- Modify: `plans/260818-0924-deepdive-thinking-loader/plan.md`
- Modify: `plans/260818-0924-deepdive-thinking-loader/phase-03-frontend-thinking-state-and-fact-rendering.md`
- Modify: `plans/260818-0924-deepdive-thinking-loader/phase-04-thinkingblock-ui-in-chat.md`
- Modify: `plans/reports/spike-260818-reasoning-summary.md`
- Modify: `backend/.env.example` (nếu đổi default)
- Modify: `docs/` (vị trí chốt sau khi đọc cấu trúc docs hiện có)

## Implementation Steps

1. Đọc báo cáo Phase 3. Nếu chi phí mỗi lượt tăng mà số hop không giảm → giữ default
   `false` và nói thẳng rằng migration chỉ còn giá trị future-proof.
2. Quyết định default. Nếu đổi sang `true`, phải kèm: kế hoạch rollback (đổi env), và
   xác nhận `gpt-4o-mini` guard vẫn giữ eval an toàn.
3. Sửa deepdive `plan.md` non-goal + bảng file ownership (thêm `stream-client.ts`,
   `use-chat-session.ts` giờ có hai plan cùng chạm).
4. Sửa deepdive `phase-03`: thêm field `reasoning` vào `ThinkingGroup`, và một câu nói
   rõ reasoning **không** được dùng để thoả mãn luật "thiếu dữ kiện thì không hiện dòng".
5. Sửa deepdive `phase-04`: làn render reasoning trong `ThinkingBlock`.
6. Thêm ghi chú có ngày vào spike report §6.
7. Cập nhật `blockedBy`/`blocks` hai chiều giữa hai plan bằng CLI hoặc sửa tay
   frontmatter, rồi `ak plan reindex` nếu sửa tay.
8. Chạy whole-plan consistency sweep: đọc lại toàn bộ `plan.md` + 6 phase file của plan
   này, tìm thuật ngữ cũ, giả định đã bị bác, và mâu thuẫn còn sót.
9. Trả lời open question #3 của `plan.md` (staging trước hay % traffic) — cần người dùng.

## Success Criteria

- [ ] Quyết định default có lý do bằng số, không bằng cảm tính
- [ ] Deepdive plan không còn khai "Không đụng Responses API"
- [ ] Deepdive Phase 3/4 tính đến làn reasoning
- [ ] Spike report có ghi chú đảo quyết định, kết luận cũ giữ nguyên
- [ ] `blockedBy`/`blocks` đúng hai chiều giữa hai plan
- [ ] Consistency sweep báo 0 mâu thuẫn còn lại
- [ ] Không file code sản phẩm nào bị sửa ở phase này (trừ `.env.example` nếu đổi default)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sửa deepdive plan trong khi ai đó đang implement nó | Trung bình | Deepdive đang `pending`, chưa ai bắt đầu. Kiểm tra lại status trước khi sửa |
| Đổi default dựa trên số đo mỏng (3 lần chạy) | Trung bình | Nếu số liệu không dứt khoát, giữ `false`. Không quyết định lớn trên dữ liệu yếu |
| Mất dấu vết vì sao quyết định bị đảo | Trung bình | Bước 6 bắt buộc thêm ghi chú có ngày, không viết đè |
