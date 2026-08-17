---
phase: 5
title: "Streaming reconnect via LangGraph stream modes"
status: complete
priority: P2
effort: "2.5d"
dependencies: [4]
---

# Phase 5: Streaming reconnect via LangGraph stream modes

## Overview

Nối lại streaming bằng `stream_mode` của LangGraph thay vì hồi sinh `_DeltaGate`. Đây là
phase rủi ro cao nhất trong plan và là phase duy nhất đổi cách một chat turn được thực thi.

## Bằng chứng lỗi

Không frame `delta` nào từng được phát trên graph plane:

- `_DeltaGate` (`streaming.py:198-336`) là producer duy nhất của `delta` và phase
  `generating` — `grep -rn "DeltaGate" backend/src` chỉ ra chính `streaming.py`. **Không
  được khởi tạo ở đâu.**
- `emit_reset` (`streaming.py:169`) — **không call site nào**.
- Frame thật phát ra: `final`/`error` (`routes.py:460,463`) + đúng 4 phase key:
  `received` (`routes.py:407`), `itinerary_build` (`trip_planner.py:2087`), `persisting`
  (`trip_planner.py:416`, `itinerary_store.py:330`), `routing_legs` (`routing.py:220`).

Phía FE là code chết đối xứng: `types.ts:367-379` khai 12 `PhaseKey`;
`use-chat-session.ts` nuôi `streamingText`/`STREAM_DELTA`/`STREAM_RESET`. Hiệu ứng gõ chữ
không bao giờ chạy.

Và một hệ quả nhìn thấy được: `derive-stage.ts` chờ `hotel_search` — phase **không được
emit ở đâu cả** (`grep` chỉ ra nó là nhãn intent của LLM trong `prompts.py:61` /
`extract_patch.py:66`). User gõ đủ thông tin trong một câu kẹt ở panel intake tới tận
`itinerary_build`, tức sau khi đã tìm khách sạn xong.

## Requirements

**Functional**
- Turn có LLM sinh prose (`qa_node`, `intake_qa`) phát `delta` frame theo token.
- Turn deterministic (`ask_slot`, `hotel_node`, `itinerary_node`) **không** phát `delta` —
  không có gì để stream, và giả vờ stream text đã có sẵn là dối trá về tiến độ.
- Phase key phát ra từ node thật đang chạy, gồm `hotel_search`.
- `final` vẫn là nguồn sự thật cuối; FE thay `streamingText` bằng `data.reply`.
- Plain `POST /planner_chat` không đổi hành vi.

**Non-functional**
- **Không** stream token của `extract_patch` (xuất JSON) hay `supervisor` (routing JSON).
  Đây là yêu cầu bảo mật/UX, không phải tinh chỉnh.
- Bộ lọc phải theo **node**, không theo prefix text. Đó là điểm khác biệt cốt lõi so với
  `_DeltaGate`.
- Interrupt/resume phải hoạt động y nguyên qua đường stream.

## Architecture

### Vì sao không hồi sinh `_DeltaGate`

`_DeltaGate` đoán xem text có phải tool-call JSON không bằng cách nhìn ký tự đầu (`{`,
`[`, `SYSTEM ERROR:`). Đó là heuristic dựng cho plane cũ, nơi một ReAct agent duy nhất
sinh mọi text và không có cách nào biết đang ở đâu.

LangGraph cho biết chính xác node nào đang phát token. Lọc theo node là **bảo đảm cấu
trúc** — cùng lập luận mà `qa_node` docstring đã dùng cho ranh giới schema: *"the contract
is enforced by the schema boundary itself, not a runtime check"*.

### Luồng đích

```python
# routes.py::_run_turn_via_graph — nhánh streaming
for mode, chunk in app.stream(
    turn_input, config=config, stream_mode=["updates", "messages"]
):
    if mode == "updates":
        for node_name, update in chunk.items():
            emit_phase(PHASE_KEY_BY_NODE[node_name])   # bỏ qua node không map
    elif mode == "messages":
        message_chunk, metadata = chunk
        if metadata.get("langgraph_node") in STREAMING_NODES:
            emit_delta(message_chunk.content)
```

