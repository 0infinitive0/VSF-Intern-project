---
phase: 1
title: "Spike: đo reasoning summary thật"
status: completed
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Spike — đo reasoning summary thật

> **ĐÃ CHẠY XONG 2026-08-18.** Kết quả:
> [`../reports/spike-260818-reasoning-summary.md`](../reports/spike-260818-reasoning-summary.md).
>
> **Kết luận: no-go cho hướng reasoning summary.** Không phải vì nó hỏng — nó chạy được trên
> cả hai model — mà vì **độ phủ phụ thuộc độ khó câu hỏi và không dự đoán trước được**:
> `gpt-5.1` không suy luận trên prompt lập lịch trình thường (TTFT 2.8s) nên không có gì để
> tóm tắt, nhưng phát 59 block trên prompt xác suất. Bước gọi tool thì luôn rỗng. Cộng thêm
> ngôn ngữ là tiếng Anh không ép được bằng prompt.
>
> Dự án chuyển sang **tường thuật từ dữ kiện thật của graph** (Phase 2-5). Nội dung gốc của
> phase này giữ nguyên bên dưới làm hồ sơ quyết định.

## Overview

Phase duy nhất **không sửa code sản phẩm**. Trả lời bằng số đo cho 4 câu hỏi mà cả plan
đang giả định là "có": summary có ra chữ không, ra ngôn ngữ gì, tốn thêm bao nhiêu thời
gian, và Responses API có phá tool-call của ReAct agent không.

Đây là gate. Sai giả định ở đây thì 6 phase sau vô nghĩa.

## Requirements

**Functional**
- Đo trên **cả hai** model đang chạy thật: `gpt-5.1-2025-11-13` (`LLM_MODEL`, dùng bởi
  `get_reasoning_llm`/`get_llm`) và `gpt-5-mini-2025-08-07` (`LLM_FAST_MODEL`, dùng bởi
  `get_fast_llm` ở `qa_node`/`intake_qa`/`supervisor`).
- Đo ở cả 3 mức effort: `low`, `medium`, `high`.
- Đo với **prompt tiếng Việt thật** lấy từ `backend/src/agents/graph/prompts.py`, không
  phải câu test tiếng Anh — ngôn ngữ input ảnh hưởng ngôn ngữ summary.
- Xác minh hình dạng `content` khi streaming qua Responses API: `str` hay list block.
- Xác minh ReAct agent trong `qa_node` còn gọi được tool khi model bật Responses API.

**Non-functional**
- Script spike đặt trong `backend/scripts/`, không import vào đường chạy sản phẩm.
- Không commit API key; đọc từ `backend/.env` như mọi entry point khác.
- Không sửa `llm.py`, `config.py`, hay bất kỳ node nào ở phase này.

## Architecture

Spike đứng ngoài graph. Khởi tạo `ChatOpenAI` trực tiếp với `reasoning={...}` rồi
`.stream()`, đọc `chunk.content_blocks` lọc `type == "reasoning"` (API LangChain xác nhận
qua Context7: `langchain-ai/docs` → `models.mdx`, `integrations/chat/openai.mdx`).

Riêng câu hỏi tool-call phải chạy qua graph thật — dựng một `qa_node` với model bật
reasoning và gọi một câu chắc chắn kích hoạt tool (ví dụ hỏi về khách sạn), rồi xem tool
có được gọi không.

## Related Code Files

- Create: `backend/scripts/spike_reasoning_summary.py`
- Create: `plans/reports/spike-260818-reasoning-summary.md`
- Read only: `backend/src/services/llm.py`, `backend/src/agents/graph/nodes/qa_node.py`,
  `backend/src/agents/graph/prompts.py`, `backend/.env`

## Implementation Steps

1. Viết `spike_reasoning_summary.py`: nhận `--model`, `--effort`, `--prompt-file`, in ra
   số block reasoning, tổng ký tự, ngôn ngữ phát hiện được, thời gian tới token đầu và
   tổng thời gian.
2. Chạy ma trận 2 model × 3 effort với một prompt tiếng Việt lấy từ `prompts.py`. Ghi bảng số.
3. Chạy lại cùng ma trận **không** bật reasoning để có đường cơ sở latency so sánh.
4. In thẳng `type(chunk.content)` và `repr` của một chunk để chốt hình dạng `content`.
   Đối chiếu với guard `isinstance(content, str)` ở `routes.py:548`.
5. Thử ép tiếng Việt: thêm chỉ dẫn "suy luận bằng tiếng Việt" vào system prompt, chạy lại,
   xem summary có đổi ngôn ngữ không. Ghi kết quả trung thực kể cả khi thất bại.
6. Dựng `qa_node` với model bật reasoning, gọi câu kích hoạt tool. Ghi rõ tool có chạy không,
   lỗi gì nếu có.
7. Viết báo cáo `spike-260818-reasoning-summary.md`: bảng số + khuyến nghị effort + kết luận
   ngôn ngữ + go/no-go.

## Success Criteria

- [x] Bảng số: 2 model × 3 effort × (có/không reasoning) — số block, ký tự, latency
- [x] Kết luận rõ ràng: mức effort nào cho summary dùng được
- [x] Kết luận ngôn ngữ: summary ra tiếng gì, prompt có ép được không
- [x] Kết luận hình dạng `content`: `str` hay list block, guard `routes.py:548` có vỡ không
- [x] Kết luận tool-call: ReAct trong `qa_node` còn hoạt động không
- [x] Delta latency so với đường cơ sở, tính bằng giây
- [x] Go/no-go tường minh cho Phase 2

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Reasoning summary cần org verification, API trả 403 | Ghi nguyên lỗi vào báo cáo → no-go, báo người dùng đi xác minh tổ chức trên OpenAI |
| Spike tốn token thật | Prompt ngắn, chạy 1 lần mỗi ô, không lặp |
| Kết quả khác nhau giữa các lần chạy | Chạy mỗi ô 2 lần, ghi cả hai, không lấy trung bình từ 1 mẫu |

**Gate:** nếu summary rỗng ở mọi effort, hoặc tool-call vỡ không vá được → **dừng plan**,
báo người dùng kèm số đo. Không đi tiếp bằng giả định.
