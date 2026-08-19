---
title: "DeepDive thinking loader — thay loader chat bằng khối tường thuật theo bước"
description: "Thay ElapsedSpinner trong luồng chat bằng khối thinking: các bước gom nhóm hướng người dùng, tường thuật dữ kiện thật của graph dưới bước đang chạy, bước xong thì đóng ✓, trả lời xong thì thu gọn và giữ lại xem được sau restore."
status: pending
priority: P2
effort: "~5d"
tags: [streaming, sse, ux, frontend, i18n, supabase]
created: 2026-08-18
updated: 2026-08-18
blockedBy: []  # xem ghi chú cross-plan: 260819-0931 Phase 5 chạy sau Phase 4 của plan này
blocks: [260819-0931-responses-api-migration-opt-in-with-reasoning-summary]
---

# DeepDive thinking loader

## Overview

Khi một lượt chat đang chạy, chat hiện 3 chấm nhấp nháy (`ElapsedSpinner`,
`frontend/src/components/message-list.tsx:95`) — không nói gì về việc đang xảy ra. Tiến độ
thật có tồn tại nhưng nằm ở panel phải (`turn-phases.tsx`), và không có nội dung nào mô tả
công việc.

Plan này thay chỗ đó bằng khối thinking: bước gom nhóm hướng người dùng, bước đang chạy có
spinner + **tường thuật dữ kiện thật** của graph bên dưới, bước xong đóng thành dòng ✓.
Trả lời xong, khối thu gọn thành header có chevron, mở lại xem được, kể cả sau restore.

## Lịch sử quyết định

Hướng ban đầu là stream **reasoning summary** của model. Phase 1 (spike, đã chạy) bác bỏ
hướng đó bằng số đo — xem
[`../reports/spike-260818-reasoning-summary.md`](../reports/spike-260818-reasoning-summary.md):

- Reasoning summary **chạy được** trên cả `gpt-5.1` và `gpt-5-mini`, nhưng chỉ xuất hiện khi
  model thấy câu hỏi đủ khó. Prompt lập lịch trình thông thường → `gpt-5.1` không suy luận
  (TTFT 2.8s, viết thẳng 6208 ký tự) → không có gì để tóm tắt. Prompt xác suất → 59 block.
  **Độ phủ không dự đoán trước được**, mà khối UI thì luôn phải có nội dung.
- Bước gọi tool (`hotel_search`) **luôn** rỗng — không có LLM nào suy luận ở đó.
- Ngôn ngữ summary là tiếng Anh, prompt ép không được.

Dữ kiện thật của graph thì luôn có: `hotel_node` luôn biết nó tìm ở đâu, lọc theo gì, còn
lại bao nhiêu kết quả. Nên nguồn nội dung chuyển sang đó.

## Quyết định đã chốt

| Quyết định | Chốt |
|---|---|
| Nguồn nội dung | Dữ kiện thật từ state của graph — không reasoning summary, không text mẫu |
| Render | Template i18n ở **FE**; BE chỉ phát dữ kiện có cấu trúc |
| Frame SSE | **Không thêm frame mới** — dữ kiện đi ké extras của `phase` |
| Vị trí | Trong chat, thay `ElapsedSpinner`; panel phải giữ nguyên |
| Sau khi xong | Thu gọn, giữ lại, mở lại được (có persist) |
| Nhãn bước | Gom nhóm hướng người dùng |
| Model | `backend/.env:69` — `gpt-5.1-2025-11-13` |

## Vì sao hướng này rẻ hơn hẳn hướng cũ

`emit_phase(key, **data)` (`streaming.py:145`) **đã** hỗ trợ extras, và `routing.py:220`
đang dùng thật (`emit_phase("routing_legs", days=len(by_day))`). FE cũng đã khai
`phase` có thể mang extras (`types/index.ts:210`). Nên:

- Không thêm event SSE → không đổi contract, client cũ không vỡ.
- Không đụng Responses API → rủi ro `routes.py:548` (`isinstance(content, str)` nuốt `delta`)
  **biến mất hoàn toàn**.