`STREAMING_NODES = {"qa_node", "intake_qa"}` — whitelist, không blacklist. Node mới thêm
sau này mặc định **không** stream cho tới khi được thêm vào tập này một cách có ý thức.

### Bảng ánh xạ node → PhaseKey

Node có sẵn từ `graph.py:87-106`. FE `PhaseKey` từ `types.ts:367-379`.

| Node | PhaseKey | Ghi chú |
|---|---|---|
| — | `received` | Vẫn emit thủ công ở đầu `_run_turn_via_graph` |
| `load_context` | `compacting_history` | Tên FE đã có sẵn, sát nghĩa nhất |
| `scope_guard` | *(không map)* | Quá nhanh, không đáng một dòng UI |
| `extract_patch` | `intake_check` | Bước chậm nhất của turn intake |
| `validate_patch` | *(không map)* | |
| `apply_patch` | *(không map)* | |
| `ask_slot` | *(không map)* | |
| `intake_qa` | `generating` | Có stream token |
| `supervisor` | `routing` | |
| `hotel_node` | `hotel_search` | **Đây là key `derive-stage.ts` đang chờ** |
| `itinerary_node` | `itinerary_build` | Trùng key đang emit trong `trip_planner.py` — xem Risk |
| `booking_node` | *(không map)* | |
| `qa_node` | `generating` | Có stream token |
| `budget_check` | *(không map)* | |
| `respond` | *(không map)* | Terminal, `final` nói thay |

`route_decided`, `tool_start`, `tool_end` không có nguồn phát trong graph hiện tại →
**xóa khỏi `PhaseKey`** ở FE thay vì để chúng làm nhiễu. Nếu sau này cần tool-level
progress, `stream_mode="messages"` có metadata tool để thêm lại.

### Nguồn state cuối sau khi stream

`app.stream()` không trả state cuối như `app.invoke()`. Lấy bằng `app.get_state(config)
.values` sau khi generator drain. Nhánh interrupt: `updates` mode phát key `__interrupt__`
— bắt tại đó, giữ nguyên logic `unresolved_resume_text` hiện có ở `routes.py:411-418`.

### Ranh giới sync/async

Giữ nguyên kiến trúc hiện tại: `planner_chat_stream` là `async def`, chạy turn trong
worker pool qua `run_in_executor`, `TurnEmitter.emit()` bắc cầu bằng
`call_soon_threadsafe`. `app.stream()` là generator **đồng bộ** → chạy thẳng trong worker
thread, không cần đổi gì ở tầng transport. Đây là lý do phase này không phải viết lại
`streaming.py`.

## Related Code Files

- Modify: `backend/src/api/routes.py` — `_run_turn_via_graph` tách nhánh stream/invoke
- Modify: `backend/src/api/streaming.py` — thêm `emit_delta`; **xóa** `_DeltaGate` và `emit_reset`
- Create: `backend/src/agents/graph/phase_keys.py` — `PHASE_KEY_BY_NODE`, `STREAMING_NODES`
- Modify: `frontend/src/types.ts` — `PhaseKey` bỏ `route_decided`/`tool_start`/`tool_end`; `StreamEvent` bỏ `reset`
- Modify: `frontend/src/lib/phase-labels.ts` — bỏ label tương ứng
- Modify: `frontend/src/hooks/use-chat-session.ts` — bỏ `STREAM_RESET`
- Modify: `frontend/src/api/stream-client.ts` — bỏ nhánh `case 'reset'`
- Modify: `frontend/src/lib/derive-stage.ts` — `hotel_search` giờ có thật, giữ nguyên logic
- Create: `backend/tests/test_stream_modes.py`

## Implementation Steps

