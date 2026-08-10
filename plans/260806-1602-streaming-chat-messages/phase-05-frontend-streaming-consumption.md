---
title: "Phase 5: Frontend streaming consumption"
status: done
phase: 5
priority: P1
effort: "2.5 ngày"
dependencies: [1]
---

# Phase 5: FE tiêu thụ stream

## Overview

Đọc stream SSE, hiển thị token chảy dần trong bong bóng AI, hiện danh sách bước tiến độ
mọc dần, và thêm nút "Dừng". Kèm hạ cấp tự động về `POST /planner_chat` khi SSE không dùng
được.

Chạy **song song với Phase 2/3/4** ngay sau khi Phase 1 đóng contract — mock server
(`frontend/mock/server.js`) đã phát SSE nên FE không phải chờ backend.

## Requirements

- Functional:
  - Bong bóng AI hiện text tăng dần theo `delta`, có con trỏ nhấp nháy khi đang stream.
  - Danh sách bước **mọc dần** theo `phase` event nhận được — không vẽ sẵn ô chờ điền.
  - Nút "Dừng" gọi cancel endpoint + abort reader; tắt khi nhận `phase: persisting`.
  - SSE hỏng (404/415/parse lỗi/mất mạng) → tự động chạy lại lượt qua `POST /planner_chat`.
- Non-functional:
  - `ChatState` hiện có không đổi hình dạng cho phần mà component khác đang đọc —
    `stage-router.tsx`, `stage-hotels.tsx`, `app-shell.tsx` không phải sửa.
  - i18n đủ cả `vi` và `en` cho mọi nhãn bước.

## Architecture

### Không dùng `EventSource`

`EventSource` chỉ GET được, mà lượt chat cần POST body. Dùng `fetch` + `ReadableStream`:

```ts
// frontend/src/api/stream-client.ts  (mới)

export interface SseFrame { event: string; data: unknown }

/** Parser frame SSE tăng dần. Frame ngăn nhau bằng dòng trống; dòng mở đầu ':'
 *  là comment (heartbeat) và bị bỏ qua. Giữ phần đuôi chưa trọn frame giữa các
 *  lần đọc — một chunk TCP có thể cắt ngang giữa frame. */
export async function* parseSse(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<SseFrame> { ... }
```

~40 dòng. Không thêm dependency.

`sendMessageStream()` đặt cạnh `sendMessage()` trong `api/`, giữ nguyên quy ước "không
component nào tự gọi fetch" đã ghi ở đầu `chat-client.ts`.

### Reducer

`use-chat-session.ts` đang có 6 action. Thêm 4, giữ nguyên toàn bộ action cũ để đường POST
fallback đi đúng code hôm nay:

| Action | Tác dụng |
|---|---|
| `STREAM_PHASE` | Đẩy `{key, at}` vào `state.phases[]` |
| `STREAM_DELTA` | Nối text vào `state.streamingText` |
| `STREAM_RESET` | Xoá `state.streamingText` (agent bỏ attempt) |
| `STREAM_CANCELLED` | Xoá bong bóng đang stream + `phases`, `pending=false` |

`SEND_SUCCESS` giữ **nguyên không đổi** — `final` đi qua đúng nó, nên mọi thứ hạ nguồn
(`hotelOptions`, `tripPlan`, `intake`, `suggestions`) hành xử y hệt hôm nay. Đây là điều
làm phase này rẻ: streaming chỉ thêm trạng thái tạm trong lúc chờ, không đụng vào trạng
thái cuối.

Ba field mới trên `ChatState`:

```ts
streamingText: string      // '' khi không stream
phases: TurnPhase[]        // rỗng khi không có lượt nào chạy
cancelState: 'idle' | 'cancelling' | 'blocked'
```

Cả ba đều tạm, đều bị `SEND_SUCCESS` / `STREAM_CANCELLED` dọn sạch.

### Hạ cấp về POST

```ts
try {
  await streamMessage(sessionId, text, lang, handlers)
} catch (err) {
  if (err instanceof StreamUnsupported) {
    // 404/415 → backend chưa có endpoint stream; hoặc frame đầu không tới trong 5s
    // → nghi proxy buffer. Chạy lại lượt qua POST cũ.
    const data = await sendMessage(sessionId, text, lang)
    dispatch({ type: 'SEND_SUCCESS', id, data })
  } else { ...SEND_ERROR... }
}
```