> **HẾT HIỆU LỰC 2026-08-19 — hai gạch đầu dòng ngay trên.**
>
> Cả hai đều đã bị việc khác vượt qua, và theo hướng có lợi:
>
> - **Guard `isinstance(content, str)` đã được vá** (`routes.py`, plan
>   `260819-0931`). Rủi ro không "biến mất nhờ tránh né" — nó được đóng lại. Lý do phải
>   đóng: langchain định tuyến model sang Responses API theo **tên** (`gpt-5-pro*`, mọi
>   tên chứa `codex`), nên tránh né chưa bao giờ là một chiến lược.
> - **Đã có thêm một event SSE**: `reasoning`. Client cũ vẫn không vỡ — SSE bỏ qua event
>   lạ, và `stream-client.ts:163` có `switch` với nhánh `default` không làm gì.
>
> Người dùng chọn ngày 2026-08-19: bật reasoning summary và render **kèm** dữ kiện graph.
> Phần còn lại của mục này vẫn đúng — dữ kiện graph vẫn là nguồn chính, reasoning chỉ
> chồng thêm khi có, và FE vẫn sở hữu mọi text sản phẩm.
- Không thêm lượt gọi LLM → không thêm chi phí, không thêm latency.
- FE giữ quyền sở hữu text hiển thị — đúng nguyên tắc `phase-labels.ts` đã lập:
  *"backend never sends display text"*.

Plan rút từ 7 phase (~6d) xuống 4 phase còn lại (~4.5d) cộng spike đã chạy.

Riêng phần UI **không** được rút gọn theo: vùng cuộn riêng, bám đáy, dừng bám khi người
dùng đọc, và gradient mờ đều nằm trong Phase 4 theo yêu cầu. Repo hiện **không có** tiền lệ
bám đáy để tái dùng — `message-list.tsx:53-67` chỉ throttle rồi cuộn vô điều kiện — nên đây
là phần dựng mới, không phải chép lại.

## Hai nguồn dữ kiện

**1. Rút từ state delta — một chỗ duy nhất, không đụng node nào.**
`routes.py:536-543` lặp `for node_name, update in chunk.items()` ở stream mode `updates`.
`update` **chính là** dict node vừa trả về. `extract_patch` trả
`{patch, intent, extraction_failed, patch_reason, …}` (`extract_patch.py:510`) — đủ để dựng
"Hiểu yêu cầu". `supervisor` trả `next_worker`. Rút ngay tại chỗ đang gọi `emit_phase`.

**2. Kwargs tại site emit — cho số liệu không nằm trong state delta.**
Số kết quả tìm được / lọc còn lại không có trong dict `hotel_node` trả về
(`{pending_tasks, task_results, selected_hotel_id}`), nên phải phát từ trong node hoặc
service tìm kiếm. Ba site sẵn có (`trip_planner.py:416,2087`, `routing.py:220`,
`itinerary_store.py:330`) nhận thêm kwargs theo cách `routing_legs` đang làm.

## Nhóm bước và dữ kiện

| Nhóm | Phase key | Dữ kiện đề xuất | Nguồn |
|---|---|---|---|
| Hiểu yêu cầu | `received`, `compacting_history`, `routing`, `intake_check` | `intent`, `fields[]` (field nào vừa đổi), `worker` | state delta |
| Tìm kiếm & thu thập | `hotel_search` | `destination`, `radius_km`, `amenities[]`, `found`, `kept` | kwargs tại site |
| Dựng lịch trình | `itinerary_build`, `routing_legs` | `action`, `days[]`, `locked_days[]`; `routing_legs` đã có `days` sẵn | kwargs tại site |
| Hoàn tất | `persisting`, `generating` | — | — |

Quy tắc mở/đóng nhóm: nhóm "mở" khi phase đầu tiên thuộc nhóm về; "đóng" (✓) khi có phase
thuộc nhóm **sau** về; phase thuộc nhóm đã mở gộp vào dòng cũ (vòng lặp supervisor không
tạo dòng trùng); nhóm không có phase nào thì không hiện; `final` về thì mọi nhóm đóng.
Thứ tự theo thứ tự nhóm cố định, không theo thứ tự phase tới.

> Ảnh mẫu có bước "Personalized Validation". Các node tương ứng (`scope_guard`,
> `validate_patch`, `budget_check`) **cố tình không emit** phase vì chạy nhanh hơn tốc độ
> đọc (`phase_keys.py:6`). Nhóm này bỏ.

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Chat hiện bước + tường thuật thật thay cho 3 chấm | P1 |
| 2 | Không regression `delta` / panel phải / POST fallback | P1 |
| 3 | Mọi chữ hiện ra đều truy được về dữ kiện thật — không câu mẫu vô nghĩa | P1 |
| 4 | Tường thuật xem lại được sau reload | P2 |

## Phases

| # | Phase | Status | Ưu tiên | Phụ thuộc |
|---|-------|--------|---------|-----------|
| 1 | [Spike: đo reasoning summary](./phase-01-start.md) | **Complete** | P1 | — |
| 2 | [Phát dữ kiện thật từ state graph](./phase-02-emit-real-facts-from-graph-state.md) | **Done** | P1 | 1 |
| 3 | [FE thinking state + render dữ kiện](./phase-03-frontend-thinking-state-and-fact-rendering.md) | **Done** | P1 | 2 |
| 4 | [ThinkingBlock UI trong chat](./phase-04-thinkingblock-ui-in-chat.md) | **Done** | P1 | 3 |
| 5 | [Persist + restore thinking trace](./phase-05-persist-and-restore-thinking-trace.md) | Pending | P2 | 4 |

