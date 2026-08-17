---
phase: 3
title: "Doc reconciliation"
status: completed
priority: P2
effort: "0.5d"
dependencies: [1, 2]
---

# Phase 3: Doc reconciliation

## Overview

`ARCHITECTURE.md` mô tả một node không tồn tại và bỏ sót cấu trúc thật của graph.
Phase này làm doc khớp code, và ghi thành văn nguyên tắc thiết kế mà Phase 1 vừa cưỡng
chế và Phase 6 sắp dựa vào: **số liệu → template; giọng văn → LLM.**

Chạy sau Phase 1 và 2 vì cả hai đều đổi thứ doc phải mô tả.

## Requirements

**Functional**

- `ARCHITECTURE.md` liệt kê đúng 14 node của graph, không phải 4 node tưởng tượng.
- Vai trò `respond` mô tả đúng: response assembler, không phải NLG node.
- Nguyên tắc "số liệu → template; giọng văn → LLM" được ghi thành mục có thể trích dẫn.
- Contract `emits_reply` (Phase 1) được tài liệu hoá.

**Non-functional**

- Không viết lại toàn bộ doc. Chỉ sửa phần sai và bổ sung phần thiếu.
- Mermaid diagram phải render được.

## Architecture

### Doc sai chỗ nào

`ARCHITECTURE.md` vẽ:

```
subgraph Nodes[LangGraph Execution Nodes]
    IntakeNode[Intake & Clarification Node]
    RetrievalNode[Search & RAG Retrieval Node]
    SchedulerNode[Deterministic Trip Scheduler Node]
    RespondNode[Formatting & Polish Node]
end
```

Bốn node này **không tồn tại**. `NODE_NAMES` (`graph.py:58-73`) liệt kê 14 node thật:

```
load_context, scope_guard, extract_patch, validate_patch, apply_patch,
ask_slot, intake_qa, supervisor, hotel_node, itinerary_node, booking_node,
qa_node, budget_check, respond
```

`RespondNode[Formatting & Polish Node]` là chỗ sai nguy hiểm nhất: nó khiến người đọc
tin rằng có một lớp sinh ngôn ngữ. Thực tế `respond` (`respond.py:286`) chỉ lắp
`PlannerChatResponse` và **nhặt** reply theo thứ tự ưu tiên. Chính niềm tin sai đó là lý
do lỗ hổng ở Phase 1 tồn tại lâu mà không ai thấy: ai cũng nghĩ "có node lo phần trả lời".

### Doc thiếu chỗ nào

- Không mô tả patch pipeline (`extract_patch → validate_patch → apply_patch → ask_slot`)
  — cơ chế quan trọng nhất của kiến trúc, thứ xoá cả một class deadlock.
- Không mô tả supervisor delegation và `all_tasks_done` như edge thuần.
- Không mô tả contract enforcement ở biên node.
- Không mô tả `qa_node` cô lập bằng schema boundary.
- Không giải thích tại sao reply là template chứ không phải LLM.

### Nguyên tắc cần ghi thành văn

Nguyên tắc này đang **tồn tại thật trong code** nhưng chỉ nằm rải rác trong docstring:

| Nguồn | Trích |
|---|---|
| `budget_check.py` docstring | *"preserving the existing 'never invent missing prices' contract"* |
| `hotel_node.py::_binding_constraint_reply` | Đếm chính xác số khách sạn rớt theo từng tag |
| `trip_formatter.py::format_trip_response_from_json` | Render giá/giờ/ngày từ `trip_data` |

Ghi thành mục trong `ARCHITECTURE.md`:

> **Reply generation rule.** Reply chứa số liệu (giá, số lượng, ngày, giờ, tên thực thể)
> phải sinh bằng template xác định đọc thẳng từ state. LLM chỉ được dùng cho phần không
> mang số liệu: câu hỏi intake, câu trả lời Q&A, và (nếu bật) lớp diễn đạt lại
> rewrite-only. Không có ngoại lệ: một LLM viết lại con số là một LLM có thể bịa con số.

Mục này là thứ Phase 6 phải tuân thủ, và là lý do Phase 6 có eval gate.

## Related Code Files

- Modify: `ARCHITECTURE.md` — sửa mermaid, sửa mô tả node, thêm 2 mục mới
- Modify: `docs/chat_api_contract.md` — hoàn tất phần Phase 2 đã bắt đầu (nếu còn sót)
- Read-only nguồn sự thật:
  - `backend/src/agents/graph/graph.py` — `NODE_NAMES`, topology, edges
  - `backend/src/agents/graph/contracts.py` — `CONTRACTS`, `emits_reply`
  - `backend/src/agents/graph/nodes/respond.py` — thứ tự ưu tiên reply
  - `backend/src/agents/graph/routing.py` — `WORKER_ORDER`, `_IMPOSSIBLE`

## Implementation Steps

1. **Đọc `ARCHITECTURE.md` toàn bộ trước khi sửa.** Xác định phần nào còn đúng (frontend,
   data layer, Airflow) — không đụng vào.

2. **Thay subgraph `Nodes`** trong mermaid bằng topology thật. Giữ diagram đọc được, có
   thể gộp nhóm nhưng tên node phải là tên thật:
   ```
   subgraph Pipeline[Patch pipeline]
       LoadCtx[load_context] --> Scope[scope_guard] --> Extract[extract_patch]
       Extract --> Validate[validate_patch] --> Apply[apply_patch] --> AskSlot[ask_slot]
   end
   subgraph Workers[Supervisor + workers]
       Sup[supervisor] --> Hotel[hotel_node]
       Sup --> Itin[itinerary_node]
       Sup --> Booking[booking_node]
       Sup --> QA[qa_node subgraph]
   end
   Budget[budget_check] --> Respond[respond — response assembler]
   ```