**Chỉ hạ cấp khi chưa nhận được frame nào.** Nếu stream đã chạy rồi mới đứt thì chạy lại
lượt là **gửi lại tin nhắn lần hai** — lượt đầu vẫn đang chạy ở server và vẫn ghi vào
session. Trường hợp đó báo lỗi mạng, không retry. Ghi rõ điều này trong code comment.

### UI

- **`message-bubble.tsx`** — thêm prop `streaming?: boolean`; khi bật, render con trỏ
  `▍` nhấp nháy sau text. Không đổi gì khác; bubble vẫn `whitespace-pre-wrap`.
- **`message-list.tsx`** — khi `streamingText` khác rỗng, render một bubble AI tạm thay
  cho `ElapsedSpinner`. Auto-scroll hiện phụ thuộc `[messages, pending]`; thêm
  `streamingText` vào deps, nhưng **throttle** — cuộn mượt mỗi token sẽ giật. Cuộn tối đa
  ~10 lần/giây.
- **`turn-phases.tsx`** (mới) — danh sách bước mọc dần, mỗi bước một dòng đã hoàn thành có
  tick, bước cuối đang chạy có spinner. Hiện **thay cho** `ElapsedSpinner` khi có
  `phases`, giữ nguyên số giây thật đã trôi bên cạnh.
- **`composer.tsx`** — nút gửi đổi thành "Dừng" khi `pending`. `cancelState='cancelling'`
  → hiện "Đang dừng…", disabled. `'blocked'` (409) → nút biến mất, quay lại spinner.

