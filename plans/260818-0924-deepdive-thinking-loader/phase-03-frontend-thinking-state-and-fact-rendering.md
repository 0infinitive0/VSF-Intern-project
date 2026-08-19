---
phase: 3
title: "FE thinking state + render dữ kiện"
status: completed
priority: P1
effort: "1d"
dependencies: [2]
---

# Phase 3: FE thinking state + render dữ kiện

## Overview

Lớp dữ liệu và lớp chữ của khối thinking: nhận extras từ frame `phase`, gom phase key thành
nhóm hướng người dùng, và dựng câu tiếng Việt từ dữ kiện bằng template i18n. Không có UI ở
phase này — UI là Phase 4.

Đây là nơi **FE giữ quyền sở hữu text hiển thị**, đúng nguyên tắc `phase-labels.ts` đã lập:
backend gửi khoá đục + số liệu, không bao giờ gửi câu chữ.

## Requirements

**Functional**
- `stream-client.ts` đã truyền cả dict extras qua `onPhase(key, at, d)` (`stream-client.ts:162`)
  — xác nhận, không cần sửa.
- `lib/thinking-groups.ts`: map `PhaseKey` → nhóm + hàm reduce dựng danh sách nhóm.
- `lib/thinking-lines.ts`: dựng dòng chữ từ `(phaseKey, facts)` bằng i18n.
- Reducer `use-chat-session.ts`: state `thinking: ThinkingGroup[]`, cập nhật trong action
  `STREAM_PHASE` sẵn có (không cần action mới — dữ kiện đi cùng phase).
- `thinking` xoá sạch ở mọi chỗ `phases` đang bị xoá (`use-chat-session.ts:44,98,130,148,206,212`).

**Non-functional**
- **Thiếu dữ kiện thì không hiện dòng.** Không có câu chống chế kiểu "Đang xử lý…" —
  dòng trống còn thật thà hơn câu vô nghĩa. Đây là ranh giới giữa plan này và text mẫu.
- **Reasoning KHÔNG được dùng để thoả mãn luật trên** (thêm 2026-08-19). Plan
  `260819-0931` thêm event SSE `reasoning` mang bản tóm tắt suy luận do model viết.
  Dùng nó lấp chỗ một nhóm thiếu dữ kiện là quay lại đúng câu chống chế mà luật này cấm,
  chỉ khác là bằng tiếng Anh. Hai field song song, không cái nào fallback sang cái kia.
- Phase key lạ bỏ qua im lặng (như `phaseLabelKey` đang làm). Field extras lạ cũng bỏ qua.
- `phases` giữ nguyên — panel phải đang dùng. `thinking` là state song song, không thay thế.
- Số tiền/ngày dùng formatter sẵn có (`lib/format-currency.ts`, `lib/format-trip-dates.ts`),
  không tự định dạng lại.

## Architecture

```ts
// lib/thinking-groups.ts
export type ThinkingGroupKey = 'understand' | 'gather' | 'build' | 'finalize'

const GROUP_BY_PHASE: Record<PhaseKey, ThinkingGroupKey> = {
  received: 'understand', compacting_history: 'understand',
  routing: 'understand',  intake_check: 'understand',
  hotel_search: 'gather',
  itinerary_build: 'build', routing_legs: 'build',
  persisting: 'finalize',  generating: 'finalize',
}
const GROUP_ORDER: ThinkingGroupKey[] = ['understand', 'gather', 'build', 'finalize']

export interface ThinkingGroup {
  key: ThinkingGroupKey
  labelKey: string
  lines: string[]   // câu đã dựng sẵn từ dữ kiện graph, rỗng nếu không có dữ kiện
  reasoning: string // chữ model tự tóm tắt (plan 260819-0931), '' là bình thường
  done: boolean
}
```

**Quy tắc mở/đóng** — nơi mọi lỗi sẽ trốn:

- Phase về → tra nhóm. Chưa có → thêm vào cuối, `done: false`.
- Đã có → **không** thêm dòng mới (supervisor có thể quay lại `routing` nhiều lần), nhưng
  dòng chữ mới vẫn được nối vào `lines` nếu có dữ kiện mới.
- Thêm nhóm mới → mọi nhóm đứng trước theo `GROUP_ORDER` chuyển `done: true`.
- `final` về → mọi nhóm `done: true`.
- Sắp xếp theo `GROUP_ORDER`, **không** theo thứ tự phase tới: `persisting` có thể tới trước
  `routing_legs` ở vài nhánh, và "Hoàn tất" không được nhảy lên trên "Dựng lịch trình".

**Dựng chữ** — `thinking-lines.ts` là hàm thuần `(key, facts) => string[]`:

