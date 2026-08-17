---
phase: 3
title: "Auth-correct session bootstrap"
status: complete
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 3: Auth-correct session bootstrap

## Overview

Lời gọi fetch trần duy nhất còn sót trong frontend làm user mất session mỗi lần reload
trang. Diff rất nhỏ, tác động rất lớn — nên ship sớm, độc lập với mọi phase khác.

## Bằng chứng lỗi

`frontend/src/hooks/use-chat-session.ts:319`:

```ts
const res = await fetch(`/api/v1/chat/${encodeURIComponent(stored)}/plan`)
```

Thiếu **cả ba** thứ mà mọi call khác đều có: `authHeaders()`, `VITE_API_BASE`, và xử lý
401 qua `reportSessionExpired()`.

Chuỗi lỗi với config mặc định (`AUTH_REQUIRED=false`, FE vẫn gửi Bearer token ở mọi call
khác):

1. `POST /chat/session` có token → session được gán `owner_user_id` (`routes.py:188`).
2. Reload → ping `/plan` **không token** → `current_user = None`.
3. `_owned_session_or_404` (`routes.py:111`): owner có, caller `None` → **404**.
4. FE hiểu 404 là "server mất session" → âm thầm `createSession()`.

→ **Mất session sau mỗi lần reload.** Hội thoại đang dở biến mất.

Với `AUTH_REQUIRED=true` hỏng theo kiểu ngược lại: trả **401** chứ không phải 404, FE rơi
vào nhánh `else` "session còn sống" và giữ một session mà server sẽ từ chối ở request kế.

## Requirements

**Functional**
- Ping dùng cùng client wrapper như mọi call khác: auth header, base URL, xử lý 401.
- 404 → tạo session mới (giữ hành vi hiện tại, đúng ý định D1).
- 401 → báo session-expired bus, **không** tạo session mới im lặng (user cần biết mình
  bị đăng xuất).
- Lỗi mạng → giữ session đang lưu, optimistic (giữ hành vi hiện tại).

**Non-functional**
- Không thêm endpoint mới. `GET /chat/{id}/plan` đã đủ làm ping.
- Không tự viết fetch nữa trong hook — dùng `chat-client.ts`.

## Architecture

`chat-client.ts` đã có sẵn `getPlan(sessionId)` (`chat-client.ts:95-97`) dùng `request()`
— đã có auth header, base URL, và `reportSessionExpired()` cho 401. Nhưng nó **throw**
trên mọi lỗi, còn bootstrap cần phân biệt 404 với 401 với lỗi mạng.

Thêm một hàm chuyên dụng thay vì nhét logic vào `getPlan`:

```ts
export type SessionPing = 'alive' | 'gone' | 'unauthorized' | 'unknown'

/** Ping một session đang lưu để biết server còn nhận nó không.
 *  Không throw: bootstrap cần phân biệt ba kết cục, không phải bắt exception. */
export async function pingSession(sessionId: string): Promise<SessionPing>
```

Bảng quyết định trong bootstrap:

| Kết quả ping | Hành động |
|---|---|
| `alive` | `SESSION_READY` với session đang lưu |
| `gone` (404) | `createSession()` → `SESSION_READY` với id mới |
| `unauthorized` (401) | `reportSessionExpired()` đã bắn từ trong client; giữ session đang lưu, **không** tạo mới |
| `unknown` (lỗi mạng) | Giữ session đang lưu (optimistic, như hiện tại) |

Lý do 401 không tạo session mới: token hết hạn là trạng thái tạm thời sẽ được
`AuthProvider` refresh; tạo session mới ở đây sẽ vứt bỏ hội thoại vì một lý do sẽ tự
khỏi trong vài giây.

## Related Code Files

- Modify: `frontend/src/api/chat-client.ts` — thêm `pingSession`
- Modify: `frontend/src/hooks/use-chat-session.ts` — bootstrap dùng `pingSession`, bỏ fetch trần
- Modify: `frontend/src/hooks/use-chat-session.test.ts` — thêm case cho 4 kết cục
- Create: `frontend/src/api/chat-client.test.ts` nếu chưa có coverage cho `request()`