1. **Test đỏ trước.** `test_qa_turn_emits_delta_frames`: chạy turn qa_node qua endpoint
   stream với LLM giả sinh nhiều chunk, assert có ≥1 `delta` frame. Và
   `test_extract_patch_never_streams`: turn intake với extractor sinh JSON → **không**
   `delta` frame nào.
2. Tạo `phase_keys.py` với hai hằng số. Viết test khẳng định mọi key trong
   `PHASE_KEY_BY_NODE.values()` tồn tại trong `PhaseKey` của FE (đọc `types.ts` bằng
   regex, hoặc — tốt hơn — để Phase 8 sinh danh sách này).
3. Tách `_run_turn_via_graph` thành `_run_turn_streaming` và `_run_turn_blocking` dùng
   chung phần dựng input/xử lý interrupt. **Không** để hai bản copy logic interrupt.
4. Thêm `emit_delta` vào `streaming.py` (đối xứng `emit_phase`, cùng guard no-emitter).
5. Nối `app.stream(stream_mode=["updates","messages"])` vào nhánh streaming.
6. Xóa `_DeltaGate`, `emit_reset` và test của chúng.
7. Dọn FE: bỏ `reset` khỏi `StreamEvent`, `STREAM_RESET` khỏi reducer, 3 PhaseKey chết,
   label tương ứng. Chạy `npm run typecheck` + `npm test`.
8. Kiểm thủ công: hỏi một câu Q&A ("khách sạn này có hồ bơi không?") → thấy chữ chạy dần.
   Gõ đủ thông tin một câu → panel generating hiện ngay khi `hotel_search` bắn.

## Success Criteria

- [x] Cả hai test ở bước 1 fail trước, pass sau — `test_stream_modes.py` 11/11
- [ ] Turn qa_node hiện hiệu ứng gõ chữ trong UI *(cần kiểm thủ công; backend có test khẳng định delta frame)*
- [x] Turn intake **không** hiện JSON của extractor ở bất kỳ khung nào
- [x] `hotel_search` phase được emit → `derive-stage.ts` chuyển sang panel generating đúng lúc
- [x] `grep -rn "DeltaGate|emit_reset" backend/` → chỉ còn trong docstring giải thích lịch sử
- [x] `grep -rn "STREAM_RESET|onReset" frontend/src` → không kết quả
- [x] `PhaseKey` không còn key nào không có nguồn phát — có test đối chiếu `PHASE_KEY_BY_NODE` với union trong `types.ts`
- [x] Interrupt/resume vẫn hoạt động qua stream (`test_interrupt_resume.py` pass)
- [x] Plain `POST /planner_chat` không đổi hành vi (695 pass / 5 fail = baseline)

## Ghi chú thực thi (2026-08-16)

### Probe trước, viết sau

Hai giả định của plan đều **chưa được kiểm chứng** khi viết, nên bước đầu là một probe
thật với `stream_mode=["updates","messages"]`. Kết quả đổi cả thiết kế lẫn mức độ tin cậy:

| Câu hỏi | Plan nói | Thực tế đo được |
|---|---|---|
| `metadata["langgraph_node"]` của token từ ReAct subgraph `qa_node` | *"có thể là tên node con"* — cần verify | Là **`"qa_node"`** — tên node cha. Whitelist theo tên node là đủ |
| `intake_qa` dùng `llm.invoke()` (không stream) thì có token không? | không đề cập | **Có** — 15 chunk, `langgraph_node == "intake_qa"` |
| Ai khác phát lên kênh `messages`? | không đề cập | **`respond` và `supervisor`**. Đây là phát hiện quan trọng nhất |

`respond` ghi reply hoàn chỉnh vào chính kênh `messages`. Nếu lọc sai (hoặc không lọc),
toàn bộ câu trả lời sẽ được gửi **hai lần** — một lần dạng delta, một lần trong `final`.
Whitelist `STREAMING_NODES = {qa_node, intake_qa}` loại nó theo cấu trúc; có test riêng
khẳng định điều đó.

