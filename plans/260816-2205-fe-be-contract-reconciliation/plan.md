---
title: "FE/BE contract reconciliation — hồi phục các hợp đồng đứt sau cutover graph plane"
description: "Nối lại persistence, restore, streaming và các field request bị rơi sau khi xóa legacy plane; chốt server snapshot làm nguồn sự thật cho intake form; khóa type contract bằng codegen từ OpenAPI."
status: pending
priority: P1
effort: "~11.5d"
tags: [contract, persistence, streaming, langgraph, frontend, regression]
created: 2026-08-16
updated: 2026-08-16
blockedBy: []
blocks: [260812-0927-langgraph-orchestration-state-patch-and-interrupts]
---

# FE/BE contract reconciliation

## Overview

Commit `e26d6f5` ("Implement reply contract and clean up graph plane") xóa cascade
`process_chat_turn` và chuyển toàn bộ chat turn sang `_run_turn_via_graph`. Việc xóa
là đúng theo plan [`260815-2300-reply-contract-and-graph-plane-cleanup`](../260815-2300-reply-contract-and-graph-plane-cleanup/plan.md),
nhưng **plane cũ còn giữ nhiều side-effect mà plane mới không tiếp quản**. Kết quả là
một loạt hợp đồng FE↔BE đứt im lặng: không có test nào fail, không có exception nào
được log, chỉ có tính năng ngừng hoạt động.

Plan này đóng lại toàn bộ khoảng cách đó, cộng thêm một quyết định thiết kế mà bug
"chatbot gửi 2 tin nhắn" phơi ra: **server snapshot là nguồn sự thật cho intake form**,
không phải local form state.

### Ba nguyên nhân gốc

| # | Nguyên nhân | Hệ quả |
|---|---|---|
| 1 | Cutover không chuyển side-effect của plane cũ | Mất persist session, restore rỗng, streaming chết, phase key thiếu |
| 2 | `_run_turn_via_graph` chỉ nhận `(session_id, message, language)` | `selection_message`, `stay_dates`, `min_price`, `max_price` rơi im lặng |
| 3 | `frontend/src/types.ts` maintain thủ công, verify bằng đọc code | Lệch nullability, field thừa/thiếu, `stage === 'error'` không bao giờ đúng |

### Ba quyết định đã chốt

| Câu hỏi | Quyết định | Lý do |
|---|---|---|
| Persist lịch sử từ đâu? | **Writer mới đọc thẳng `TravelGraphState`** | Đúng tinh thần "single control plane" của plan 260812; xóa hẳn mirror `TripSession.state` thay vì hồi sinh nó |
| Streaming? | **Nối lại đầy đủ** | Dùng LangGraph `stream_mode` thay vì hồi sinh `_DeltaGate` — bộ lọc theo node là bảo đảm cấu trúc, không phải heuristic prefix |
| Intake source of truth? | **Server snapshot thắng local form** | Local form không phân biệt được "user chưa trả lời" với "backend vừa mở lại field" |

### Nguyên tắc xuyên suốt

- **Không hồi sinh `TripSession.state` cho luồng HTTP.** Nó chỉ còn phục vụ CLI
  (`src/cli/terminal_chat.py`). Mọi thứ web đọc/ghi từ graph state.
- **Không thêm heuristic parse text.** Mọi field FE cần phải là structured field trên
  wire.
- **Mỗi phase phải có test tái hiện được bug trước khi sửa.** Toàn bộ nhóm lỗi này lọt
  lưới vì không có test nào phủ ranh giới FE↔BE.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Lịch sử hội thoại persist và restore đúng, không qua `TripSession.state` | P1 |
