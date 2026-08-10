---
title: "Phase 7: FE Stage Intake & Generating"
date: 2026-08-06
summary: "Dựng 2 stage intake + generating theo design Claude; checklist 5 dòng dữ liệu thật; generating trung thực (giây thật + skeleton + bar vô hạn), không danh sách tick giả"
---

# Phase 7: FE Stage Intake & Generating

## What happened

Implement Phase 7 (FE) của plan 260805-1022-claude-design-ui-integration: hai stage view đầu
tiên của shell — intake (hero + checklist "THÔNG TIN AI ĐANG THU THẬP") và generating.

Files tạo: `stage-intake.tsx`, `stage-generating.tsx`, `intake-checklist.tsx`, `skeleton-card.tsx`,
`lib/intake-checklist-rows.ts` (+9 unit test). Sửa: `stage-router.tsx` (nối stage thật),
`styles.css` (@utility `shimmer-block` + `@keyframes indeterminate-segment`), i18n en/vi
(+19 key, xoá 3 key placeholder cũ), `mock/server.js` chấp nhận MOCK_PORT.

Gates: typecheck / oxlint / check:tokens / 52 vitest — tất cả pass. Nghiệm thu bằng ảnh trên
cả mock (turn 1-3 scripted) lẫn backend thật docker :5173.

Code review subagent: approve-with-notes, 9/9 tiêu chí pass; 4 minor đã sửa (M1 trùng chuỗi
"30–60 giây" giữa title và sub; M2 nbsp literal → '\\u00A0'; M3 value gate theo collected;
M4 plural en `generatingElapsed_one/_other`).

## Decisions

1. Dòng Ngân sách trong checklist hiển thị "—" thường trực: contract đóng băng không có
   field chosen-tier (min_price/max_price chỉ tồn tại ở schemas.py, chưa khai báo phía FE).
   Hiển thị nhãn mức = bịa dữ liệu. User đã chọn phương án này qua question gate.
2. Giữ `trip-parameters-card.tsx`: khác bề mặt và mục đích với intake-checklist, không trùng
   chức năng (user quyết).
3. Không port danh sách 6 bước tick của design (genSteps) — backend chỉ có pending + elapsed;
   giữ nguyên quyết định plan.md mục 14.
4. Bỏ edit affordance từng dòng của design vì stage không có send path — link "Sửa" sẽ là
   hứa suông.
5. Hero gradient dùng token alias thay hex hardcode để dark theme override được.

## Next steps

- Phase 8 [FE] Stage: Hotels & Hotel Focus — skeleton-card variant 'hotel' đã sẵn sàng tái dùng.
- Nếu muốn dòng Ngân sách có giá trị thật: cần mở contract (types.ts + mock + contract doc
  + thỏa thuận 2 dev) khai báo chosen budget tier.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
