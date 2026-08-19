---
phase: 6
title: "Quyết định rollout + hoà giải cross-plan"
status: completed
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

- [x] Quyết định default có lý do — giữ `false`, xem mục Quyết định
- [x] Deepdive plan không còn khai "Không đụng Responses API"
- [x] Deepdive Phase 3/4 tính đến làn reasoning
- [x] Spike report có ghi chú đảo quyết định, kết luận cũ giữ nguyên
- [x] `blockedBy`/`blocks` đúng hai chiều giữa hai plan
- [x] Consistency sweep báo 0 mâu thuẫn còn lại
- [x] Không file code sản phẩm nào bị sửa ở phase này

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Sửa deepdive plan trong khi ai đó đang implement nó | Trung bình | Deepdive đang `pending`, chưa ai bắt đầu. Kiểm tra lại status trước khi sửa |
| Đổi default dựa trên số đo mỏng (3 lần chạy) | Trung bình | Nếu số liệu không dứt khoát, giữ `false`. Không quyết định lớn trên dữ liệu yếu |
| Mất dấu vết vì sao quyết định bị đảo | Trung bình | Bước 6 bắt buộc thêm ghi chú có ngày, không viết đè |

## Quyết định: giữ default `false`

**`LLM_USE_RESPONSES_API` và `LLM_REASONING_SUMMARY` đều giữ mặc định tắt.**

Lý do, theo thứ tự sức nặng:

1. **Không có số nào ủng hộ việc đổi.** Phase 3 rút xuống smoke test — nó trả lời "có vỡ
   không" (không), chứ không đo latency, chi phí, hay số hop. Phép đo đó nằm ở Phase 3b,
   đang hoãn vì nó phục vụ hai quyết định là non-goal. Đổi default dựa trên "không thấy
   vỡ" là đổi mà không có lý do.
2. **Lợi ích lớn nhất đã bị vô hiệu.** Spike đo TTFT giảm 17.6s → 1.0s, nhưng đó là do
   token summary lấp chỗ trống. Dự án lấp chỗ đó bằng dữ kiện graph (deepdive plan), nên
   phần lớn lợi ích không còn thu được.
3. **Prompt caching đã có trên cả hai đường.** `eval/pricing/model-prices.json` có
   `cached_input` (gpt-5.1: 1.25 → 0.125). Lý do chi phí không đứng vững.
4. **Cái còn lại là future-proof**, và nó **không cần** default đổi: guard
   `_streamed_text`/`response_text` (Phase 1 + 2.5) đã đóng đường vỡ, kể cả khi ai đó đặt
   `LLM_MODEL=gpt-5-pro` và langchain tự chuyển transport.

Giá trị thật sự thu được từ plan này không phải việc migrate, mà là **9 chỗ giả định
`.content` luôn là `str` đã được vá**, và đường Responses API giờ bật được an toàn khi
cần — bằng một biến env, không phải một đợt deploy.

### Bật khi nào

Khi Phase 5 dựng làn reasoning trong khối thinking. Lúc đó môi trường chạy Phase 5 cần
`LLM_USE_RESPONSES_API=true` + `LLM_REASONING_SUMMARY=auto`. Đó là quyết định phạm vi
môi trường, không phải đổi default sản phẩm.

## Docs đã cập nhật

- `docs/chat_api_contract.md` — event `reasoning` + 4 thuộc tính bắt buộc (Phase 4).
- `docs/setup/SETUP_GUIDE.md` — một dòng chỉ đường; chi tiết từng biến ở `.env.example`,
  đúng quy ước file đó đang trỏ tới. Không nhân bản.
- Không tạo cây `docs/decisions/` mới — repo không có quy ước ADR, và tạo một cây thư mục
  cho một quyết định là dựng cấu trúc trước khi có nhu cầu.

## Consistency sweep

Đọc lại `plan.md` + 8 phase file. Đã sửa trong lượt này:

- Bảng phase trong `plan.md` thiếu Phase 2.5 và 3b → đã thêm.
- Non-goal của plan nói "phép đo chi phí phục vụ Phase 3" → sửa thành trỏ Phase 3b.
- Phase 3 vẫn mang tiêu đề "A/B" trong tên file (`phase-03-measure-the-a-b-on-real-turns.md`)
  dù nội dung đã thành smoke test. **Không đổi tên file** — link từ `plan.md` và các
  report đang trỏ vào đó; đổi tên tạo link chết để đổi lấy một cái tên đẹp hơn.
- Open question #1, #2 đã đóng bằng số đo; #3 vẫn mở; #4 (bug `qa_node`) mới thêm.