Nút "Dừng" ở đây **không mâu thuẫn** với quyết định cũ ở
`260803-1200/phase-03-chat-panel-restyle.md:54` ("do not adopt `stop`, that would imply
fake streaming"). Lý do loại nó khi đó là *không có streaming để mà dừng*. Giờ có streaming
thật và huỷ thật ở Phase 4.

### i18n

Nhãn cho **12 khoá** `phase` (bảng contract có 11 dòng — `tool_start`/`tool_end` là hai
khoá chung một dòng), cả `vi` và `en`, trong `frontend/src/i18n/locales/`. Khoá lạ
(backend thêm khoá mới mà FE chưa biết) → **bỏ qua im lặng**, không render mã khoá thô ra
màn hình.

## Related Code Files

- Create: `frontend/src/api/stream-client.ts` — `parseSse`, `sendMessageStream`, `cancelTurn`, `StreamUnsupported`
- Create: `frontend/src/components/turn-phases.tsx`
- Create: `frontend/src/lib/phase-labels.ts` + `phase-labels.test.ts` — map khoá → khoá i18n, bỏ qua khoá lạ
- Modify: `frontend/src/hooks/use-chat-session.ts` — 4 action, 3 field, đường hạ cấp
- Modify: `frontend/src/types.ts` — `TurnPhase`, `PhaseKey`, 3 field trên `ChatState`
- Modify: `frontend/src/components/message-bubble.tsx` — prop `streaming`
- Modify: `frontend/src/components/message-list.tsx` — bubble tạm + throttle scroll
- Modify: `frontend/src/components/composer.tsx` — nút Dừng
- Modify: `frontend/src/i18n/locales/en.json`, `vi.json`

## Implementation Steps

1. `stream-client.ts`: `parseSse` trước, test đơn vị bằng chuỗi cố định — frame bị cắt
   ngang chunk, heartbeat comment, nhiều frame trong một chunk, frame cuối không có dòng
   trống kết.
2. `sendMessageStream()` + `cancelTurn()` + `StreamUnsupported`.
3. Thêm 3 field + 4 action vào reducer. Giữ `SEND_SUCCESS` nguyên vẹn.
4. Nối vào `send()`, kèm đường hạ cấp (chỉ khi chưa nhận frame nào).
5. `phase-labels.ts` + i18n cho 12 khoá, cả hai ngôn ngữ.
6. `turn-phases.tsx`; thay `ElapsedSpinner` khi có `phases`.
7. Con trỏ streaming trong `message-bubble.tsx`; bubble tạm + throttle scroll trong
   `message-list.tsx`.
8. Nút Dừng trong `composer.tsx`, đủ 3 trạng thái `cancelState`.
9. Chạy toàn bộ với `frontend/mock/server.js` — không cần backend.

## Success Criteria

**Phạm vi 07/08/2026:** người dùng chọn triển khai Phase 5 **trừ** nút Dừng — nó phụ
thuộc cancel endpoint của Phase 4, đang tạm dừng. `STREAM_CANCELLED`/`cancelState` không
được thêm vào reducer; các tiêu chí liên quan tới nút Dừng (3 mục dưới) bị hoãn cùng
Phase 4, không phải bỏ sót.

- [x] Token hiện dần trong bubble; con trỏ nhấp nháy trong lúc stream, biến mất khi xong —
      implement + typecheck + build sạch; **chưa xác minh bằng mắt trong trình duyệt**
      (chính sách repo: không mở Chrome tự động trừ khi được yêu cầu)
- [x] Danh sách bước mọc dần; lượt intake hiện ít bước hơn lượt finalize (không có ô chờ điền)
      — `turn-phases.tsx` chỉ render event thật nhận được, không vẽ sẵn
- [x] Khoá `phase` lạ bị bỏ qua im lặng, không render mã thô — `phase-labels.test.ts`
- [ ] ~~Nút Dừng → `cancelling` → bubble biến mất khi nhận `cancelled`; composer dùng lại được~~
      — hoãn cùng Phase 4 (paused)
- [ ] ~~Nhận `phase: persisting` → nút Dừng biến mất~~ — hoãn cùng Phase 4 (paused)
- [ ] ~~`cancel` trả 409 → nút biến mất, lượt chạy tiếp, `final` vẫn hiển thị đúng~~ — hoãn
      cùng Phase 4 (paused)
- [x] Tắt backend stream (mock trả 404) → tự hạ cấp về POST, người dùng không thấy lỗi —
      `StreamUnsupported` ném khi chưa nhận frame nào (status không 2xx / sai
      content-type / hết `firstFrameTimeoutMs`), `send()` bắt và gọi lại qua
      `sendMessage()` (POST). Xác minh bằng code review + type check, chưa test tay qua mock
- [x] Đứt giữa chừng sau khi đã có frame → báo lỗi mạng, **không** gửi lại tin nhắn —
      `sendMessageStream` chỉ ném `StreamUnsupported` khi `!receivedAnyFrame`; sau đó là
      `Error` thường, không được `send()` bắt để hạ cấp
- [x] `stage-router.tsx` / `stage-hotels.tsx` / `app-shell.tsx` không phải sửa — xác nhận
      bằng `git status`/`git diff`, cả ba file không đổi
- [x] Cuộn không giật khi stream token nhanh — throttle 100ms trong `message-list.tsx`;
      chưa xác minh bằng mắt
- [x] Cả `vi` và `en` đủ nhãn; `npm run build` sạch — `phase-labels.test.ts` khẳng định cả
      12 khoá có nhãn ở cả hai ngôn ngữ; `npm run build` xanh

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Hạ cấp gửi lại tin nhắn hai lần | Chỉ hạ cấp khi **chưa nhận frame nào**. Test riêng cho ca đứt-giữa-chừng |
| Auto-scroll giật vì mỗi token một lần `scrollIntoView` | Throttle ~10 lần/giây; giữ `behavior:'smooth'` |
| Parser SSE sai khi frame bị cắt ngang chunk TCP | Bước 1 test trước bằng chuỗi cố định, gồm đúng ca đó |
| `ChatState` phình làm component khác phải sửa | 3 field mới đều là trạng thái tạm; `SEND_SUCCESS` không đổi nên đường dữ liệu cuối giữ nguyên. Tiêu chí "3 file không phải sửa" gác điều này |
| Nút Dừng bị hiểu là huỷ được mọi lúc | `cancelState='blocked'` làm nút biến mất khi qua rào; nhãn "Đang dừng…" nói rõ là chưa dừng ngay |
| Mock và backend thật lệch contract | Mock viết ở Phase 1 từ cùng bảng contract; Phase 6 chạy lại toàn bộ tiêu chí này trên backend thật |
