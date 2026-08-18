# Đặc tả: thay loader chat bằng khối "DeepDive Thinking"

Ngày: 2026-08-18 · Trạng thái: chờ duyệt · Nguồn: yêu cầu người dùng + 4 quyết định đã chốt

## 1. Kết quả mong muốn

Trong luồng chat, khi một lượt đang chạy, thay 3 chấm nhấp nháy (`ElapsedSpinner`) bằng
một khối "đang suy nghĩ": danh sách các bước theo nhóm, bước đang chạy có spinner và
**stream reasoning summary thật của model** ngay dưới nó; bước xong thì đóng lại thành
một dòng ✓. Trả lời xong, cả khối thu gọn thành header có chevron, mở lại xem được,
kể cả sau khi restore session.

## 2. Quyết định đã chốt

| Câu hỏi | Chốt |
|---|---|
| Nguồn text | Reasoning summary thật từ model (Responses API + `reasoning.summary`) |
| Vị trí | Trong chat, thay `ElapsedSpinner`; `TurnPhases` ở panel phải giữ nguyên |
| Sau khi xong | Thu gọn, giữ lại, mở lại được — **có persist** |
| Nhãn bước | Nhãn hướng người dùng, gom nhóm các phase key hiện có |

## 3. Hiện trạng (đã xác minh)

- `frontend/src/components/message-list.tsx:95` — `pending && !streamingText` → `ElapsedSpinner`.
  Đây là điểm thay thế duy nhất trong chat.
- `frontend/src/components/turn-phases.tsx` — UI ✓/spinner đã tồn tại nhưng chỉ dùng ở
  `stage-generating.tsx` (panel phải). Docstring của nó ghi rõ đã **cố tình** không đặt
  trong chat để tránh trùng lặp → quyết định "giữ cả hai" là đảo ngược chủ ý cũ, chấp nhận có ý thức.
- SSE hiện có 4 event: `phase` | `delta` | `final` | `error` (`backend/src/api/streaming.py:88`).
  **Không có** event nào chở nội dung suy luận.
- 9 phase key trong `frontend/src/types/index.ts:191`, phát từ `backend/src/agents/graph/phase_keys.py:25`
  cộng 3 chỗ emit trong service (`trip_planner.py`, `routing.py`, `itinerary_store.py`).
- Model: `gpt-5.1-2025-11-13`, provider `openai`, `llm_reasoning_effort` default `low`
  (`backend/src/config.py:30`). `get_llm` truyền `reasoning_effort` dạng kwarg → đi
  **Chat Completions**, API này không trả reasoning ra ngoài.
- `chat_messages` chỉ có 4 cột: `session_id`, `sender_type`, `message_content`, `created_at`
  (`supabase/seed.sql:394`). Không có chỗ chứa reasoning.

## 4. Ràng buộc phải chấp nhận

1. **Đổi API surface của LLM.** Muốn có reasoning summary phải khởi tạo
   `ChatOpenAI(reasoning={"effort": ..., "summary": "auto"})`. LangChain khi đó tự route
   sang Responses API — đổi format message/tool-call cho **mọi** node dùng model đó, gồm
   cả ReAct subgraph trong `qa_node`. → Phải bật có phạm vi (chỉ node nào cần), không bật toàn cục.
2. **Đảo ngược một tối ưu vừa làm.** Commit `3cd4e4e` hạ `reasoning_effort` để giảm 76s/1536
   hidden token mỗi lượt. Reasoning summary cần effort ≥ `low`, và `low` thường cho summary
   rất ngắn hoặc rỗng. Muốn text đẹp như ảnh mẫu phải `medium`/`high` → latency và chi phí tăng lại.
3. **Không phải bước nào cũng có reasoning.** `hotel_search`, `routing_legs`, `persisting` là
   gọi tool/service, không có LLM suy luận. Các nhóm bước này sẽ chỉ có tiêu đề + spinner,
   không có text chạy bên dưới. Đây là hành vi đúng, không phải bug — không được bịa text để lấp.
4. **Persist cần migration.** `chat_messages` thiếu cột. Lưu ý: migration
   `20260811_add_session_checkpoint_persistence.sql` **không được track trong repo**
   (`backend/src/services/session_store.py:378`) → quy trình migration của dự án đang có lỗ hổng,
   cần xác nhận cách thêm cột mới trước khi code.

## 5. Yêu cầu chức năng

### FR1 — Backend phát reasoning
- Thêm SSE event `reasoning`: `{ text: string, node: string }`, stream theo token.
- Emit qua `emit_reasoning()` trong `streaming.py`, cùng khuôn với `emit_delta` (never-raise,
  no-op khi không streaming).
- Whitelist node được phát reasoning, tách khỏi `STREAMING_NODES` (node stream prose ≠ node
  có reasoning đáng xem).
- Lượt không streaming (POST thường) không đổi hành vi.

### FR2 — Gom nhóm bước
Nhóm hướng người dùng, map từ phase key sẵn có (backend **không** đổi):