### Chốt vấn đề `itinerary_build` phát hai lần

Plan để ngỏ (*"cần chốt khi implement"*). **Quyết định: không map `itinerary_node`.**

Các emit thủ công nằm *bên trong* service mà `itinerary_node` gọi — `itinerary_build`
(`trip_planner.py`), `routing_legs` (`routing.py`), `persisting` (`itinerary_store.py`) —
mô tả các bước *trong* một node, thứ mà ranh giới node không nhìn thấy. Chúng nói nhiều
hơn một dòng `itinerary_build` ở mức node, và đã chạy đúng từ trước. Map thêm node chỉ tạo
ra dòng trùng tên (FE key theo `${key}-${at}`). Không xóa gì cả — chỉ không map.

### Một hàm, một cờ — không phải hai hàm

Plan đề xuất tách `_run_turn_streaming` / `_run_turn_blocking`. Làm vậy thì nhánh
interrupt tồn tại hai bản. Thay bằng `_drive_turn(app, config, turn_input, *, stream)` —
chỗ **duy nhất** hai chế độ khác nhau. Mọi thứ bao quanh (dựng input, nhánh resume, xử lý
interrupt, persist, dựng response) dùng chung, nên hai chế độ không thể trả lời khác nhau
cho cùng một tin nhắn.

`app.stream()` không trả state đã merge như `invoke()`, nên state cuối đọc từ
`app.get_state(config).values` sau khi generator drain; `__interrupt__` bắt từ `updates`
rồi gắn lại vào result để hai chế độ có cùng shape.

### Dọn kèm

- Xóa `_DeltaGate` (152 dòng), `emit_reset`, và `tests/test_api/test_delta_gate.py`
- FE: bỏ `STREAM_RESET`/`onReset`/`case 'reset'`, 3 `PhaseKey` chết, label tương ứng
- Xóa 3 khóa i18n mồ côi (`phaseRouteDecided`, `phaseToolStart`, `phaseToolEnd`) ở cả `en`/`vi`
- Cập nhật `docs/chat_api_contract.md`: bỏ `reset` khỏi tập event, sửa bảng phase key
  (bảng cũ vẫn trỏ vào `agents/session.py` của plane đã chết)

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **`itinerary_build` bị emit hai lần** (từ node mapping và từ `trip_planner.py:2087`) | Cao | FE `TurnPhases` key theo `${row.key}-${row.at}` → hai dòng trùng tên. Quyết định: **xóa `emit_phase` thủ công trong `trip_planner.py`/`itinerary_store.py`/`routing.py`**, để node mapping là nguồn duy nhất. Trừ `routing_legs` (chi tiết hơn node) — giữ và không map `itinerary_node`... **cần chốt khi implement**, không để cả hai cùng chạy |
| `stream_mode="messages"` phát cả token của LLM trong tool của qa_node | Cao | `metadata["langgraph_node"]` với ReAct subgraph có thể là tên node con. Phải verify thực tế trong bước 1 và điều chỉnh whitelist; test `test_extract_patch_never_streams` là lưới an toàn |
| `app.stream()` đổi ngữ nghĩa lỗi so với `app.invoke()` | Trung bình | Exception giờ ném từ trong generator giữa chừng, sau khi vài frame đã gửi. `planner_chat_stream` đã bắt và emit `error` (`routes.py:461-463`) — verify frame `final` không bao giờ đi cùng `error` |
| Tách hai nhánh làm logic interrupt phân kỳ | Trung bình | Bước 3 bắt buộc dùng chung helper; test `test_interrupt_resume.py` chạy trên **cả hai** đường |
| Xóa 3 PhaseKey là breaking change cho FE | Thấp | Chúng chưa bao giờ được emit; xóa là dọn code chết, không đổi hành vi |
| LangGraph 1.x đổi chữ ký `stream_mode` | Thấp | `requirements.txt` ghim `langgraph>=1.2.0,<2.0.0`; verify với bản đang cài trước khi viết |