## Implementation Steps

1. **Test đỏ trước.** Trong `use-chat-session.test.ts`, thêm test: session đang lưu +
   server trả 404 → tạo mới; trả 401 → **giữ** session cũ. Test thứ hai phải fail hiện tại.
2. Thêm `pingSession` vào `chat-client.ts`, dùng `BASE` và `authHeaders()`, trả union
   type thay vì throw.
3. Thay khối `if (stored) { ... fetch ... }` trong bootstrap bằng `switch` trên kết quả
   `pingSession`.
4. Kiểm tra thủ công cả hai chế độ: chạy backend với `AUTH_REQUIRED=false` rồi `=true`,
   reload trang, xác nhận session giữ nguyên ở cả hai.

## Success Criteria

- [x] Test 401-giữ-session fail trước, pass sau — **xem "Sai lệch so với bản plan" bên dưới**
- [x] `grep -n "fetch(" frontend/src/hooks/use-chat-session.ts` → không còn kết quả nào
- [ ] Reload trang với `AUTH_REQUIRED=false` → cùng `session_id`, hội thoại còn nguyên *(cần kiểm thủ công)*
- [ ] Reload trang với `AUTH_REQUIRED=true` → cùng `session_id` *(cần kiểm thủ công)*
- [x] Đặt `VITE_API_BASE` trỏ backend khác → bootstrap vẫn hoạt động — ping dùng `BASE`, có test khẳng định URL
- [ ] Token hết hạn → hiện session-expired modal, **không** mất hội thoại *(cần kiểm thủ công; `reportSessionExpired` đã có test)*

## Sai lệch so với bản plan (2026-08-16)

**Dự đoán "401 → tạo session mới" của bản plan là sai.** Code cũ
(`use-chat-session.ts:319-330`) chỉ tạo session mới khi status **đúng bằng 404**;
mọi status khác — gồm 401 — rơi vào nhánh `else` và **giữ** session. Nên test
"401 giữ session" không thể fail-trước theo nghĩa hành vi.

Lỗi thật ở nhánh 401 là **im lặng**: không ai gọi `reportSessionExpired()`, nên user
bị đăng xuất mà không có modal nào hiện ra. Test đã viết khẳng định đúng điều đó
(`chat-client.test.ts` — "reports unauthorized on 401 and notifies the session-expired bus"),
và nó fail trước vì `pingSession` chưa tồn tại.

Lỗi mất-session-mỗi-lần-reload với `AUTH_REQUIRED=false` thì đúng như plan mô tả và
đã được sửa: ping giờ gửi `authHeaders()` nên server trả 200 thay vì 404.

**Ghi chú thiết kế:** logic bootstrap được tách thành `resolveBootstrapSession(deps)`
thuần (inject `ping`/`create`/`fallbackId`), vì project không có jsdom/RTL — đó là cách
duy nhất unit-test được 4 kết cục mà không render hook. `sessionStorage.setItem` ở lại
phía caller để hàm không có side-effect.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Giữ session khi 401 làm user kẹt với session không dùng được | Trung bình | `reportSessionExpired()` đã bắn → `session-expired-modal.tsx` hiện ra và buộc đăng nhập lại. Sau refresh token, session cũ lại hợp lệ vì `owner_user_id` không đổi |
| `pingSession` là API surface mới cần maintain | Thấp | 15 dòng, một call site. Rẻ hơn nhiều so với để logic auth rải rác |
| Vẫn còn fetch trần ở chỗ khác | Thấp | Bước kiểm `grep` ở Success Criteria; `amenity-catalog-client.ts` có fetch không auth nhưng endpoint đó **thật sự** public (`/hotel-amenities` không có `Depends(get_current_user)`) — hợp lệ, không đổi |