| 2 | Session sống sót qua reload trang với mọi giá trị `AUTH_REQUIRED` | P1 |
| 3 | Mọi field trên `PlannerChatRequest`/`SelectHotelRequest` đến được graph hoặc bị xóa khỏi schema | P1 |
| 4 | Streaming phát `delta` + phase key thật; không còn code chết hai đầu | P2 |
| 5 | Intake form theo server snapshot; không còn bubble câu hỏi trùng | P1 |
| 6 | Lỗi backend hiển thị như lỗi trên UI | P2 |
| 7 | `types.ts` sinh từ OpenAPI, drift bị CI chặn | P2 |

## Phases

| # | Phase | Status | Ưu tiên | Phụ thuộc |
|---|-------|--------|---------|-----------|
| 1 | [Session persistence writer](./phase-01-start.md) | Complete | P1 | — |
| 2 | [Restore endpoint from real state](./phase-02-restore-endpoint-from-real-state.md) | Complete | P1 | 1 |
| 3 | [Auth-correct session bootstrap](./phase-03-auth-correct-session-bootstrap.md) | Complete | P1 | — |
| 4 | [Request field pass-through](./phase-04-request-field-pass-through.md) | Complete | P1 | — |
| 5 | [Streaming reconnect via LangGraph stream modes](./phase-05-streaming-reconnect-via-langgraph-stream-modes.md) | Complete | P2 | 4 |
| 6 | [Intake server-snapshot source of truth](./phase-06-intake-server-snapshot-source-of-truth.md) | Complete | P1 | — |
| 7 | [Stage vocabulary and error surfacing](./phase-07-stage-vocabulary-and-error-surfacing.md) | Complete | P2 | 2 |
| 8 | [Typed contract from OpenAPI](./phase-08-typed-contract-from-openapi.md) | Pending | P2 | 1,2,4,5,7 |

Phase 8 chạy cuối cùng vì nó **khóa** các shape mà phase 1-7 còn đang đổi.

### Thứ tự chạy đề xuất

```
1 → 2 → 7 ─┐
3 ─────────┤
4 → 5 ─────┼→ 8
6 ─────────┘
```

Phase 3 và 6 độc lập hoàn toàn, diff nhỏ, tác động người dùng cao — có thể ship trước
để lấy giá trị sớm.

## Ranh giới file (tránh xung đột khi chạy song song)

| Phase | Sở hữu ghi |
|---|---|
| 1 | `backend/src/services/session_store.py`, `backend/src/api/routes.py` (`_run_turn_via_graph` phần persist + docstring `create_session`) |
| 2 | `backend/src/agents/graph/response_payload.py` (**tạo mới**), `backend/src/agents/graph/nodes/respond.py`, `backend/src/api/routes.py` (`restore_session`), `backend/src/models/schemas.py` (`IntakeStatus.from_state`) |
| 3 | `frontend/src/hooks/use-chat-session.ts`, `frontend/src/api/chat-client.ts` |
| 4 | `backend/src/api/routes.py` (handlers), `backend/src/models/schemas.py` (request models) |
| 5 | `backend/src/api/streaming.py`, `backend/src/api/routes.py` (`_run_turn_via_graph` tách nhánh), `backend/src/agents/graph/phase_keys.py` (**tạo mới**), `frontend/src/lib/phase-labels.ts`, `frontend/src/api/stream-client.ts`, `frontend/src/types.ts` (PhaseKey/StreamEvent) |
| 6 | `frontend/src/lib/next-intake-field.ts`, `frontend/src/hooks/use-intake-form.ts`, `frontend/src/components/chat-panel.tsx` |
| 7 | `backend/src/agents/graph/response_payload.py` (`derive_stage`), `backend/src/models/schemas.py` (`ChatStage`), `frontend/src/components/message-bubble.tsx`, `frontend/src/types.ts` (`Stage`) |
| 8 | `frontend/src/types/` (thay `types.ts`), `frontend/package.json`, `.github/workflows/` |

**Xung đột đã biết:**

