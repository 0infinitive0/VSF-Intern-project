---
phase: 3.5
title: "A/B chi phí và số hop (HOÃN)"
status: deferred
priority: P3
effort: "1d"
dependencies: [3]
---

# Phase 3b: A/B chi phí và số hop — HOÃN

## Overview

Đo latency, số hop ReAct, và chi phí mỗi lượt giữa hai đường API, trên 36 lượt qua
graph thật.

> **KHÔNG BẮT ĐẦU** cho tới khi có người thật sự đề xuất một trong hai:
> đổi `LLM_USE_RESPONSES_API` default sang `true`, hoặc dùng server-side state
> (`previous_response_id` / `store=true`).
>
> Cả hai đều đang là non-goal của plan (xem `plan.md` § Non-Goals, chốt với người dùng
> 2026-08-19). Đo bây giờ là mua số liệu cho một quyết định không ai sắp ra.

## Vì sao hoãn chứ không xoá

Có đúng một giả thuyết chưa ai đo, và nó vẫn còn giá trị nếu bài toán chi phí quay lại:
trong vòng ReAct của `qa_node`, Chat Completions **vứt bỏ reasoning giữa các hop** —
model phải suy luận lại sau mỗi tool call. Responses API giữ được reasoning item.

Nếu điều đó làm giảm số hop, nó giảm cả chi phí lẫn độ trễ. Nếu không, thì migration
chỉ còn giá trị future-proof, và câu đó nên được nói bằng số.

## Điều kiện kích hoạt

Một trong:
- Chi phí LLM mỗi lượt trở thành vấn đề được nêu ra.
- Có đề xuất đổi default sang Responses API.
- Có đề xuất dùng `previous_response_id`.

## Thiết kế (giữ nguyên từ bản đầu)

- 3 nhóm node × 2 prompt (một dễ một khó) × 2 cấu hình × 3 lần chạy = 36 lượt.
- Prompt khó **bắt buộc** phải thật sự cần suy luận. Spike §2 chứng minh prompt lịch
  trình thường không kích hoạt reasoning trên `gpt-5.1`; một tập prompt toàn loại dễ
  sẽ kết luận sai lần thứ hai.
- ≥3 lần chạy mỗi ô. Spike §7 ghi nhận cùng một cấu hình lệch 14.9s vs 23.0s.
- Quy giá bằng `eval/harness/cost.py`; lưu raw records trước khi gộp.
- Trả lời: số hop `qa_node` có giảm không, chi phí mỗi lượt đổi bao nhiêu %.

## Success Criteria

- [ ] Điều kiện kích hoạt đã xảy ra và được ghi lại
- [ ] Báo cáo có số cho cả hai cấu hình, ≥3 lần chạy mỗi ô
- [ ] Trả lời được: số hop có giảm không, chi phí đổi bao nhiêu
- [ ] Mục "Giới hạn của phép đo" nêu rõ cái gì không đo
