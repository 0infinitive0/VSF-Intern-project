---
phase: 6
title: "Dọn dead code frontend và i18n"
status: pending
priority: P3
effort: "2-3h"
dependencies: []
---

# Phase 6: Dọn dead code frontend và i18n

## Overview

Xoá 2 component không ai import, 2 export chết, 2 type chết, và 35 key i18n
không được dùng. Sửa lệch plural form giữa `en` và `vi`. Không phụ thuộc phase
nào — làm song song được.

## Requirements

**Functional**
- `npm run lint` → 0 cảnh báo
- `npm run typecheck` → 0 lỗi
- `npm run test` → xanh
- `en.json` và `vi.json` cùng tập key

**Non-functional**
- Không đụng API client cho endpoint chưa implement (thuộc plan khác)
- Không thay đổi chuỗi hiển thị của key đang được dùng

## Architecture

### Component không ai import

| File | Dòng | Bằng chứng |
|---|---|---|
| `src/components/glass-panel.tsx` | 31 | 0 file import. Tên `glass-panel` còn sống nhưng dưới dạng **CSS utility** (`styles.css:208`), dùng trực tiếp qua `className` ở `sidebar-rail.tsx:43`. Component React thì không ai dùng |
| `src/components/stay-date-form.jsx` | 62 | 0 file import. Là file `.jsx` **duy nhất** trong codebase TypeScript. Đang tạo cảnh báo oxlint duy nhất của cả project (`:11` biến `today` không dùng) |

`stay-date-form.jsx` đã bị thay bằng `intake-date-range.tsx` (dùng
`@daypicker/react`). Backend vẫn có `StayDatesInput` (`schemas.py:216`) và
`PlannerChatRequest.stay_dates` — hợp đồng API còn sống, chỉ component cũ chết.
**Không** đụng phía backend.

### Export chết

| File | Symbol | Ghi chú |
|---|---|---|
| `src/api/chat-client.ts` | `getPlan` | 0 consumer. `use-chat-session.ts:146` gọi thẳng `fetch('/api/v1/chat/{id}/plan')` chứ không qua helper này |
| `src/types.ts` | `TerminalStreamEvent` | 0 usage, và không plan treo nào nhắc tới |

### Hai symbol trông chết nhưng KHÔNG được xoá

Ranh giới quan trọng nhất của phase: **"chưa ai gọi" ≠ "chết"** khi có plan đang
treo mô tả đúng chỗ dùng. Kiểm tra chéo đã xác nhận:

| Symbol | Chủ sở hữu | Bằng chứng |
|---|---|---|
| `src/api/place-client.ts` `getAttractionDetail` | `260805-1022-.../phase-09-fe-stage-workspace-focus.md` (`pending`) | Dòng 16 và 90: tiêu thụ `GET /attractions/{id}` cho Workspace Focus Mode |
| `src/types.ts` `TurnPhase` | `260806-1602-.../phase-05-frontend-streaming-consumption.md` (`todo`) | Dòng 79: `phases: TurnPhase[]`; dòng 136: "Modify: `frontend/src/types.ts` — `TurnPhase`, `PhaseKey`, 3 field trên `ChatState`" |

### i18n

**Lệch plural form** — `en.json` có `generatingElapsed_one` + `generatingElapsed_other`
(dạng plural i18next), `vi.json` chỉ có `generatingElapsed` phẳng. Tiếng Việt
không chia số nhiều nên `vi.json` đúng theo cách viết phẳng, nhưng i18next cần
`_other` tối thiểu khi key được gọi kèm `count`. Kiểm chỗ gọi
(`stage-generating.tsx`) để xác định key được dùng có `count` không, rồi thống
nhất một dạng cho cả hai file.

**35/195 key không được dùng.** Nhóm lớn nhất (18 key) là form intake cũ, đã bị
thay bởi các component chip/stepper:

```
intakeDestinationPlaceholder, intakeDatesLabel, intakeStartDateLabel,
intakeEndDateLabel, intakeDatePlaceholder, intakeGuestsLabel,
intakeOtherOptionsLabel, intakeCompanionsLabel, intakePaceLabel,
intakeDayRhythmLabel, intakeNotesLabel, intakeNotesPlaceholder,
intakeNotesCounter, intakeSubmit, intakeRequiredHint,
intakeDecreaseGuests, intakeIncreaseGuests, intakeNoBudgetOptions
```

Còn lại: `intakeStep1..3Num/Title/Desc` (9), `chatPanelMoreHint`,
`chatPanelExpandHint`, `messageTimestampLabel`, `statusLabel`, `errorPrefix`,
`errorStage`.

Quét bằng đối chiếu key phẳng với toàn bộ `.ts`/`.tsx`. Phương pháp này **không
bắt được key dựng động** (`t(\`kind${x}\`)`). Trước khi xoá, grep tiền tố:

```bash
grep -rnE "t\(\`|t\((['\"])?\\\$\{" frontend/src --include='*.tsx' --include='*.ts'
```