| Cặp | File chung | Xử lý |
|---|---|---|
| 2 ↔ 7 | `response_payload.py` (`derive_stage`) | Phase 7 `dependencies: [2]` — Phase 2 tạo module, Phase 7 sửa hàm trong đó |
| 1 ↔ 2 ↔ 4 ↔ 5 | `backend/src/api/routes.py` | Bốn vùng khác nhau trong cùng file. Chạy tuần tự hoặc merge cẩn thận; Phase 5 tách `_run_turn_via_graph` nên phải sau Phase 4 |
| 4 ↔ 7 | `backend/src/models/schemas.py` | Phase 4 sửa request models, Phase 7 sửa `ChatStage` — không giao nhau, an toàn song song |
| 5 ↔ 7 ↔ 8 | `frontend/src/types.ts` | Phase 8 **xóa** file này. Phải chạy sau cả 5 và 7 (đã có trong `dependencies`) |

## Success Criteria

- [ ] Sau một chat turn thật, `sessions` và `chat_messages` có row; `GET /chat/sessions` trả về session đó
- [ ] `GET /chat/{id}/restore` trả messages, stage, hotel_options, intake thật — khôi phục hội thoại cũ hiện đúng nội dung
- [ ] Reload trang giữ nguyên session với `AUTH_REQUIRED=false` **và** `AUTH_REQUIRED=true`
- [ ] `POST /hotels/select` dùng `selection_message` của client; `PlannerChatRequest` không còn field nào bị nuốt
- [ ] Stream phát ít nhất một `delta` frame trên turn qa_node/intake_qa; `hotel_search` phase được emit
- [ ] Gõ "tôi muốn đổi ngày đi" hiện **một** câu hỏi và widget date-picker, không phải chips sở thích
- [ ] Lỗi backend hiện với styling lỗi trên UI
- [ ] CI (`npm run openapi:check`) đỏ khi backend schema đổi mà chưa regen types
- [ ] Không còn code chết: `_DeltaGate`/`emit_reset` hoặc đã được dùng, hoặc đã bị xóa

## Không làm trong plan này (non-goals)

- **Không** thực hiện Phase 16 của plan 260812 (conversational polish). Nó vẫn `pending`
  và giờ `blockedBy` plan này: Phase 1/2/7 di chuyển và đổi chữ ký các hàm trong
  `respond.py`, nên làm Phase 16 trước sẽ phải rebase lên một module đã dời chỗ
- **Không** thiết kế lại luồng intake widget — chỉ sửa nguồn sự thật và câu hỏi trùng
- **Không** bật `AUTH_REQUIRED=true` — Phase 3 chỉ làm cho cả hai giá trị đều đúng

## Quyết định đã chốt (2026-08-16)

Ba câu hỏi mở của bản nháp đầu đã được người dùng quyết định. Ghi lại ở đây để lần đọc
sau biết đây là lựa chọn có ý thức, không phải mặc định trôi.

### QĐ-1 — `sessions.context_data` dùng **schema v3 sạch**, không tái dùng v2

Writer mới định nghĩa v3 lấy nguồn từ `TravelGraphState`, thay vì nhồi dữ liệu graph vào
shape v2 vốn mô tả `TripSession.state`. Giữ v2 sẽ để lại vĩnh viễn một schema mang từ vựng
của plane đã chết (`workflow` = `_CHECKPOINT_FIELDS`, `pending_hotel_selection`).

Hệ quả phải xử lý trong Phase 1:
- `summarize()` phải đọc được **cả ba** v1/v2/v3 (row cũ trong DB vẫn phải hiện ở history rail).
- `deserialize()` gặp row v3 sẽ rơi nhầm vào nhánh `_deserialize_v1` → phải chặn tường minh.
- Writer chỉ ghi v3. Không viết migration ngược.

### QĐ-2 — Chấp nhận degrade khi `CHECKPOINTER_BACKEND=memory`

