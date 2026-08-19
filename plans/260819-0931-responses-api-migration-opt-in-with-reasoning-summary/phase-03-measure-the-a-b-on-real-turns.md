---
phase: 3
title: "Smoke test qua graph thật"
status: completed
priority: P2
effort: "0.5h"
dependencies: [2.5]
---

# Phase 3: Smoke test qua graph thật

## Overview

Một câu hỏi nhị phân: bật cờ rồi chạy lượt thật qua LangGraph, có vỡ gì không.
6 lượt, không phải 36.

> **Thu nhỏ 2026-08-19.** Bản đầu của phase này là A/B đo latency, số hop, và chi phí
> trên 36 lượt. Phần đo đó đã tách sang [Phase 3b](./phase-03b-deferred-cost-and-hop-ab.md)
> và bị hoãn, vì nó phục vụ hai quyết định người dùng đã hoãn: đổi default và dùng
> `previous_response_id`. Cái còn lại ở đây là câu hỏi thật sự chặn Phase 4.
>
> Bản đầu cũng chọn nhầm node: nó lo `extract_patch` vì `with_structured_output`
> (`extract_patch` không dùng cái đó — nó `json.loads` thủ công) và **bỏ sót**
> `supervisor`, chỗ duy nhất thật sự dùng. Đo live 2026-08-19: `supervisor` chạy tốt,
> `extract_patch` mới là chỗ vỡ. Phase 2.5 đã sửa nó; phase này xác nhận trên graph.

## Requirements

**Functional**
- Chạy 3 lượt đại diện với cờ **bật**, và 3 lượt y hệt với cờ **tắt**:
  - một lượt intake (chưa đủ slot) → `intake_qa`, streaming
  - một lượt Q&A trên plan đã lưu → `qa_node`, ReAct + tool
  - một lượt sửa lịch trình → `extract_patch` + `trip_edit_planner`
- Mỗi lượt kiểm ba thứ: không exception, `patch`/`intent` đúng như cấu hình tắt, và
  `delta` có tới.
- Xác nhận `usage_metadata` tới `usage_recorder` cho mọi call trong lượt bật cờ.

**Non-functional**
- Chạy đồng bộ trong thread của script. `usage_recorder` docstring cảnh báo call qua
  `ThreadPoolExecutor.submit` / `run_in_executor` là **vô hình** — và đường streaming
  của `routes.py` dùng đúng `run_in_executor`. Đo qua HTTP endpoint sẽ cho số 0 im lặng.
- **Không đo latency ở đây.** Một lần chạy không kết luận được gì về latency, và
  Phase 3b mới là chỗ cho câu hỏi đó.
- So sánh là so **kết quả**, không so số. Cùng một prompt, cùng một `intent`, cùng một
  hình dạng `patch` — đó là điều kiện đỗ.

## Architecture

Không có thành phần mới. Script dùng lại `routes._run_turn_via_graph` như
`eval/harness/e2e_eval.py` đang làm, với `record_usage()` bao ngoài.

```
cho mỗi cấu hình in {off, on}:
    cho mỗi lượt in {intake, qa, edit}:
        with record_usage(scope=f"smoke:{cấu hình}"):
            chạy lượt, đồng bộ
        ghi: exception?, intent, len(patch), có delta?, usage có đủ?
so sánh cột off với cột on
```

## Related Code Files

- Create: `backend/scripts/smoke_responses_api.py`
- Create: `plans/reports/smoke-260819-responses-api-graph.md`
- Read-only: `backend/src/api/routes.py`, `eval/harness/usage_recorder.py`

## Implementation Steps

1. Viết script, 3 lượt × 2 cấu hình.
2. Chạy, ghi bảng so sánh.
3. Nếu có ô lệch giữa off và on → **dừng**, đó là bug Phase 2.5 bỏ sót, không phải
   caveat để ghi chú.
4. Viết báo cáo ngắn, gồm mục "cái gì không được đo".

## Success Criteria

- [x] 6 lượt chạy xong, không exception ở cấu hình bật cờ
- [x] `intent` và hình dạng `patch` khớp nhau giữa hai cấu hình
- [x] `delta` tới ở cả hai cấu hình cho lượt intake và qa
- [x] `usage_metadata` đầy đủ — 8/8 call, kèm `model`
- [x] Báo cáo nêu rõ giới hạn phép đo

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Đo qua `run_in_executor` → số 0 im lặng | Cao | Chạy đồng bộ; ghi ràng buộc này vào docstring script |
| Lượt edit cần state có sẵn (plan đã lưu) | Trung bình | Dựng state bằng `apply_patch` như `test_stream_modes.py` đang làm, không cần DB |
| 6 lượt chưa đủ bao phủ | Trung bình | Đúng vậy, và đó là đánh đổi có chủ ý. Ghi vào mục giới hạn |

## Kết quả

**PASS**, 6/6 lượt. Báo cáo: `plans/reports/smoke-260819-responses-api-graph.md`.

Phát hiện ngoài phạm vi, ảnh hưởng Phase 5: lượt `qa` chỉ phát **2 frame delta** cho
~600-700 ký tự, tức `qa_node` không stream theo token (lượt `intake` phát 41 frame cho
154 ký tự — đó mới là streaming thật). Giống nhau ở cả hai transport nên không phải hồi
quy của plan này, nhưng khối thinking của Phase 5 dựa vào luồng delta đó.
