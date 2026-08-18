---
phase: 3
title: "FE thinking state + render dữ kiện"
status: pending
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
  lines: string[]   // câu đã dựng sẵn, rỗng nếu không có dữ kiện
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

- [ ] Hai file lib đều là hàm thuần, test không cần render
- [ ] Đủ 6 ca của `thinking-groups` + 5 ca của `thinking-lines`
- [ ] `facts = {}` → không dòng nào, không câu chống chế — có test khẳng định
- [ ] `phases` và panel phải không đổi hành vi; `phase-labels.test.ts` xanh nguyên
- [ ] `thinking` xoá ở đủ mọi nhánh reset — test reducer từng action
- [ ] Backend chưa phát extras: nhóm vẫn dựng đúng, chỉ không có dòng chữ
- [ ] i18n đủ VI + EN
- [ ] `npm run typecheck` sạch

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Quên xoá `thinking` ở một nhánh reset → dính sang lượt sau | Bước 5 liệt kê đủ 6 chỗ; test từng action |
| Template nội suy `undefined` vào câu | Mỗi dòng có điều kiện riêng; ca test "thiếu một field" |
| Trượt dần thành câu mẫu vô nghĩa | Ranh giới ghi thành yêu cầu non-functional + ca test `facts = {}` |
| Vòng lặp supervisor tạo dòng trùng | Ca test "routing 3 lần" |
| Xung đột với plan `260816-2205` Phase 8 (codegen type từ OpenAPI) | Type SSE là hand-written ngoài OpenAPI; đặt type mới cùng vùng đó |