Restore sau khi restart process sẽ có transcript (từ `chat_messages`) nhưng mất
`travel_state`/`trip_data` (từ checkpointer). **Không** rebuild `travel_state` từ
`context_data` — làm vậy tạo nguồn sự thật thứ hai cho cùng dữ liệu, đúng thứ QĐ-1 đang
loại bỏ.

Đường thoát cho production là `CHECKPOINTER_BACKEND=postgres`, và nhánh đó **đã wired
đầy đủ**: `main.py:88-105` dựng `PostgresSaver(pool)`, gọi `.setup()`, sweep checkpoint
mồ côi theo TTL, inject vào registry; package `langgraph-checkpoint-postgres` đã cài;
`_require_checkpointer_database_url` fail-fast khi thiếu DSN; pool config đúng cho
Supavisor (`prepare_threshold=0`).

**Nhưng nhánh postgres chưa có test nào phủ** — chỉ được verify bằng đọc code. Phase 2 bổ
sung một test cho nó (xem Phase 2 bước 7). Bật cờ này ở production vẫn nằm ngoài phạm vi
plan.

### QĐ-3 (đã sửa) — `POST /hotels/change` vào graph tại `hotel_node`

**Bản đầu của QĐ-3 nói giữ nguyên đường full graph, với lý do "gọi thẳng `hotel_node` tạo
cửa sau bỏ qua `validate_patch`". Lý do đó sai và quyết định đã được sửa.**

Hai trường hợp không cùng hình dạng:

| | Nguồn dữ liệu | Ghi vào `travel_state` | Kết luận |
|---|---|---|---|
| `stay_dates` (Phase 4) | **client** | có, không qua validate | cửa sau thật → chặn |
| `/hotels/change` | `travel_state` đã commit | chỉ `hotel_preferences.*`, trong contract đã khai (`contracts.py:76-84`), có `enforce_contract` chặn tại node boundary | không phải cửa sau |

Lập luận thật sự chống lại đường full graph **không phải độ trễ mà là rủi ro đúng/sai**:
`hotel_node` đọc toàn bộ input từ `state["travel_state"]`; chuỗi `"đổi khách sạn"` mang
zero thông tin mới. Đẩy nó qua `extract_patch` là gửi một intent đã biết chắc qua kênh
lossy để nhận lại — kèm khả năng extractor sinh patch giả mạo. Upside bằng 0, downside
khác 0.

**Nhưng "gọi thẳng `hotel_node(state)`" như hàm Python cũng sai** — mất bốn thứ:
checkpointer write, `enforce_contract`, payload từ `respond`, và **`interrupt()`**
(`hotel_node` có thể pause để hỏi center của radius search — `hotel_node.py:11-16`).

**Đường đã chọn — vào graph tại `hotel_node`:**

```python
snapshot = app.get_state(config)
app.invoke(
    Command(goto="hotel_node", update=load_context(snapshot.values)),
    config=config,
)
```

Chạy `hotel_node → budget_check → respond`; bỏ `load_context → scope_guard →
extract_patch → validate_patch → apply_patch`. Giữ nguyên cả bốn thứ trên.

`update=load_context(...)` là bắt buộc, không phải tùy chọn: `load_context` reset 17
field turn-scoped (`load_context.py:38-61`), trong đó có `task_results: []` và
`next_question: None`. Thiếu nó, `respond._question_for_this_reply` sẽ hỏi lại câu hỏi
của turn trước. Tái dùng chính hàm đó thay vì chép danh sách reset — một nguồn sự thật.

**Gated bằng spike.** Docs LangGraph cảnh báo về `Command` làm input: *"Using
`Command(update=...)` alone as input can cause the graph to appear stuck because it
attempts to resume from the latest checkpoint rather than restarting from the start
node."* Cảnh báo đó nói về `update` **không kèm** `goto`, và codebase đã dùng
`Command(resume=...)` làm input thành công (`routes.py:413`) — nhưng `goto` làm entry
point thì chưa được exercise ở đây. Spike ~1h ở đầu Phase 4 quyết định; nếu không đáng
tin thì rơi về phương án cũ (giữ full graph, chỉ sửa hardcode tiếng Việt).