3. **Xoá `RespondNode[Formatting & Polish Node]`.** Thay bằng mô tả đúng:
   *"`respond` — response assembler. Xây `PlannerChatResponse` từ state; nhặt reply theo
   thứ tự ưu tiên (intake_qa+ask_slot → task_results → messages → generic ack canary).
   Không sinh ngôn ngữ."*

4. **Thêm mục "Reply generation rule"** với nội dung ở phần Architecture trên.

5. **Thêm mục "Node contracts"**: `CONTRACTS` khai `reads`/`writes`/`tools`/`emits_reply`;
   `enforce_contract` cưỡng chế ở biên; `qa_node` cô lập bằng schema boundary chứ không
   bằng runtime check.

6. **Thêm mục "Patch pipeline"**: giải thích tại sao patch commit **trước** slot gate
   (một câu hỏi đang chờ không thể chặn một fact khác landing).

7. **Hoàn tất phần doc Phase 2 để lại**: kết quả khảo sát field mồ côi trên `TripSession`
   (bước 7 của Phase 2) ghi vào mục "Known debt".

8. **Verify mermaid render**: paste vào mermaid.live hoặc preview trong IDE. Diagram gãy
   còn tệ hơn diagram sai.

9. **Đối chiếu lần cuối**: mọi tên node trong doc phải khớp `NODE_NAMES` trong
   `graph.py:58-73`. Không tên nào thừa, không tên nào thiếu.

## Success Criteria

- [x] `ARCHITECTURE.md` không còn `RespondNode[Formatting & Polish Node]`
- [x] Mọi tên node trong doc khớp `NODE_NAMES` (`graph.py:58-73`)
- [x] Mermaid render được, không lỗi cú pháp
- [x] Mục "Reply generation rule" tồn tại và trích dẫn được
- [x] Mục "Node contracts" mô tả `emits_reply` từ Phase 1
- [x] Mục "Patch pipeline" giải thích thứ tự patch-trước-slot-gate
- [x] Known debt ghi: `/hotels/change` NL-string RPC, field mồ côi trên `TripSession`
- [x] `docs/chat_api_contract.md` khớp surface sau Phase 2

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Doc lại lạc hậu sau Phase 4/6 | Trung bình | Phase 4 và 6 đều có bước cập nhật doc trong success criteria của chính nó. Phase 3 dựng cấu trúc; các phase sau điền vào. |
| Diagram quá chi tiết thành khó đọc | Thấp | Gộp nhóm bằng subgraph, giữ tên thật. Ưu tiên đúng hơn đẹp. |
| Sửa nhầm phần doc còn đúng (frontend/data layer) | Thấp | Bước 1 đọc toàn bộ trước, khoanh vùng chỉ sửa phần Nodes + thêm mục mới. |
| "Reply generation rule" bị hiểu là cấm mọi LLM trong reply | Thấp | Câu chữ nói rõ: cấm LLM **chạm số liệu**, không cấm LLM ở câu hỏi intake/Q&A/rewrite. |

**Rollback:** `git revert`. Không có code thay đổi.

## Execution Log — 2026-08-15

Step 1 (read the whole doc first) found the drift was **wider than this phase
described**. The plan targeted the mermaid `Nodes` subgraph and
`RespondNode[Formatting & Polish Node]`; in fact three more sections described the
deleted control plane:

- **Section 3 "AI Agent"** documented `AgentState` and four nodes
  (`intake_node`, `retrieval_node`, `scheduler_node`, `respond_node`) plus
  "7-branch routing in `process_chat_turn` (`src/services/chat_session.py`)".
  None of it exists — `chat_session.py` is gone. Rewritten from `graph.py` as the
  ground truth: all 14 nodes with their real roles, plus the `respond`-is-an-assembler
  correction.
- **Section 3's own control-flow mermaid** drew the same four ghost nodes. Replaced
  with the real edges from `build_graph`.
- **Data Flow steps 3-6** described `process_chat_turn` routing through 7 branches and
  `derive_stage()` deriving stage from "which tool actually ran". Rewritten around
  `_run_turn_via_graph`, the patch pipeline, and stage-derived-from-state.

Also corrected while there: the endpoint list in Section 2 (said "Four endpoints",
listed pre-cutover ones), and two wrong frontend filenames (`src/App.jsx`,
`chat-client.js` — the repo is TypeScript).

Added sections: **Trip creation path** (Phase 4 filled this in), **Node contracts**,
**Reply generation rule**, **Patch pipeline**, **Known debt**.

Verification instead of a mermaid.live paste (step 8): a script parses both fenced
blocks and asserts `subgraph`/`end` balance and that every id used in an edge is
declared. Both balanced, no undeclared ids. Step 9 is likewise scripted — the 14
`NODE_NAMES` are read straight out of `graph.py` and each is asserted present in the
doc, with a companion check that no ghost name (`RespondNode`, `intake_node`,
`AgentState`, `7-branch`, …) survives. Both pass.

**Finding recorded, not fixed — `src/cli/terminal_chat.py` is broken.** It imports
`process_chat_turn` from `src.agents.session`, which no longer exists;
`python -c "import src.cli.terminal_chat"` raises `ImportError`. Nothing imports it, so
nothing failed loudly. Fixing it means porting the CLI onto `build_graph` or deleting
it — a product call, so it is in "Known debt" and the main diagram marks the CLI edge
as broken. The `TripSession` orphan-field survey from Phase 2 step 7 landed in the same
table.