Phase 1 đã xong; kết quả của nó là lý do plan có hình dạng hiện tại.

## Sở hữu file theo phase

| Phase | Sở hữu ghi |
|---|---|
| 2 | `backend/src/api/routes.py` (vòng drain), `backend/src/api/streaming.py`, `backend/src/agents/graph/nodes/hotel_node.py`, `backend/src/services/{trip_planner,routing,itinerary_store}.py`, `docs/chat_api_contract.md` |
| 3 | `frontend/src/types/index.ts`, `frontend/src/lib/thinking-groups.ts`, `frontend/src/hooks/use-chat-session.ts`, `frontend/src/api/stream-client.ts`, `frontend/src/i18n/` |
| 4 | `frontend/src/components/thinking-block.tsx`, `frontend/src/components/message-list.tsx` |

Plan `260819-0931` Phase 5 chạm **cùng** `stream-client.ts`, `use-chat-session.ts`, và
`thinking-block.tsx` để thêm làn reasoning. Nó chạy **sau** Phase 4 của plan này (khối
thinking phải tồn tại trước) và chỉ thêm field `reasoning` cạnh `lines` — không sửa
đường dữ kiện. Không chạy song song hai plan trên nhóm file này.
| 5 | `supabase/migrations/`, `supabase/seed.sql`, `backend/scripts/database_schema.sql`, `backend/src/services/session_store.py`, `backend/src/models/schemas.py`, `backend/src/api/routes.py` (restore) |

Phase 2 và Phase 5 cùng chạm `routes.py` nhưng khác hàm (vòng drain vs `restore_session`),
và Phase 5 chạy sau nên không giao nhau.

## Success Criteria

- [ ] Gửi câu hỏi thường: khối thinking hiện, có ít nhất một nhóm kèm dữ kiện thật, xong thì thu gọn
- [ ] Gửi yêu cầu dựng lịch trình: ≥3 nhóm nối tiếp, nhóm trước đóng ✓ khi nhóm sau mở
- [ ] Mọi con số hiện trên UI đối chiếu được với log/DB — không số nào bịa
- [ ] Nhóm không có dữ kiện: hiện tiêu đề + spinner, không có vùng text rỗng
- [ ] `delta` (hiệu ứng gõ chữ) chạy y như trước — kiểm riêng
- [ ] Panel phải (`stage-generating`) không đổi hành vi
- [ ] POST `/planner_chat` không streaming: không có khối thinking, không lỗi
- [ ] Abort giữa lượt: khối thinking biến mất sạch, không kẹt spinner
- [ ] Reload + restore: khối thinking lượt cũ mở lại được, nội dung khớp
- [ ] Message cũ không có trace: không hiện header, không lỗi
- [ ] Extras lạ từ backend mới: FE bỏ qua im lặng, không crash
- [ ] Test xanh: `test_stream_modes.py`, `stream-client.test.ts`, `use-chat-session.test.ts`, `phase-labels.test.ts`

## Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Dữ kiện rút từ `update` sai/thiếu vì hình dạng state khác giả định | Trung bình | Phase 2 bước 1 in thật `update` của từng node trước khi viết bộ rút |
| Lấy số kết quả tìm kiếm phải đụng vào `hotel_node` | Trung bình | Giữ thay đổi ở mức thêm một lời gọi `emit_phase`, không đổi logic |
| Dữ kiện nhạy cảm lọt ra client | Trung bình | Whitelist field tường minh; cấm ID nội bộ, tool arg thô, chuỗi lỗi |
| Text i18n dài ra thành câu mẫu vô nghĩa khi thiếu dữ kiện | Trung bình | Thiếu dữ kiện thì **không hiện dòng**, không có câu chống chế |
| Migration Supabase không có quy trình trong repo | Trung bình | Phase 5 viết SQL rồi dừng chờ người dùng chạy tay |
| Tiến độ hiện 2 nơi (chat + panel phải) | Thấp | Đã chấp nhận có ý thức |

## Non-goals

- Không dùng reasoning summary (Phase 1 đã bác bỏ bằng số đo)
- Không thêm lượt gọi LLM nào để sinh text tường thuật
- Không thêm event SSE mới
- Không sửa `turn-phases.tsx` / panel phải
- Không hiện `routing_reasoning` (audit log, `supervisor.py:47` cấm)
- Không thêm nhóm "Kiểm tra phù hợp"

## Câu hỏi mở

Không còn. Ba câu hỏi mở của spike đã chốt (xem bảng Quyết định).

<!-- slug: deepdive-thinking-loader -->
