---
phase: 8
title: "Typed contract from OpenAPI"
status: pending
priority: P2
effort: "1d"
dependencies: [1, 2, 4, 5, 7]
---

# Phase 8: Typed contract from OpenAPI

## Overview

`frontend/src/types.ts` được maintain thủ công và verify bằng cách đọc code Python — cách
làm này đã trôi. Phase này sinh type từ `/openapi.json` của FastAPI và để CI chặn drift.
Chạy **cuối cùng** vì nó khóa các shape mà Phase 1-7 còn đang đổi.

## Bằng chứng lỗi

`types.ts` tự khai ở dòng 1-4: *"Verified against backend/src/services/trip_formatter.py"* —
một lần verify thủ công tại một thời điểm. Kết quả trôi:

| Field | Backend | Frontend |
|---|---|---|
| `requires_stay_dates` | luôn `False` (`respond.py:413`) | **không khai báo** |
| `budget`, `budget_currency` | có emit (`trip_formatter.py:461-462`) | **thiếu** trong `TripPlan`; comment `trip-overview-tab.tsx:35` nói *"trip_plan has no budget"* — sai |
| `TripPlan.duration_days` | `int \| None` | bắt buộc `number` |
| `TripPlan.status` | `str \| None` | bắt buộc `TripStatus` |
| `Day.theme` | `str \| None` | bắt buộc `string` |
| `DayItem.order_index` | `int \| None` | bắt buộc `number` |
| `DayItem.activity` | `str \| None` | bắt buộc `string` |
| `SessionSummary.created_at`/`updated_at` | `str \| None` | bắt buộc `string` |

Nhóm nullable là **type lie**: TS tin luôn có giá trị, runtime nhận `null` → crash render
hoặc hiện "undefined".

## Requirements

**Functional**
- Type wire sinh tự động từ `/openapi.json`; không sửa tay.
- CI fail khi backend schema đổi mà chưa regen.
- Type do FE tự định nghĩa (`ChatState`, `IntakeFormShape`, `StageView`…) tách khỏi type
  wire, không bị codegen ghi đè.

**Non-functional**
- Không đòi backend chạy trong CI của frontend — commit file schema, không fetch live.
- Không đổi runtime behavior. Phase này chỉ đổi type; mọi chỗ codegen phơi ra type lie
  phải được sửa **có ý thức**, không bằng cách nới lỏng type.

## Architecture

### Bố cục file

```
frontend/
  openapi.json                 ← snapshot commit vào repo, sinh từ backend
  src/
    types/
      wire.generated.ts        ← openapi-typescript sinh, KHÔNG sửa tay
      index.ts                 ← re-export alias thân thiện + type riêng của FE
    types.ts                   ← xóa, thay bằng types/index.ts
```

`wire.generated.ts` chứa `components['schemas']['PlannerChatResponse']` v.v. — cồng kềnh.
`types/index.ts` đặt alias để mọi import hiện có không phải đổi:

```ts
import type { components } from './wire.generated'

export type PlannerChatResponse = components['schemas']['PlannerChatResponse']
export type HotelOption        = components['schemas']['HotelOption']
export type TripPlan           = components['schemas']['TripPlanPayload']
// … và các type thuần FE giữ nguyên tại đây
export interface ChatState { /* không sinh tự động */ }
```

### Kiểm drift trong CI

```jsonc
// package.json
"scripts": {
  "openapi:dump":  "cd ../backend && python -c \"import json;from src.main import app;print(json.dumps(app.openapi()))\" > ../frontend/openapi.json",
  "openapi:gen":   "openapi-typescript openapi.json -o src/types/wire.generated.ts",
  "openapi:check": "npm run openapi:dump && npm run openapi:gen && git diff --exit-code openapi.json src/types/wire.generated.ts"
}
```

CI chạy `openapi:check` → schema đổi mà chưa commit lại thì `git diff --exit-code` fail.

### Xử lý type lie sau khi sinh

Codegen sẽ biến `duration_days` thành `number | null` và làm vỡ mọi chỗ đang giả định
non-null. Mỗi chỗ vỡ là một quyết định thật, xử lý theo thứ tự ưu tiên:

1. **Backend nên non-null?** — nếu field thực sự luôn có giá trị, sửa Pydantic model
   (thêm default, bỏ `| None`). Đây là lựa chọn đúng cho `TripPlan.status` (đã có
   `or "Draft"` ở `trip_formatter.py:455`) và `duration_days` (luôn được tính).
2. **Thật sự nullable?** — sửa call site FE xử lý null tử tế.
3. **Không bao giờ** dùng `as` hay `!` để dập lỗi.

Ước lượng: khoảng 8-12 điểm vỡ, phần lớn thuộc nhóm 1.

## Related Code Files

- Create: `frontend/openapi.json`
- Create: `frontend/src/types/wire.generated.ts`
- Create: `frontend/src/types/index.ts`
- Delete: `frontend/src/types.ts`
- Modify: `frontend/package.json` — thêm `openapi-typescript` (devDependency) + 3 script
- Modify: `.github/workflows/` — thêm bước `openapi:check`
- Modify: `backend/src/models/schemas.py` — siết nullability cho field thực sự luôn có giá trị
- Modify: các component FE tại điểm vỡ (`trip-overview-tab.tsx`, `day-timeline.tsx`, `conversation-list.tsx`, …)

## Implementation Steps

1. **Chốt tiền đề:** Phase 1, 2, 4, 5, 7 đã merge. Nếu chưa, dừng — sinh type trên shape
   đang đổi là công toi.
2. Thêm `openapi-typescript` vào devDependencies; thêm 3 script.
3. Chạy `openapi:dump` + `openapi:gen`, commit cả hai file.
4. Tạo `types/index.ts` với alias cho mọi type mà `types.ts` đang export. Đối chiếu danh
   sách export cũ để không sót — `grep -rn "from '../types'" frontend/src | wc -l` trước
   và sau phải khớp.
5. Xóa `types.ts`, chạy `npm run typecheck`. Ghi lại **toàn bộ** lỗi vào một danh sách.
6. Phân loại từng lỗi theo 3 nhóm ở Architecture. Sửa backend trước (nhóm 1), regen, rồi
   mới sửa FE (nhóm 2).
7. Sửa comment sai ở `trip-overview-tab.tsx:35` và bổ sung hiển thị `budget`/
   `budget_currency` nếu design yêu cầu — **hoặc** ghi rõ là cố ý không hiển thị.
8. Thêm bước CI. Verify bằng cách sửa một field backend, chạy CI cục bộ, xác nhận đỏ.
9. Chạy `npm test` — test hiện có dùng fixture theo type cũ có thể vỡ.

## Success Criteria

- [ ] `frontend/src/types.ts` không còn tồn tại; mọi import trỏ `types/index.ts`
- [ ] `npm run typecheck` xanh, không có `as any` / `!` mới nào được thêm
- [ ] Sửa một field trong `schemas.py` mà không regen → CI đỏ
- [ ] `requires_stay_dates` hoặc đã bị xóa khỏi backend, hoặc đã có trong type FE
- [ ] `budget`/`budget_currency` có trong `TripPlan`; comment sai đã sửa
- [ ] Không còn field nullable nào bị FE khai là bắt buộc
- [ ] `npm test` xanh

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| **Chạy trước khi Phase 1-7 xong → sinh lại từ đầu** | Cao | Bước 1 là cổng chặn cứng. `dependencies: [1,2,4,5,7]` trong frontmatter |
| Số điểm vỡ lớn hơn ước lượng, phase phình ra | Trung bình | Bước 5 liệt kê hết trước khi sửa. Nếu >25 điểm, tách nhóm 2 sang phase riêng thay vì làm vội |
| Cám dỗ dùng `as`/`!` để đi nhanh | Cao | Success Criteria kiểm rõ. Đây là rủi ro chính khiến phase này mất giá trị |
| `openapi-typescript` sinh tên type khó dùng | Thấp | Lớp alias ở `types/index.ts` cách ly hoàn toàn |
| Script `openapi:dump` cần Python env của backend | Trung bình | CI đã cài backend deps cho test suite. Nếu không, thay bằng bước riêng chạy trong job backend rồi upload artifact |
| Comment tài liệu quý trong `types.ts` bị mất | Trung bình | Nhiều comment trong `types.ts` ghi kiến thức thật (định dạng `coordinates`, tại sao `route_from_hotel` thường null). **Chuyển sang `types/index.ts`**, đừng xóa cùng file |