### Kết quả spike (2026-08-16): **PASS — chọn nhánh 6a**

`tests/test_hotels_change_entrypoint.py`, 8/8 pass. Cảnh báo "appear stuck" **không**
xảy ra với dạng có `goto`. Từng khẳng định của QĐ-3 đã được kiểm riêng:

| Khẳng định | Cách kiểm | Kết quả |
|---|---|---|
| Graph chạy `hotel_node`, không đứng im | `task_results` có entry `hotel_node`, `response` khác rỗng | ✅ |
| `extract_patch` **không** chạy | spy đếm lời gọi (không đo thời gian) | ✅ 0 lời gọi |
| `respond` trả payload đầy đủ | `reply`/`stage`/`intake` đều có | ✅ |
| `travel_state` đã commit không mất khi bỏ qua `apply_patch` | đọc lại `destination`/`people` sau turn | ✅ |
| Không kế thừa `next_question` của turn trước | assert `next_question is None` | ✅ |
| Không kế thừa `task_results` của turn trước | turn trước có worker result; sau khi vào lại chỉ còn đúng 1 | ✅ |
| `interrupt()` trong `hotel_node` vẫn pause | radius không có center → `kind == "hotel_radius_center"` | ✅ |
| Pause resume được | `Command(resume="Cầu Rồng")` → hoàn tất, có payload | ✅ |

Một lỗi bắt được khi viết spike: turn dựng bối cảnh ban đầu **không** chạy worker nào
(extractor thật trả rỗng → `impact_map_fallback` → `respond`), nên test "không kế thừa
`task_results`" không có gì để rò rỉ — nó pass một cách vô nghĩa. Đã thay bằng extractor
giả sinh patch `hotel_preferences.*` để turn dựng bối cảnh thật sự chạy `hotel_node`
(đồng thời bỏ luôn một lời gọi LLM thật trong test).

Dù đi đường nào, hai việc vẫn làm: `routes.py:320` dùng `session.language` thay chuỗi
tiếng Việt cứng, và sửa comment sai ở `chat-client.ts:100-105`.

## Open Questions

Ba câu hỏi mở của bản nháp đầu đã được quyết định ở mục trên. Một câu hỏi **mới** phát
sinh khi thực thi Phase 6:

### CH-1 — `extract_patch` không bao giờ sinh `unset`, nên không slot nào bị xóa được (mở 2026-08-16)

Phase 6 verify giả định *"backend xóa slot khi user nói đổi ngày"* và tìm ra là **sai**:
prompt của `extract_patch` khai `unset` trong schema JSON nhưng không hướng dẫn model khi
nào dùng, không có deterministic rewrite nào bù lại, và không có test nào phủ. Chi tiết
bằng chứng: mục "Sai lệch (B)" trong
[phase-06](./phase-06-intake-server-snapshot-source-of-truth.md).

Hệ quả: mọi câu "tôi muốn đổi X" đều để lại giá trị cũ nguyên vẹn trong `travel_state`.
FE giờ đã xử lý đúng khi backend xóa slot (`mergeIntakeIntoForm`), nhưng backend chưa bao
giờ xóa.

Đây là thay đổi hành vi LLM (prompt + eval), không phải sửa contract — thuộc một plan
riêng, không nhét vào plan này. Hai hướng:

- **A.** Dạy prompt emit `unset` khi user nêu ý định đổi mà chưa cho giá trị mới. Rủi ro:
  extractor xóa nhầm slot.
- **B.** Deterministic: nhận diện intent "đổi/thay/sửa <field>" ở code, emit `unset` cho
  đúng field đó. An toàn hơn, nhưng phải maintain danh sách cụm từ hai ngôn ngữ.

Cần người dùng quyết định trước khi mở phase.

<!-- slug: fe-be-contract-reconciliation -->