```ts
// ví dụ: hotel_search
// facts = { destination: "Đà Nẵng", radius_km: 5, found: 24, kept: 8 }
// → ["Tìm địa điểm quanh Đà Nẵng, bán kính 5km",
//    "24 kết quả → lọc còn 8 theo tiện nghi đã chọn"]
// facts = {} → []
```

Mỗi dòng có điều kiện riêng: `found`/`kept` thiếu → bỏ dòng thứ hai, giữ dòng đầu. Không
bao giờ nội suy `undefined` vào câu.

## Related Code Files

- Create: `frontend/src/lib/thinking-groups.ts` + `.test.ts`
- Create: `frontend/src/lib/thinking-lines.ts` + `.test.ts`
- Modify: `frontend/src/types/index.ts` (`ThinkingGroup`, mở rộng extras của `phase`)
- Modify: `frontend/src/hooks/use-chat-session.ts` (state + `STREAM_PHASE` + reset)
- Modify: `frontend/src/i18n/` (nhãn 4 nhóm + template dòng, VI + EN)
- Modify: `frontend/src/hooks/use-chat-session.test.ts`

## Implementation Steps

1. Mở rộng type extras của `phase` trong `types/index.ts` cho khớp schema Phase 2, mọi
   field tuỳ chọn. Thêm `ThinkingGroup`.
2. Viết `thinking-groups.ts` (hàm thuần) + test **trước** khi nối reducer. Ca bắt buộc:
   - chuỗi phase bình thường → 4 nhóm đúng thứ tự
   - `routing` về 3 lần → vẫn 1 dòng "Hiểu yêu cầu"
   - nhánh intake không chạm `itinerary_build` → không có nhóm "Dựng lịch trình"
   - `persisting` tới trước `routing_legs` → thứ tự vẫn theo `GROUP_ORDER`
   - phase key lạ → bỏ qua, không crash
   - `final` → mọi nhóm `done`
3. Viết `thinking-lines.ts` + test. Ca bắt buộc:
   - đủ dữ kiện → đúng câu
   - thiếu một field → bỏ đúng dòng đó, giữ dòng còn lại
   - `facts = {}` → `[]`, **không** có câu chống chế
   - field lạ → bỏ qua
   - tiền/ngày đi qua formatter sẵn có
4. Thêm i18n VI + EN cho nhãn nhóm và template dòng.
5. Nối vào reducer; xoá `thinking` ở đủ 6 chỗ đang xoá `phases`.
6. `npm run test` + `npm run typecheck`.

## Success Criteria

- [x] Hai file lib đều là hàm thuần, test không cần render
- [x] 17 ca `thinking-groups` + 18 ca `thinking-lines` (yêu cầu: 6 + 5)
- [x] `facts = {}` → không dòng nào — có test cho cả 4 key có dữ kiện lẫn 4 key không
- [x] `phases` không đổi (có test reducer); toàn bộ suite FE 280 pass
- [x] `thinking` xoá ở đủ **6** nhánh reset — test từng action
- [x] Không extras → nhóm vẫn dựng, `lines: []` — có test
- [x] i18n đủ VI + EN — 32 khoá mỗi bên, có test đối chiếu
- [x] `npm run typecheck`: 0 lỗi do phase này gây ra (còn lỗi có sẵn ở fixture test khác)

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Quên xoá `thinking` ở một nhánh reset → dính sang lượt sau | Bước 5 liệt kê đủ 6 chỗ; test từng action |
| Template nội suy `undefined` vào câu | Mỗi dòng có điều kiện riêng; ca test "thiếu một field" |
| Trượt dần thành câu mẫu vô nghĩa | Ranh giới ghi thành yêu cầu non-functional + ca test `facts = {}` |
| Vòng lặp supervisor tạo dòng trùng | Ca test "routing 3 lần" |
| Xung đột với plan `260816-2205` Phase 8 (codegen type từ OpenAPI) | Type SSE là hand-written ngoài OpenAPI; đặt type mới cùng vùng đó |

## Bổ sung 2026-08-19 — làn reasoning

Plan `260819-0931` Phase 4 đã ship event SSE `reasoning` (backend xong, hợp đồng đã ghi
trong `docs/chat_api_contract.md`). Phase 5 của plan đó thêm phần FE, và nó **thêm vào**
phase này chứ không thay:

- `stream-client.ts`: thêm `onReasoning?: (text: string) => void` + nhánh
  `case 'reasoning'` trong `switch` sẵn có (`stream-client.ts:163`).
- `use-chat-session.ts`: action `STREAM_REASONING` nối text vào **nhóm đang chạy**, không
  phải một buffer toàn cục.
- `reasoning` phải được xoá ở mọi chỗ `thinking` đang bị xoá.

Bốn thuộc tính của event, đã đo, không phải giả định:

1. **Luôn tiếng Anh**, kể cả hội thoại tiếng Việt và kể cả khi prompt ép ngược lại.
   Không dịch. Nhãn giới thiệu là chữ sản phẩm nên qua i18n; nội dung thì không.
