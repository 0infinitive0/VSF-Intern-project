---
phase: 3
title: "Frontend late suggestions consumption"
status: done
priority: P1
effort: "0.5d"
dependencies: [2]
---

# Phase 3: Frontend late suggestions consumption

## Overview

`stream-client.ts` hiện `return frame.data` ngay tại `case 'final'`
(`stream-client.ts:181`) nên **ngừng đọc stream** — frame `suggestions` phát
sau đó sẽ không bao giờ tới tay app. Phase này đổi vòng đọc để commit tin nhắn
tại `final` nhưng vẫn drain tiếp tới khi stream đóng.

## Requirements

**Functional**
- Tin nhắn assistant vẫn hiển thị đúng thời điểm `final` như hiện nay (không
  chậm thêm).
- Frame `suggestions` sau `final` cập nhật `state.suggestions`.
- Không có frame `suggestions` (LLM hỏng, hoặc turn không đủ điều kiện) →
  không có chip. Đây là trạng thái hợp lệ, không phải lỗi, và FE không cần
  nhánh xử lý riêng.
- Frame `suggestions` của turn cũ không được ghi đè turn mới (guard `turnId`
  như `STREAM_PHASE`/`STREAM_DELTA`).
- Stream kết thúc mà chưa từng có `final` → vẫn ném lỗi như hiện nay.

**Non-functional**
- Giữ `StreamUnsupported` chỉ ném trước khi response 200 được thiết lập —
  không đổi ngữ nghĩa này.

## Architecture

Đổi hợp đồng của `sendMessageStream`:

| Trước | Sau |
|-------|-----|
| `case 'final': return data` | `case 'final': finalData = data; handlers.onFinal?.(data)` |
| promise resolve tại `final` | promise resolve khi stream đóng, trả `finalData` |
| — | `case 'suggestions': handlers.onSuggestions?.(data.suggestions)` |
| — | hết vòng mà `finalData == null` → ném lỗi như cũ |

Caller (`use-chat-session.ts:517-530`) dispatch `SEND_SUCCESS` từ `onFinal`
thay vì từ giá trị promise trả về, để `pending` được gỡ ngay tại `final`.
Giá trị promise vẫn giữ để nhánh catch/fallback không phải đổi hình dạng.

## Related Code Files

- Modify: `frontend/src/api/stream-client.ts`
  - `StreamHandlers`: thêm `onFinal?: (data: PlannerChatResponse) => void` và
    `onSuggestions?: (suggestions: Suggestion[]) => void`.
  - Vòng `for await`: bỏ `return` ở `case 'final'`, thêm `case 'suggestions'`.
  - Cập nhật docstring của hàm (dòng 100-116) — nó đang mô tả "resolves with
    the `final` payload once the stream's single terminal frame arrives".
- Modify: `frontend/src/hooks/use-chat-session.ts`
  - Union `Action` (khai báo tại dòng 73) — thêm
    `{ type: 'STREAM_SUGGESTIONS'; suggestions: Suggestion[]; turnId: number }`
    cạnh `STREAM_DELTA` (dòng 94).
  - Nhánh reducer mới, guard `turnId` giống `STREAM_DELTA` (315-318).
  - Truyền `onFinal` + `onSuggestions` vào `sendMessageStream`.
- Không đụng `frontend/src/types/index.ts`: union `Action` nằm trong
  `use-chat-session.ts`, còn type `Suggestion` đã export sẵn từ `types`.

## Implementation Steps

1. Thêm 2 handler vào `StreamHandlers`, đổi vòng đọc, sửa docstring.
2. Thêm `case 'suggestions'` — đọc `data.suggestions` (mảng `{label, value}`).
3. Thêm biến thể `STREAM_SUGGESTIONS` vào union `Action` + nhánh reducer.
4. Nối handler ở call site; `SEND_SUCCESS` chuyển sang `onFinal`.
5. Test `stream-client.test.ts`: stream có `final` rồi `suggestions` →
   `onFinal` gọi 1 lần, `onSuggestions` gọi 1 lần, promise resolve với payload
   của `final`.
6. Test `use-chat-session.test.ts`: `STREAM_SUGGESTIONS` với `turnId` cũ bị bỏ
   qua; với `turnId` hiện tại thì set `suggestions`.

## Success Criteria

- [ ] `SuggestionChips` hiện chip sau khi tin nhắn đã hiển thị, không có nháy loading thêm. Đúng về mặt cấu trúc (`onSuggestions` chỉ bắn sau `onFinal`, không có nhánh code nào đảo thứ tự) nhưng chưa xác nhận bằng render/browser thật.
- [x] Turn mới bắt đầu trước khi chip của turn cũ tới → chip cũ bị bỏ qua. Verified bằng reducer test (`turnId` guard) + code review fix: `send()` giờ abort stream của turn trước khi mở turn mới (turnId không tự tăng giữa hai tin nhắn cùng session, guard riêng không đủ).
- [x] Stream không có frame `suggestions` (turn qa) → `state.suggestions` giữ nguyên hành vi hiện tại. `applyPlannerResponse` luôn set `suggestions: data.suggestions || []` tại `SEND_SUCCESS`, không đổi bởi Phase 3.
- [x] Test hiện có của `stream-client` và `use-chat-session` vẫn xanh.

## Risk Assessment

- **`abortRef.current.abort()` khi user gửi tin mới sẽ cắt stream trước khi
  chip tới.** Đúng như mong muốn — turn cũ không nên ghi đè turn mới; guard
  `turnId` là lớp bảo vệ thứ hai.
- **Đổi thời điểm resolve có thể làm test cũ treo** nếu test giả lập stream
  không đóng body. Kiểm tra `stream-client.test.ts` hiện có và bổ sung đóng
  stream nếu cần.
- **`pending` gỡ muộn** nếu quên chuyển `SEND_SUCCESS` sang `onFinal` — sẽ
  thấy ngay ở test/UX; đây là bước bắt buộc, không phải tuỳ chọn.