Nếu có key dựng động, loại tiền tố tương ứng khỏi danh sách xoá. Ví dụ đã biết:
`kindBreakfast`/`kindLunch`/... được `day-card.tsx` dùng — quét đã bắt đúng, nhưng
đó là may mắn chứ không phải bảo đảm.

Backend cũng có catalog gettext (`backend/locales/{en,vi}/LC_MESSAGES`) — **không
thuộc phạm vi phase này**, hệ thống khác, vòng đời khác.

## Related Code Files

- Delete: `frontend/src/components/glass-panel.tsx`
- Delete: `frontend/src/components/stay-date-form.jsx`
- Modify: `frontend/src/api/chat-client.ts` — xoá `getPlan`
- Modify: `frontend/src/types.ts` — xoá `TerminalStreamEvent`
- Modify: `frontend/src/i18n/locales/en.json`, `vi.json` — xoá key chết, thống nhất plural
- Keep: `frontend/src/api/place-client.ts` — `getAttractionDetail` (phase-09 sở hữu)
- Keep: `frontend/src/types.ts` — `TurnPhase` (streaming phase-05 sở hữu)

## Implementation Steps

1. Xác nhận lại phạm vi loại trừ: `getAttractionDetail` và `TurnPhase` **không**
   nằm trong phase này. Nếu plan sở hữu đã bị huỷ trong thời gian chờ, mở lại
   quyết định này.
2. Xoá `glass-panel.tsx`. Xác nhận CSS utility `glass-panel` ở `styles.css:208`
   **vẫn giữ nguyên** — `sidebar-rail.tsx` phụ thuộc vào nó.
3. Xoá `stay-date-form.jsx`. Grep chuỗi class CSS trước khi xoá:
   ```bash
   grep -rn "stay-date-form" frontend/src --include='*.css'
   ```
   Nếu `styles.css` có block cho class này, xoá luôn.
4. Xoá `getPlan` khỏi `chat-client.ts`. Cân nhắc: `use-chat-session.ts:146` đang
   `fetch` thẳng thay vì dùng helper — hoặc xoá helper, hoặc để hook dùng nó.
   Dùng lại helper nhất quán hơn; nếu chọn hướng đó thì đây là refactor nhỏ, ghi
   rõ trong PR.
5. Xoá `TerminalStreamEvent` khỏi `types.ts`. **Giữ** `TurnPhase`.
6. Grep key i18n dựng động (lệnh ở Architecture). Loại tiền tố bị ảnh hưởng khỏi
   danh sách xoá.
7. Xoá 35 key khỏi **cả** `en.json` và `vi.json`. Giữ hai file cùng tập key.
8. Sửa lệch `generatingElapsed`: đọc chỗ gọi ở `stage-generating.tsx`, thống nhất
   dạng plural cho cả hai ngôn ngữ.
9. Thêm một test đối chiếu key giữa hai file locale vào `frontend/src/lib/`
   (vitest đã có sẵn) — chặn lệch tái phát:
   ```ts
   // so sánh tập key phẳng của en.json và vi.json
   ```
10. Chạy `npm run lint && npm run typecheck && npm run test`.
11. Kiểm bằng mắt trên UI: đổi ngôn ngữ vi ↔ en, đi qua luồng intake → hotels →
    plan, xác nhận không có chuỗi nào hiện ra dạng raw key.

## Success Criteria

- [ ] `cd frontend && npm run lint` → 0 cảnh báo
- [ ] `cd frontend && npm run typecheck` → 0 lỗi
- [ ] `cd frontend && npm run test` → xanh, có thêm test đối chiếu key locale
- [ ] `en.json` và `vi.json` cùng tập key (test tự động xác minh)
- [ ] `find frontend/src -name '*.jsx'` → rỗng
- [ ] Đi hết luồng chính ở cả 2 ngôn ngữ, 0 raw key hiện trên UI
- [ ] `getAttractionDetail` và `TurnPhase` **vẫn còn** (plan khác sở hữu)

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Xoá key i18n đang được dựng động → raw key hiện trên UI | Bước 6 grep template literal. Bước 11 kiểm tay cả 2 ngôn ngữ. Đây là loại lỗi typecheck không bắt được |
| Người thực thi thấy `TurnPhase`/`getAttractionDetail` "0 usage" rồi xoá theo phản xạ | Đã loại trừ tường minh ở 4 chỗ trong phase này, kèm tiêu chí nghiệm thu ngược ("vẫn còn") |
| Xoá CSS utility `glass-panel` cùng component | Bước 2 nêu rõ: giữ CSS, xoá component. Hai thứ khác nhau trùng tên |
| Sửa plural làm hỏng chuỗi đang hiển thị đúng | Bước 8 đọc chỗ gọi trước. Bước 11 xác minh bằng mắt |
| Test đối chiếu key làm đỏ CI khi cố tình thêm key một bên | Đó là mục đích. Quy trình: thêm key vào cả hai file cùng lúc |