| Nhóm | Phase key nguồn |
|---|---|
| Hiểu yêu cầu | `received`, `compacting_history`, `routing`, `intake_check` |
| Tìm kiếm & thu thập dữ liệu | `hotel_search` |
| Dựng lịch trình | `itinerary_build`, `routing_legs` |
| Hoàn tất | `persisting`, `generating` |

Quy tắc: một nhóm "mở" khi phase đầu tiên thuộc nhóm đó về; "đóng" (✓) khi có phase thuộc
nhóm **sau** nó về. Phase thuộc nhóm đã mở trước đó (vòng lặp supervisor) gộp vào dòng cũ,
không tạo dòng mới. Nhóm không có phase nào về thì không hiện.
Nhóm cuối cùng đóng khi `final` về.

> Ảnh mẫu có bước "Personalized Validation". Các node tương ứng (`scope_guard`,
> `validate_patch`, `budget_check`) hiện **cố tình không emit** phase vì chạy quá nhanh
> (`phase_keys.py:6`). Nhóm này tạm bỏ. Muốn có phải thêm phase key mới → xem Câu hỏi mở.

### FR3 — UI trong chat
- Component mới `thinking-block.tsx`, thay `ElapsedSpinner` ở `message-list.tsx:95`.
- Đang chạy: header "Đang suy nghĩ" + chevron (mở sẵn), các nhóm xong hiện ✓, nhóm hiện tại
  hiện spinner + reasoning text chạy bên dưới.
- Text reasoning giới hạn chiều cao, tự cuộn theo token mới, mờ dần ở đáy (như ảnh mẫu).
- Xong: khối tự thu gọn còn 1 dòng header, click để mở lại.
- Trước khi phase đầu tiên về (cửa sổ ~vài trăm ms): fallback về indicator hiện tại.
- `aria-live="polite"`, `aria-busy` đúng trạng thái; reasoning text không được đọc lại
  toàn bộ mỗi token.

### FR4 — Persist & restore
- `final` payload chở thêm trace: `[{ group, text }]`.
- Thêm cột `reasoning_trace jsonb` vào `chat_messages`, ghi kèm message của assistant.
- `/session/restore` trả trace theo từng message; UI hiện header thu gọn, mở ra xem lại được.
- Message cũ không có trace → không hiện header, không lỗi.

## 6. Tiêu chí nghiệm thu

1. Gửi 1 câu hỏi thường: khối thinking hiện, ít nhất 1 nhóm có text reasoning chạy thật
   (không phải text mẫu), xong thì thu gọn.
2. Gửi yêu cầu dựng lịch trình: thấy ≥3 nhóm nối tiếp nhau, nhóm trước đóng ✓ khi nhóm sau mở.
3. Nhóm không có reasoning (`hotel_search`) hiện tiêu đề + spinner, **không** có text bịa.
4. Reload trang rồi restore session: khối thinking của lượt cũ mở lại được, nội dung khớp.
5. Panel phải (`stage-generating`) hoạt động y như cũ, không regression.
6. Fallback POST không streaming: không có khối thinking, không lỗi.
7. Lượt bị abort giữa chừng: khối thinking biến mất sạch, không kẹt spinner.
8. Test hiện có xanh: `stream-client.test.ts`, `use-chat-session.test.ts`,
   `test_stream_modes.py`, `phase-labels.test.ts`.

## 7. Không làm (non-goals)

- Không sửa `turn-phases.tsx` / panel phải.
- Không thêm phase key mới ở đợt này.
- Không hiện reasoning cho provider khác OpenAI (ollama/anthropic/google) — im lặng bỏ qua.
- Không hiện `routing_reasoning` (audit log, `supervisor.py:47` cấm hiện cho user).

## 8. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Bật Responses API làm hỏng tool-call của ReAct trong `qa_node` | **Cao** | Spike trước: bật riêng 1 node, chạy `test_respond.py` + `test_stream_modes.py` |
| `summary` rỗng ở effort `low` | Cao | Đo thực tế trước khi code UI; nếu rỗng phải chọn: nâng effort hay đổi nguồn text |
| Latency/chi phí tăng lại sau `3cd4e4e` | Trung bình | Đo lại thời gian lượt trước/sau, đặt ngưỡng chấp nhận |
| Quy trình migration Supabase không đầy đủ trong repo | Trung bình | Xác nhận cách thêm cột trước khi động vào FR4 |
| Tiến độ hiện 2 nơi gây rối | Thấp | Đã chấp nhận có ý thức |

## 9. Câu hỏi mở

1. `reasoning_effort` nâng lên mức nào? (`low` hiện tại có thể cho summary rỗng — cần spike đo trước.)
2. Có chấp nhận latency tăng trở lại mức trước commit `3cd4e4e` để đổi lấy reasoning đẹp không?
3. Nhóm "Kiểm tra phù hợp" (như ảnh mẫu) có đáng thêm phase key mới ở `scope_guard`/`budget_check` không?
4. Cột `reasoning_trace` thêm bằng cách nào, khi migration gần nhất không được track trong repo?
5. Reasoning summary của OpenAI trả về **tiếng Anh**. Có cần dịch/ép sang tiếng Việt không,
   và nếu ép thì bằng cách nào (prompt hay dịch lại — cả hai đều tốn thêm)?