2. **Thường vắng.** Đo live 2026-08-19: prompt khó cho 203 frame, prompt đơn giản cho
   **0 frame**. Không được gate render vào sự xuất hiện của nó.
3. **Không phải prefix của `final.reply`**, không bao giờ nằm trong `final`.
4. **Nhịp khác nhau theo node.** `intake_qa` stream nhiều frame; `qa_node` là subgraph
   biên dịch sẵn nên cả cục về trong **một** frame. UI phải chịu được cả hai — xem
   `plans/reports/debug-260819-qa-node-not-token-streaming.md`.

## ~~CHẶN~~ đã gỡ: chạy trong Docker

`frontend/node_modules` được cài cho **Linux arm64**, máy là **darwin arm64**:

```
node_modules/@typescript/typescript-linux-arm64      ← có
node_modules/@typescript/typescript-darwin-arm64     ← thiếu
node_modules/lightningcss-linux-arm64-gnu|musl       ← có, không có bản darwin
```

Hệ quả: `npm run typecheck` và `npm run test` (vitest → rolldown native) đều ném
`Unable to resolve @typescript/typescript-darwin-arm64`. Không liên quan tới code của
phase này — có sẵn từ trước.

Repo có `docker-compose.yml` với service `frontend` build từ Dockerfile, nên nhiều khả
năng node_modules này là **cố ý** dành cho container. Chạy `npm install` trên macOS sẽ
thay nó và có thể phá luồng Docker, nên **chưa làm** — cần người dùng quyết.

**Cách gỡ (2026-08-19):** `node_modules` là linux-arm64, và container trên Apple Silicon
cũng là linux/arm64 — nên chỉ cần mount vào là chạy được, không phải cài lại gì:

```
docker run --rm -v "$PWD/frontend":/app -w /app node:20-alpine npx vitest run
docker run --rm -v "$PWD/frontend":/app -w /app node:20-alpine npx tsc --noEmit -p tsconfig.json
```

Kết quả: **280 pass / 281**; 1 fail là `merge-active-session.test.ts`, đã chứng minh có
sẵn (stash thay đổi của phase này rồi chạy lại vẫn fail). Typecheck: 0 lỗi do phase này.

**Hai lỗi thật do chạy mới lộ ra:**

1. Test `HOTEL_SELECTION_START` của tôi dựng action thiếu `turnId`, nên guard
   `action.turnId !== state.turnId` trả state nguyên vẹn và test đỏ. Lỗi ở test, không
   phải reducer.
2. `derive-stage.test.ts` dựng một `ChatState` đầy đủ, nên thêm field bắt buộc `thinking`
   làm vỡ typecheck ở đó. Tôi *đã* soát rủi ro này nhưng chỉ grep `use-chat-session.test.ts`
   và sót file kia — đúng loại lỗi mà chỉ trình biên dịch bắt được.

## Lệch plan

### 1. Dữ kiện thật khác ví dụ trong plan

Plan minh hoạ `hotel_search` với `found`/`kept`. Phase 2 đo được `found` **không tồn tại**
ở nơi lấy được, nên nó không được phát. `thinking-lines` dựng câu từ đúng thứ Phase 2
phát: `status`, `destination`, `radius_km`, `amenities`, `kept`.

Thêm vào đó `status` cho phép phân biệt "tìm xong không có" với "tìm lỗi" — hai câu khác
hẳn nhau, và trước đây plan không có chỗ cho sự khác biệt đó.

### 2. Nhóm `build` hiện chưa có dòng nào

`itinerary_build` không phát dữ kiện (Phase 2 ghi rõ lý do: điểm emit nằm trước khi lịch
trình được dựng). `routing_legs` có `days`. Nên nhóm "Dựng lịch trình" chỉ có chữ khi
`routing_legs` chạy.

### 3. Làn reasoning được nối luôn ở đây

`appendReasoning` + action `STREAM_REASONING` + `onReasoning` trong `stream-client.ts`
đã xong, dù plan `260819-0931` Phase 5 nhận phần này. Lý do: helper đã viết và test xong
trong phase này, để nó không có người gọi là code chết — tệ hơn là chồng lấn phạm vi một
chút. Phase 5 của plan kia nhờ đó chỉ còn phần render.

### 4. Ba chỗ suýt sai, phát hiện khi soát

- Regex thay `phases: [],` chỉ bắt **5/6** chỗ reset — chỗ thứ 6 không có dấu phẩy cuối.
- Khai báo `ChatState` nằm ở `types/index.ts:200`, không phải trong hook; phép thế của
  tôi im lặng không khớp (dùng `.replace()` không assert). Đã thêm assert và sửa.
- `i18n.t` gán thẳng vào `Translate` là chỗ dễ lỗi kiểu nhất — đã bọc adapter.
